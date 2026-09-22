"""TaskStore — persists tasks/steps against the database (or in-memory)."""
from __future__ import annotations

from core.utils import iso_now, new_id


class TaskStore:
    """CRUD bridge for tasks. Uses the DB when a session_factory is present,
    otherwise keeps an in-memory mirror (tests, demo)."""

    def __init__(self, session_factory=None) -> None:
        self.session_factory = session_factory
        self._memory: dict[str, dict] = {}

    # ------------------------------------------------------------------
    def create(self, command: str, mode: str = "smart") -> str:
        tid = new_id("task")
        now = iso_now()
        rec = {"id": tid, "command": command, "mode": mode, "status": "queued",
               "created_at": now, "goal": "", "plan": [], "steps": [],
               "result": "", "error": "", "files_changed": [], "apps_used": [],
               "errors_repaired": 0, "started_at": None, "finished_at": None}
        if self.session_factory is not None:
            from database.service import create_task_with_id
            with self.session_factory() as s:
                create_task_with_id(s, tid, command, mode)
        self._memory[tid] = rec
        return tid

    def update(self, task_id: str, **fields) -> None:
        rec = self._memory.get(task_id)
        if rec:
            rec.update(fields)
        if self.session_factory is not None:
            from database.service import update_task
            db_fields = {k: v for k, v in fields.items()
                         if k in ("status", "goal", "plan", "result", "error",
                                  "files_changed", "apps_used", "errors_repaired",
                                  "changes", "started_at", "finished_at")}
            if db_fields:
                with self.session_factory() as s:
                    update_task(s, task_id, **db_fields)

    def add_step(self, task_id: str, seq: int, tool: str, arguments: dict) -> None:
        rec = self._memory.get(task_id)
        if rec:
            rec.setdefault("steps", []).append(
                {"seq": seq, "tool": tool, "arguments": arguments, "status": "pending",
                 "output": None, "error": "", "attempts": 0, "duration_ms": None})
        if self.session_factory is not None:
            from database.service import add_step
            with self.session_factory() as s:
                add_step(s, task_id, seq, tool, arguments)

    def update_step(self, task_id: str, seq: int, **fields) -> None:
        rec = self._memory.get(task_id)
        if rec:
            for st in rec.get("steps", []):
                if st["seq"] == seq:
                    st.update(fields)
        if self.session_factory is not None:
            from database.models import TaskStep
            from sqlalchemy import select
            with self.session_factory() as s:
                rows = s.execute(select(TaskStep).where(
                    TaskStep.task_id == task_id, TaskStep.seq == seq)).scalars().all()
                for row in rows:
                    for k, v in fields.items():
                        if hasattr(row, k):
                            setattr(row, k, v)

    def get(self, task_id: str) -> dict | None:
        if self.session_factory is not None:
            from database.models import Task
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload
            with self.session_factory() as s:
                t = s.execute(select(Task).options(selectinload(Task.steps))
                              .where(Task.id == task_id)).scalar_one_or_none()
                rec = self._orm_to_dict(t) if t else None
            if rec:
                return rec
        return self._memory.get(task_id)

    def list(self, limit: int = 100) -> list[dict]:
        if self.session_factory is not None:
            from database.models import Task
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload
            with self.session_factory() as s:
                rows = s.execute(
                    select(Task).options(selectinload(Task.steps))
                    .order_by(Task.created_at.desc()).limit(limit)).scalars().all()
                recs = [self._orm_to_dict(t) for t in rows]
            return recs
        items = sorted(self._memory.values(), key=lambda r: r.get("created_at", ""),
                       reverse=True)
        return items[:limit]

    def delete_all(self) -> int:
        n = len(self._memory)
        self._memory.clear()
        if self.session_factory is not None:
            from database.service import delete_all_tasks
            with self.session_factory() as s:
                n = delete_all_tasks(s)
        return n

    def status(self, task_id: str) -> str | None:
        rec = self.get(task_id)
        return rec.get("status") if rec else None

    def recent(self, limit: int = 10) -> list[dict]:
        """Newest-first convenience alias used by introspection tools."""
        return self.list(limit)

    @staticmethod
    def _orm_to_dict(t) -> dict:
        return {
            "id": t.id, "command": t.command, "mode": t.mode, "status": t.status,
            "goal": t.goal, "plan": t.plan, "result": t.result, "error": t.error,
            "files_changed": t.files_changed or [], "apps_used": t.apps_used or [],
            "errors_repaired": t.errors_repaired,
            "changes": t.changes or {},
            "created_at": t.created_at.isoformat() if t.created_at else "",
            "started_at": t.started_at.isoformat() if t.started_at else None,
            "finished_at": t.finished_at.isoformat() if t.finished_at else None,
            "steps": [{
                "seq": s.seq, "tool": s.tool, "arguments": s.arguments or {},
                "status": s.status, "output": s.output, "error": s.error,
                "attempts": s.attempts, "duration_ms": s.duration_ms,
            } for s in t.steps],
        }
