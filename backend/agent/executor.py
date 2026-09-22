"""Executor — the only component allowed to run tools (spec §10, §13).

Responsibilities:
    * permission gate: allow / confirm-ask / deny
    * emergency-stop checks between steps
    * retries + error recovery delegation
    * step recording (status, output, duration, attempts)
    * cancellation support (asyncio.CancelledError → TaskCancelled)
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from core.exceptions import (
    ConfirmationRequired,
    EmergencyStop,
    NovaError,
    TaskCancelled,
)
from permissions import DECISION_ALLOW, DECISION_ASK, DECISION_DENY, PermissionManager
from planner.planner import PlanStep
from tools import ToolRegistry
from tools.base import ToolResult


class Executor:
    def __init__(
        self,
        registry: ToolRegistry,
        permissions: PermissionManager,
        settings: Any,
        event_bus: Any = None,
        *,
        observer: Any = None,
        record_step: Callable | None = None,
        on_confirmation: Callable | None = None,
    ) -> None:
        self.registry = registry
        self.permissions = permissions
        self.settings = settings
        self.event_bus = event_bus
        self.observer = observer
        self.record_step = record_step  # callback(step_idx, status, payload, result)
        self.on_confirmation = on_confirmation

    # ------------------------------------------------------------------
    def _emit(self, event: str, **data) -> None:
        if self.event_bus:
            self.event_bus.emit(event, data)

    def _confirm_decided(self, decision: str) -> bool:
        # DECISION_ASK never reaches here; it becomes a confirmation request.
        return decision == DECISION_ALLOW

    # ------------------------------------------------------------------
    async def execute_step(self, step: PlanStep, *, task_id: str,
                           step_index: int, attempt_context: dict) -> ToolResult:
        tool = self.registry.get(step.tool)  # raises ToolNotFound if missing
        definition = tool.to_definition()

        # 1. emergency-stop gate
        _check_stop_flag(self.permissions)

        # 2. permission decision
        decision = self.permissions.check(definition, step.arguments, task_id)
        if decision == DECISION_DENY:
            self._emit("agent.step_denied", tool=step.tool, task_id=task_id)
            return ToolResult.fail(f"Denied by permission policy for {step.tool}",
                                   "PERMISSION")

        if decision == DECISION_ASK:
            detail = tool.summarize_confirmation(step.arguments, task_id)
            question = self.permissions.request_confirmation(
                definition, step.arguments, task_id, detail=detail).question
            self._emit("agent.waiting_confirmation", tool=step.tool, task_id=task_id,
                       question=question)
            raise ConfirmationRequired(
                f"Permission required for '{step.tool}'",
                tool=step.tool, task_id=task_id,
                question=self.permissions.store.get_for_task(task_id).question
                if self.permissions.store.get_for_task(task_id) else f"Allow {step.tool}?")

        # 3. execute (with retries handled by TaskManager; here a single run)
        self._emit("agent.executing", tool=step.tool, task_id=task_id,
                   step_index=step_index)
        started = time.monotonic()
        try:
            result = await tool.execute(step.arguments, task_id=task_id)
        except asyncio.CancelledError:
            self._emit("agent.cancelled", task_id=task_id)
            raise TaskCancelled(f"Cancelled during {step.tool}") from None
        except NovaError as exc:
            result = ToolResult.fail(str(exc), getattr(exc, "code", "TOOL_ERROR"))
        duration = int((time.monotonic() - started) * 1000)
        result.duration_ms = result.duration_ms or duration

        # 4. post-execution verification hook
        if result.success and definition.verify_after:
            try:
                verify = await tool.verify(step.arguments, task_id=task_id)
            except Exception:
                verify = ToolResult.ok(None, message="verified")
            if verify.success is False:
                result = ToolResult.fail(
                    f"verification failed: {verify.error or verify.message}",
                    "VERIFY_FAILED", data={"verify": verify.as_dict()})

        self._emit("agent.step_completed" if result.success else "agent.step_failed",
                   tool=step.tool, task_id=task_id, ok=result.success)
        if self.record_step:
            self.record_step(step_index, "completed" if result.success else "failed",
                             step, result)
        return result

    # ------------------------------------------------------------------
    async def execute_plan(self, plan, *, task_id: str,
                           stop_event: asyncio.Event | None = None,
                           cancel_check: Callable[[], bool] | None = None,
                           confirm_callback: Callable | None = None,
                           max_steps: int = 30) -> dict:
        """Run a whole plan. Used directly by tests and headless flows."""
        results: list[ToolResult] = []
        files: list[str] = []
        for i, step in enumerate(plan.steps[:max_steps]):
            if cancel_check and cancel_check():
                raise TaskCancelled("cancelled by user")
            if stop_event and stop_event.is_set():
                raise TaskCancelled("cancelled by user")
            _check_stop_flag(self.permissions)
            attempt = 0
            max_retries = self.settings.get_int("automation.max_retries", 2)
            result: ToolResult | None = None
            while attempt <= max_retries:
                try:
                    result = await self.execute_step(
                        step, task_id=task_id, step_index=i,
                        attempt_context={"attempts": attempt})
                    break
                except ConfirmationRequired as creq:
                    if confirm_callback is not None:
                        approved = await confirm_callback(creq)
                        if approved:
                            # session-allow just this tool for this task
                            self.permissions.set_session_rule(creq.tool, DECISION_ALLOW)
                            result = await self.execute_step(
                                step, task_id=task_id, step_index=i,
                                attempt_context={"attempts": attempt})
                            break
                        raise TaskCancelled(f"declined: {creq.tool}") from None
                    raise
                except NovaError as exc:
                    result = ToolResult.fail(str(exc), getattr(exc, "code", "TOOL_ERROR"))
            if result is None:
                result = ToolResult.fail("no result produced", "EXECUTOR_ERROR")
            results.append(result)
            if result.data and isinstance(result.data, dict):
                p = result.data.get("path") or (result.output or {}).get("path") if isinstance(result.output, dict) else None
                if p:
                    files.append(str(p))
            # short pause between steps to let the OS settle
            await asyncio.sleep(0.05)
        return {"results": results, "files_changed": files[:200]}


def _check_stop_flag(permissions: PermissionManager) -> None:
    """Borrow store's emergency latch; the store lives on PermissionManager."""
    stop = getattr(permissions, "emergency", None)
    if stop is not None and stop.active:
        raise EmergencyStop("Emergency stop active — execution halted.")
