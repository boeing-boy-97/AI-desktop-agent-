"""core.* — runtime control tools backing voice interrupts (V2 §8/§31/§75).

``core.cancel``   cancel the active task AND every queued task
``core.pause``    pause the active task before its next step
``core.resume``   resume a paused task

These exist so "Stop everything" / "Pause" / "Resume" spoken through the
planner produce real, verified behavior instead of a ToolNotFound failure.
"""
from __future__ import annotations

from tools.base import PermissionLevel, Tool, ToolResult


class CoreCancelTool(Tool):
    name = "core.cancel"
    description = "Cancel the active task and every queued task immediately."
    permission = PermissionLevel.LOW
    category = "system"
    timeout = 10
    verify_after = False

    async def run(self, args, task_id=None) -> ToolResult:
        rt = getattr(self.ctx, "runtime", None)
        if not rt:
            return ToolResult.fail("runtime unavailable", "NO_RUNTIME")
        # do not cancel ourselves mid-flight (this task) — cancel the rest
        active = rt.tasks.active_task
        queued = list(rt.tasks.queue)
        cancelled = 0
        for tid in queued:
            if tid != task_id and rt.tasks.cancel(tid, "user_cancel"):
                cancelled += 1
        if active and active != task_id and rt.tasks.cancel(active, "user_cancel"):
            cancelled += 1
        if cancelled == 0 and not active and not queued:
            return ToolResult.ok({"cancelled": 0}, message="Nothing is running.")
        return ToolResult.ok({"cancelled": cancelled},
                             message=f"Cancelled {cancelled} task(s).")


class CorePauseTool(Tool):
    name = "core.pause"
    description = "Pause the active task before its next step."
    permission = PermissionLevel.LOW
    category = "system"
    timeout = 10
    verify_after = False

    async def run(self, args, task_id=None) -> ToolResult:
        rt = getattr(self.ctx, "runtime", None)
        if not rt:
            return ToolResult.fail("runtime unavailable", "NO_RUNTIME")
        active = rt.tasks.active_task
        if not active or active == task_id:
            return ToolResult.fail("No other task is running to pause.",
                                   "NOTHING_TO_PAUSE")
        if rt.tasks.pause(active):
            return ToolResult.ok({"paused": active}, message="Task paused.")
        return ToolResult.fail("The task could not be paused in its current "
                               "state.", "PAUSE_REFUSED")


class CoreResumeTool(Tool):
    name = "core.resume"
    description = "Resume the paused task."
    permission = PermissionLevel.LOW
    category = "system"
    timeout = 10
    verify_after = False

    async def run(self, args, task_id=None) -> ToolResult:
        rt = getattr(self.ctx, "runtime", None)
        if not rt:
            return ToolResult.fail("runtime unavailable", "NO_RUNTIME")
        active = rt.tasks.active_task
        if not active:
            return ToolResult.fail("No task is paused.", "NOTHING_PAUSED")
        if rt.tasks.resume(active):
            return ToolResult.ok({"resumed": active}, message="Task resumed.")
        return ToolResult.fail("The task is not paused.", "NOT_PAUSED")
