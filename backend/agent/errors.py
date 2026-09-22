"""Error classification + recovery strategies (spec §21)."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from tools.base import ToolResult


@dataclass
class RepairAction:
    """One concrete recovery tactic for a failed tool step."""
    description: str
    kind: str                      # retry | replace_tool | reobserve | abandon
    delay_seconds: float = 0.5
    new_tool: str | None = None
    new_arguments: dict | None = None


ERROR_KNOWLEDGE: dict[str, list[RepairAction]] = {
    "NOT_FOUND": [
        RepairAction("Re-check current state with a screen observation.",
                     "reobserve"),
        RepairAction("Retry the action once more.", "retry", delay_seconds=1.0),
    ],
    "TOOL_TIMEOUT": [
        RepairAction("Increase patience and retry once.", "retry", delay_seconds=2.0),
    ],
    "NOT_AVAILABLE": [
        RepairAction("Use the documented fallback method.", "retry", delay_seconds=0.5),
        RepairAction("Report the platform limitation clearly.", "abandon"),
    ],
    "NETWORK_ERROR": [
        RepairAction("Retry the request.", "retry", delay_seconds=1.5),
    ],
    "PERMISSION": [
        RepairAction("Ask the user for permission.", "reobserve"),
    ],
    "EXECUTION_BLOCKED": [
        RepairAction("Substitute with a safe alternative.", "replace_tool"),
    ],
    "CLI_ERROR": [
        RepairAction("Read the error output and retry with corrections.", "retry",
                     delay_seconds=1.0),
    ],
    "HTTP_ERROR": [
        RepairAction("Retry with backoff.", "retry", delay_seconds=2.0),
    ],
    "IO_ERROR": [
        RepairAction("Inspect state and retry once.", "reobserve"),
    ],
    "SAFETY": [
        RepairAction("Abort — path/command is protected.", "abandon"),
    ],
}


class ErrorClassifier:
    """Classify a failed ToolResult into an error category and repair plan."""

    def __init__(self, max_retries: int = 2) -> None:
        self.max_retries = max_retries

    def classify(self, result: ToolResult) -> tuple[str, list[RepairAction]]:
        code = (result.error_code or "TOOL_ERROR").split("-")[0]
        # Normalise compound codes
        if code not in ERROR_KNOWLEDGE:
            code = _normalise(code)
        plan = ERROR_KNOWLEDGE.get(code, ERROR_KNOWLEDGE["NOT_FOUND"])
        return code, list(plan)

    async def recover(self, tool_name: str, result: ToolResult,
                      step_ctx: dict) -> tuple[bool, str, Any]:
        """Attempt recovery. Returns (recovered, message, fallback_result)."""
        code, plan = self.classify(result)
        for action in plan:
            if action.kind == "retry":
                if step_ctx.get("attempts", 0) >= self.max_retries:
                    continue
                await asyncio.sleep(action.delay_seconds)
                return True, f"retrying {tool_name} after {code}", None
            if action.kind == "abandon":
                return False, action.description, result
            if action.kind == "replace_tool":
                return True, action.description, {
                    "tool": action.new_tool, "description": action.description}
            if action.kind == "reobserve":
                return True, f"re-observing state before {tool_name}", None
        return False, f"no recovery available for {code}", result


def _normalise(code: str) -> str:
    code = code.upper()
    for known in ("NOT_FOUND", "TIMEOUT", "NOT_AVAILABLE", "NETWORK", "PERMISSION",
                  "BLOCKED", "CLI", "HTTP", "IO", "SAFETY", "DISABLED", "SIZE"):
        if code.startswith(known):
            mapping = {"BLOCKED": "NOT_AVAILABLE", "DISABLED": "NOT_AVAILABLE",
                       "SIZE": "NOT_AVAILABLE", "CLI": "CLI_ERROR",
                       "HTTP": "HTTP_ERROR", "IO": "IO_ERROR", "NETWORK": "NETWORK_ERROR",
                       "TIMEOUT": "TOOL_TIMEOUT", "NOT_FOUND": "NOT_FOUND",
                       "NOT_AVAILABLE": "NOT_AVAILABLE", "PERMISSION": "PERMISSION",
                       "SAFETY": "SAFETY"}
            return mapping.get(known, "NOT_FOUND")
    return "NOT_FOUND"
