"""alias.* — command aliases, macros and remembered-folders tools (spec §18, §19).

Aliases ("Start College Mode") expand into a list of tool steps that the
workflow engine then executes. They are ordinary planner-visible tools whose
execution enqueues follow-up steps.
"""
from __future__ import annotations

from pydantic import BaseModel, Field
from tools.base import PermissionLevel, Tool, ToolResult


class AliasCreateIn(BaseModel):
    name: str = Field(..., min_length=1)
    steps: list[dict] = Field(..., min_length=1)


class AliasRunIn(BaseModel):
    name: str = Field(..., min_length=1)


class RememberIn(BaseModel):
    key: str = Field(..., min_length=1)
    value: str = Field(..., min_length=1)


class RecallIn(BaseModel):
    key: str = Field(..., min_length=1)


class _MemoryTool(Tool):
    _abstract = True
    category = "memory"

    @property
    def _session_factory(self):
        return getattr(self.ctx, "session_factory", None)


class AliasCreateTool(_MemoryTool):
    name = "alias.create"
    description = ("Create a named command alias that expands into several steps "
                   "(round-tripped through the workflow engine on next run).")
    input_model = AliasCreateIn
    permission = PermissionLevel.MEDIUM
    timeout = 15

    async def run(self, args, task_id=None) -> ToolResult:
        from database.service import save_workflow
        if not self.ctx.session_factory:
            return ToolResult.fail("database unavailable for aliases", "DB_ERROR")
        with self.ctx.session_factory() as s:
            save_workflow(s, args.name, args.steps, triggers=[args.name.lower()])
        return ToolResult.ok({"alias": args.name, "steps": len(args.steps)})


class AliasListTool(_MemoryTool):
    name = "alias.list"
    description = "List defined command aliases/macros."
    input_model = None
    permission = PermissionLevel.LOW
    timeout = 10

    async def run(self, args, task_id=None) -> ToolResult:
        if not self.ctx.session_factory:
            return ToolResult.ok({"aliases": []})
        from database.service import list_workflows
        with self.ctx.session_factory() as s:
            rows = list_workflows(s)
        return ToolResult.ok({"aliases": [
            {"name": r.name, "steps": r.steps, "triggers": r.triggers or []}
            for r in rows if r.triggers]})


class AliasDeleteTool(_MemoryTool):
    name = "alias.delete"
    description = "Delete a command alias."
    input_model = AliasRunIn
    permission = PermissionLevel.MEDIUM
    timeout = 10

    async def run(self, args, task_id=None) -> ToolResult:
        if not self.ctx.session_factory:
            return ToolResult.fail("database unavailable", "DB_ERROR")
        from database.service import delete_workflow
        with self.ctx.session_factory() as s:
            ok = delete_workflow(s, args.name)
        return ToolResult.ok({"deleted": ok, "alias": args.name})


class RememberTool(_MemoryTool):
    name = "memory.remember"
    description = ("Store a fact/preference in local memory (e.g. folders, app "
                   "aliases). Later commands can recall it.")
    input_model = RememberIn
    permission = PermissionLevel.LOW
    timeout = 10

    async def run(self, args, task_id=None) -> ToolResult:
        if not self.ctx.session_factory:
            return ToolResult.ok({"remembered": args.key, "note": "runtime-only memory"})
        from database.service import set_memory as db_set
        with self.ctx.session_factory() as s:
            db_set(s, args.key, args.value)
        return ToolResult.ok({"remembered": args.key})


class RecallTool(_MemoryTool):
    name = "memory.recall"
    description = "Recall a stored memory value by key."
    input_model = RecallIn
    permission = PermissionLevel.LOW
    timeout = 10

    async def run(self, args, task_id=None) -> ToolResult:
        if not self.ctx.session_factory:
            return ToolResult.ok({"key": args.key, "value": None, "found": False})
        from database.service import get_memory as db_get
        with self.ctx.session_factory() as s:
            row = db_get(s, args.key)
        if not row:
            return ToolResult.ok({"key": args.key, "value": None, "found": False})
        return ToolResult.ok({"key": args.key, "value": row.value, "found": True,
                              "category": row.category})
