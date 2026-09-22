"""memory_tools.* — direct memory CRUD used by the UI/API (spec §18 viewer)."""
from __future__ import annotations

from tools.base import PermissionLevel, Tool, ToolResult


class MemoryListTool(Tool):
    name = "memory.list"
    description = "List all stored memories."
    input_model = None
    permission = PermissionLevel.LOW
    timeout = 10

    async def run(self, args, task_id=None) -> ToolResult:
        if not self.ctx.session_factory:
            return ToolResult.ok({"memories": []})
        from database.service import list_memory
        with self.ctx.session_factory() as s:
            rows = list_memory(s)
        return ToolResult.ok({"memories": [
            {"id": r.id, "key": r.key, "value": r.value, "category": r.category}
            for r in rows]})


class MemoryDeleteTool(Tool):
    name = "memory.delete"
    description = "Delete a memory by key."
    input_model = None
    permission = PermissionLevel.MEDIUM
    timeout = 10

    async def run(self, args, task_id=None) -> ToolResult:
        key = (args or {}).get("key")
        if not key:
            return ToolResult.fail("key required", "INVALID_ARGS")
        if not self.ctx.session_factory:
            return ToolResult.ok({"deleted": False})
        from database.service import delete_memory
        with self.ctx.session_factory() as s:
            ok = delete_memory(s, key)
        return ToolResult.ok({"deleted": ok, "key": key})


class MemoryClearTool(Tool):
    name = "memory.clear"
    description = "Delete ALL stored memories. HIGH RISK — requires confirmation."
    input_model = None
    permission = PermissionLevel.HIGH
    requires_confirmation = True
    confirm_message_tpl = "Clear all stored memories?"
    timeout = 10

    async def run(self, args, task_id=None) -> ToolResult:
        if not self.ctx.session_factory:
            return ToolResult.ok({"cleared": 0, "note": "runtime-only memory"})
        from database.service import clear_memory
        with self.ctx.session_factory() as s:
            n = clear_memory(s)
        return ToolResult.ok({"cleared": n})
