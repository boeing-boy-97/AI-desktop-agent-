"""introspection.* — developer/self-inspection commands (V2 §59/§58).

Lets the user ask NOVA about itself in natural language:

    "Show current plan."   -> introspection.plan
    "Show current task."   -> introspection.task
    "Show last error."     -> introspection.last_error
    "List tools."          -> introspection.tools
    "List permissions."    -> introspection.permissions
    "Show memory."         -> memory.list (existing)
    "Run diagnostics."     -> introspection.diagnostics

All read-only (LOW permission), all produce structured output the UI can
render and the TTS can summarise.
"""
from __future__ import annotations

from tools.base import PermissionLevel, Tool, ToolResult


def _runtime(ctx):
    return getattr(ctx, "runtime", None)


class ShowPlanTool(Tool):
    name = "introspection.plan"
    description = "Show the plan of the active (or most recent) task."
    permission = PermissionLevel.LOW
    category = "developer"
    timeout = 10
    verify_after = False

    async def run(self, args, task_id=None) -> ToolResult:
        rt = _runtime(self.ctx)
        if not rt:
            return ToolResult.fail("runtime unavailable", "NO_RUNTIME")
        tid = rt.tasks.active_task
        if not tid:
            recent = rt.store.recent(limit=1)
            tid = recent[0]["id"] if recent else None
        if not tid:
            return ToolResult.ok({"plan": None}, message="No task has run yet.")
        rec = rt.store.get(tid) or {}
        plan = rec.get("plan") or {}
        steps = [{"seq": s.get("seq"), "tool": s.get("tool"),
                  "arguments": s.get("arguments")}
                 for s in (plan.get("steps") or [])]
        return ToolResult.ok(
            {"task_id": tid, "goal": plan.get("goal"),
             "source": plan.get("source"), "status": rec.get("status"),
             "steps": steps},
            message=f"Plan for '{rec.get('command')}': {len(steps)} step(s).")


class ShowTaskTool(Tool):
    name = "introspection.task"
    description = "Show the current task, state and step progress."
    permission = PermissionLevel.LOW
    category = "developer"
    timeout = 10
    verify_after = False

    async def run(self, args, task_id=None) -> ToolResult:
        rt = _runtime(self.ctx)
        if not rt:
            return ToolResult.fail("runtime unavailable", "NO_RUNTIME")
        tid = rt.tasks.active_task
        rec = rt.store.get(tid) if tid else None
        if not rec:
            return ToolResult.ok(
                {"state": rt.tasks.state, "task": None},
                message=f"Agent is {rt.tasks.state.lower()}; no task in flight.")
        steps = rec.get("steps") or []
        done = sum(1 for s in steps if s.get("status") == "completed")
        return ToolResult.ok(
            {"state": rt.tasks.state, "task_id": tid,
             "command": rec.get("command"), "status": rec.get("status"),
             "steps_done": done, "steps_total": len(steps),
             "queued": rt.tasks.queue},
            message=f"Task '{rec.get('command')}' is {rec.get('status')} "
                    f"({done}/{len(steps)} steps). Agent state: {rt.tasks.state}.")


class LastErrorTool(Tool):
    name = "introspection.last_error"
    description = "Show the most recent error from any task."
    permission = PermissionLevel.LOW
    category = "developer"
    timeout = 10
    verify_after = False

    async def run(self, args, task_id=None) -> ToolResult:
        rt = _runtime(self.ctx)
        if not rt:
            return ToolResult.fail("runtime unavailable", "NO_RUNTIME")
        for rec in rt.store.recent(limit=15):
            if rec.get("error"):
                return ToolResult.ok(
                    {"task_id": rec.get("id"), "command": rec.get("command"),
                     "error": rec.get("error"), "status": rec.get("status")},
                    message=f"Last error: {rec.get('error')}")
        return ToolResult.ok({"error": None},
                             message="No errors recorded recently.")


