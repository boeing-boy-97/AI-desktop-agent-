"""Planner module — converts intent (user command + context) into structured steps.

Two planners are provided:

    * **IntelligentPlanner** — uses the configured AIProvider (tool-calling-style
      JSON output) to select tools from the registry. Covers §13, §43 (semantic
      intent) and §44 (conversational memory).
    * **HeuristicPlanner** — deterministic offline planner for common intents,
      used when the AI provider is unavailable (or in demo/tests) so voice
      commands still work end-to-end.

Both produce :class:`TaskPlan`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.config import Settings
from core.utils import robust_json_parse
from tools import ToolRegistry


@dataclass
class PlanStep:
    seq: int
    tool: str
    arguments: dict = field(default_factory=dict)
    rationale: str = ""

    def as_dict(self) -> dict:
        return {"seq": self.seq, "tool": self.tool,
                "arguments": self.arguments, "rationale": self.rationale}


@dataclass
class TaskPlan:
    goal: str
    steps: list[PlanStep] = field(default_factory=list)
    mode: str = "smart"
    source: str = "heuristic"
    raw: dict | None = None

    def as_dict(self) -> dict:
        return {"goal": self.goal, "mode": self.mode, "source": self.source,
                "steps": [s.as_dict() for s in self.steps]}


class Planner:
    """Base planner interface."""

    def __init__(self, settings: Settings, registry: ToolRegistry,
                 ai_provider: Any, memory_context: Any = None) -> None:
        self.settings = settings
        self.registry = registry
        self.ai = ai_provider
        self.memory = memory_context

    async def plan(self, command: str, *, mode: str = "smart",
                   context: list[dict] | None = None,
                   session: dict | None = None) -> TaskPlan:
        """Plan a task.

        SECURITY CONTRACT (V2 §45): *command* is always the user's own
        utterance.  External content (webpages, files, OCR, messages) is
        never passed here — it flows through tools strictly as data.
        """
        raise NotImplementedError

    # -- shared helpers --------------------------------------------------
    def _catalog(self, limit: int = 90) -> str:
        lines = []
        for d in self.registry.definitions():
            lines.append(f"- {d.name} [{d.permission_level}] :: {d.description}")
            if len(lines) >= limit:
                break
        return "\n".join(lines)

    def _reject_unknown_tools(self, steps: list[PlanStep]) -> list[PlanStep]:
        known = set(self.registry.names())
        cleaned: list[PlanStep] = []
        for st in steps:
            if st.tool in known:
                cleaned.append(PlanStep(seq=len(cleaned), tool=st.tool,
                                        arguments=st.arguments, rationale=st.rationale))
        return cleaned


class IntelligentPlanner(Planner):
    """LLM-driven planning with strict tool whitelisting + validation."""

    _SYSTEM = (
        "You are NOVA, a Windows desktop voice agent. Turn the user's request "
        "into a minimal, safe plan of tool calls.\n"
        "Respond with STRICT JSON only: {\"goal\": \"...\", \"steps\": ["
        "{\"seq\": 0, \"tool\": \"<tool name>\", \"arguments\": {...}, "
        "\"rationale\": \"...\"}]}.\n"
        "Rules:\n"
        "  * Use ONLY tools from the provided catalog.\n"
        "  * Prefer direct APIs/filesystem tools over raw clicks (§54).\n"
        "  * Never suggest shell commands unless the catalog's shell.run tool "
        "    is genuinely needed; the execution layer enforces safety.\n"
        "  * High-risk actions (delete, send_message, shutdown) are allowed in "
        "    the plan — the permission system will confirm them with the user.\n"
        "  * For project 'build' requests, plan: filesystem.create_folder, "
        "    filesystem.write_file, shell.run (npm install / build), "
        "    shell.run (fix errors), then computer.launch_app to open it.\n"
        "  * Keep steps ≤ 12. Do not invent tools."
    )

    async def plan(self, command: str, *, mode: str = "smart",
                   context: list[dict] | None = None,
                   session: dict | None = None) -> TaskPlan:
        from providers.ai import MockProvider
        if isinstance(self.ai, MockProvider):
            return (await _heuristic(self.settings, self.registry,
                                     self.ai, self.memory)
                    .plan(command, mode=mode, context=context, session=session))

        catalog = self._catalog()
        memory_note = ""
        if self.memory is not None:
            facts = self.memory.relevant(command)
            if facts:
                memory_note = "\nRemembered context (use these paths/facts):\n" + "\n".join(
                    f"- {k}: {v['value']}" for k, v in facts.items()) + "\n"
        history_note = ""
        if context:
            last = context[-1]
            history_note = (f"\nConversational memory: the current context is "
                            f"'{last.get('name', '')}'. '{command}' may refer to it.\n")

        user = (f"Tool catalog:\n{catalog}\n{memory_note}{history_note}"
                f"User request: {command}\n"
                f"Mode: {mode}\n"
                f"Return STRICT JSON with goal+steps.")

        from providers.ai import ChatMessage as CM
        messages = [CM("system", self._SYSTEM), CM("user", user)]
        try:
            resp = await self.ai.chat(messages)
        except Exception:
            # Provider unreachable / unconfigured → heuristic fallback keeps
            # voice commands working offline (never dead-ends the task).
            return (await _heuristic(self.settings, self.registry,
                                     self.ai, self.memory)
                    .plan(command, mode=mode, context=context))
        parsed = robust_json_parse(resp.content)
        if not parsed:
            # Provider returned non-JSON — fall back to heuristics.
            return (await _heuristic(self.settings, self.registry,
                                     self.ai, self.memory)
                    .plan(command, mode=mode, context=context))
        steps = []
        for raw_step in parsed.get("steps", [])[:16]:
            tool = str(raw_step.get("tool", "")).strip()
            if not tool:
                continue
            args = raw_step.get("arguments") or {}
            if not isinstance(args, dict):
                args = {}
            steps.append(PlanStep(seq=len(steps), tool=tool, arguments=args,
                                  rationale=str(raw_step.get("rationale", ""))))
        steps = self._reject_unknown_tools(steps)
        if not steps:
            return (await _heuristic(self.settings, self.registry,
                                     self.ai, self.memory)
                    .plan(command, mode=mode, context=context))
        return TaskPlan(goal=str(parsed.get("goal", command)), steps=steps,
                        mode=mode, source="intelligent", raw=parsed)


def _heuristic(settings, registry, ai, memory):
    """Lazy import to avoid a circular import with planner.heuristic."""
    from planner.heuristic import HeuristicPlanner
    return HeuristicPlanner(settings, registry, ai, memory)
