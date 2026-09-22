from __future__ import annotations

from core.config import Settings
from core.config import settings as global_settings
from core.utils import new_id, truncate
from database.models import (
    Log,
    Memory,
    Permission,
    Setting,
    Task,
    TaskStep,
    UserPreferences,
    Workflow,
)
from database.session import Database
from sqlalchemy import func, select
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


def set_memory(session: Session, key: str, value: str, category: str = "general") -> Memory:
    row = session.execute(select(Memory).where(Memory.key == key)).scalar_one_or_none()
    if row:
        row.value = value
        row.category = category
    else:
        row = Memory(key=key, value=value, category=category)
        session.add(row)
    session.flush()
    return row


def get_memory(session: Session, key: str) -> Memory | None:
    return session.execute(select(Memory).where(Memory.key == key)).scalar_one_or_none()


def list_memory(session: Session) -> list[Memory]:
    return list(session.execute(select(Memory).order_by(Memory.updated_at.desc())).scalars())


def delete_memory(session: Session, key: str) -> bool:
    row = session.execute(select(Memory).where(Memory.key == key)).scalar_one_or_none()
    if not row:
        return False
    session.delete(row)
    session.flush()
    return True


def clear_memory(session: Session) -> int:
    n = session.execute(select(func.count()).select_from(Memory)).scalar_one()
    session.execute(Memory.__table__.delete())
    session.flush()
    return n


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------


def get_permission(session: Session, scope: str) -> Permission | None:
    return session.execute(select(Permission).where(Permission.scope == scope)).scalar_one_or_none()


def set_permission(session: Session, scope: str, decision: str, persists: bool = True) -> Permission:
    row = get_permission(session, scope)
    if row:
        row.decision = decision
        row.persists = persists
    else:
        row = Permission(scope=scope, decision=decision, persists=persists)
        session.add(row)
    session.flush()
    return row


def list_permissions(session: Session) -> list[Permission]:
    return list(session.execute(select(Permission).order_by(Permission.scope)).scalars())


# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------


def save_workflow(session: Session, name: str, steps: list, triggers: list | None = None) -> Workflow:
    row = session.execute(select(Workflow).where(Workflow.name == name)).scalar_one_or_none()
    if row:
        row.steps = steps
        row.triggers = triggers or row.triggers
    else:
        row = Workflow(name=name, steps=steps, triggers=triggers or [])
        session.add(row)
    session.flush()
    return row


def get_workflow(session: Session, name: str) -> Workflow | None:
    return session.execute(select(Workflow).where(Workflow.name == name)).scalar_one_or_none()


def list_workflows(session: Session) -> list[Workflow]:
    return list(session.execute(select(Workflow).order_by(Workflow.name)).scalars())


def delete_workflow(session: Session, name: str) -> bool:
    row = get_workflow(session, name)
    if not row:
        return False
    session.delete(row)
    session.flush()
    return True


# ---------------------------------------------------------------------------
# Tasks + steps
# ---------------------------------------------------------------------------


def create_task(session: Session, command: str, mode: str = "smart") -> Task:
    task = Task(id=new_id("task"), command=command, mode=mode, status="queued")
    session.add(task)
    session.flush()
    return task


def create_task_with_id(session: Session, task_id: str, command: str,
                        mode: str = "smart") -> Task:
    task = Task(id=task_id, command=command, mode=mode, status="queued")
    session.add(task)
    session.flush()
    return task


def add_step(session: Session, task_id: str, seq: int, tool: str,
             arguments: dict | None = None) -> TaskStep:
    step = TaskStep(task_id=task_id, seq=seq, tool=tool,
                    arguments=arguments or {}, status="pending")
    session.add(step)
    session.flush()
    return step


def update_task(session: Session, task_id: str, **fields) -> Task | None:
    task = session.get(Task, task_id)
    if not task:
        return None
    for k, v in fields.items():
        if k in ("started_at", "finished_at") and isinstance(v, str) and v:
            v = _parse_ts(v)
        setattr(task, k, v)
    session.flush()
    return task


def _parse_ts(value: str):
    from datetime import datetime, timezone
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.now(timezone.utc)


def get_task(session: Session, task_id: str) -> Task | None:
    return session.get(Task, task_id)


def list_tasks(session: Session, limit: int = 100) -> list[Task]:
    return list(session.execute(
        select(Task).order_by(Task.created_at.desc()).limit(limit)).scalars())


def delete_all_tasks(session: Session) -> int:
    n = session.execute(select(func.count()).select_from(Task)).scalar_one()
    session.execute(TaskStep.__table__.delete())
    session.execute(Task.__table__.delete())
    session.flush()
    return n


def reap_interrupted_tasks(session: Session) -> int:
    """Mark tasks left in-flight by a previous backend process as failed.

    A restart kills every running coroutine, so any task still in a
    non-terminal state can never finish. Without this, they would show as
    'executing' forever in the history/dashboard.
    """
    from datetime import datetime, timezone
    terminal = ("completed", "failed", "cancelled")
    rows = session.execute(select(Task).where(Task.status.not_in(terminal))).scalars()
    n = 0
    for t in rows:
        t.status = "failed"
        t.error = (t.error + "; " if t.error else "") + "interrupted by backend restart"
        t.finished_at = datetime.now(timezone.utc)
        n += 1
    session.flush()
    return n


# ---------------------------------------------------------------------------
# Settings persistence
# ---------------------------------------------------------------------------


def load_settings_from_db(session: Session) -> dict:
    rows = session.execute(select(Setting)).scalars()
    return {r.key: r.value for r in rows}


def save_settings_to_db(session: Session, data: dict) -> None:
    for key, value in data.items():
        row = session.get(Setting, key)
        if row:
            row.value = str(value)
        else:
            session.add(Setting(key=key, value=str(value)))
    session.flush()


class SettingsService:
    """Two-way bridge between runtime :class:`Settings` and the DB.

    The database holds the serialisable settings (excluding secrets, which live
    only in environment variables / process memory). On startup the DB value
    wins over the default; on change the value is persisted.
    """

    def __init__(self, database: Database, settings: Settings | None = None) -> None:
        self.database = database
        self.settings = settings or global_settings

    def load(self) -> None:
        with self.database.session() as s:
            stored = load_settings_from_db(s)
        self.settings.load(stored, include_secrets=False)

    def persist(self) -> None:
        data = self.settings.snapshot(include_secrets=False)
        with self.database.session() as s:
            save_settings_to_db(s, data)

    def update(self, updates: dict) -> dict:
        self.settings.update(updates)
        self.persist()
        return self.settings.snapshot(include_secrets=False)


# ---------------------------------------------------------------------------
# User preferences + logs
# ---------------------------------------------------------------------------


def set_preference(session: Session, key: str, value: str) -> None:
    row = session.get(UserPreferences, key)
    if row:
        row.value = value
    else:
        session.add(UserPreferences(key=key, value=value))
    session.flush()


def get_preference(session: Session, key: str, default: str = "") -> str:
    row = session.get(UserPreferences, key)
    return row.value if row and row.value is not None else default


def add_log(session: Session, event: str, message: str = "",
            level: str = "INFO", context: dict | None = None) -> Log:
    row = Log(event=event, message=truncate(message, 2000), level=level, context=context)
    session.add(row)
    session.flush()
    return row