class ShowLogsTool(Tool):
    name = "introspection.logs"
    description = "Show the most recent agent events (live log tail)."
    permission = PermissionLevel.LOW
    category = "developer"
    timeout = 10
    verify_after = False

    async def run(self, args, task_id=None) -> ToolResult:
        rt = _runtime(self.ctx)
        limit = int((args or {}).get("limit") or 25)
        limit = max(1, min(limit, 100))
        if not rt or not rt.event_bus:
            return ToolResult.fail("event bus unavailable", "NO_EVENTS")
        events = [{"event": e.event, "at": e.at, "data": e.data}
                  for e in rt.event_bus.history(limit)]
        return ToolResult.ok({"events": events, "count": len(events)},
                             message=f"Last {len(events)} agent events.")


class ListToolsTool(Tool):
    name = "introspection.tools"
    description = "List every registered tool with its risk category."
    permission = PermissionLevel.LOW
    category = "developer"
    timeout = 10
    verify_after = False

    async def run(self, args, task_id=None) -> ToolResult:
        rt = _runtime(self.ctx)
        if not rt:
            return ToolResult.fail("runtime unavailable", "NO_RUNTIME")
        tools = [{"name": d.name, "category": d.category,
                  "permission": d.permission_level,
                  "confirmation": d.requires_confirmation}
                 for d in rt.registry.definitions()]
        return ToolResult.ok({"tools": sorted(tools, key=lambda t: t["name"]),
                              "count": len(tools)},
                             message=f"{len(tools)} tools registered.")


class ListPermissionsTool(Tool):
    name = "introspection.permissions"
    description = "Show the active permission policy and remembered rules."
    permission = PermissionLevel.LOW
    category = "developer"
    timeout = 10
    verify_after = False

    async def run(self, args, task_id=None) -> ToolResult:
        rt = _runtime(self.ctx)
        if not rt:
            return ToolResult.fail("runtime unavailable", "NO_RUNTIME")
        pm = rt.permissions
        policy = {
            "remember_choice": rt.settings.get_bool("permissions.remember_choice", True),
            "confirm_delete": rt.settings.get_bool("confirm_delete", True),
            "confirm_messages": rt.settings.get_bool("confirm_messages", True),
            "confirm_privileged": rt.settings.get_bool("confirm_privileged", True),
        }
        return ToolResult.ok({"policy": policy,
                              "session_rules": pm.describe_session()},
                             message="Current permission policy.")


class DiagnosticsTool(Tool):
    name = "introspection.diagnostics"
    description = "Run the full NOVA self-diagnostic and return a health report."
    permission = PermissionLevel.LOW
    category = "developer"
    timeout = 60
    verify_after = False

    async def run(self, args, task_id=None) -> ToolResult:
        rt = _runtime(self.ctx)
        if not rt:
            return ToolResult.fail("runtime unavailable", "NO_RUNTIME")
        report = rt.diagnostics()
        checks = report.get("checks") or []
        passed = sum(1 for c in checks if c.get("status") == "PASS")
        problems = [c for c in checks if c.get("status") == "ERROR"]
        warned = [c for c in checks if c.get("status") == "WARNING"]
        msg = f"Diagnostics: {passed}/{len(checks)} checks passed."
        if problems:
            msg += " Problems: " + ", ".join(c.get("name", "?") for c in problems[:4])
        if warned:
            msg += " Warnings: " + ", ".join(c.get("name", "?") for c in warned[:4])
        if not problems and not warned:
            msg += " All systems healthy."
        return ToolResult.ok({"report": report, "failed": len(problems)},
                             message=msg)


class UndoLastTool(Tool):
    name = "undo.last"
    description = ("Undo the last task's filesystem operations "
                   "('undo the last thing').")
    permission = PermissionLevel.MEDIUM
    category = "filesystem"
    requires_confirmation = True
    confirm_message_tpl = "Undo NOVA's last filesystem changes?"
    timeout = 30

    async def run(self, args, task_id=None) -> ToolResult:
        journal = getattr(self.ctx, "undo_journal", None)
        if journal is None:
            return ToolResult.fail("undo journal unavailable", "NO_JOURNAL")
        target = (args or {}).get("task_id") or None
        outcome = journal.undo_last(target)
        return ToolResult.ok(outcome.as_dict(), message=outcome.summary)
