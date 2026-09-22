"""NOVA permission system.

Two intersecting mechanisms:

1. **PermissionManager** — decides allow / ask / deny for a tool based on its
   declared risk level, per-tool persisted rules and session rules.
2. **ConfirmationStore** — when the decision is "ask", an internal confirmation
   is created; the agent pauses the task until the UI (or API) approves or
   declines it. This is how "WAITING_CONFIRMATION" behaves.

Plus a process-wide **EmergencyStop** latch checked before every risky step.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from core.utils import iso_now, new_id
from tools.base import PermissionLevel, ToolDefinition

DECISION_ALLOW = "allow"
DECISION_ASK = "ask"
DECISION_DENY = "deny"


class EmergencyStop:
    """Process-wide emergency latch. Setting it cancels all active/pending work."""

    def __init__(self) -> None:
        self._triggered = False
        self._lock = threading.Lock()
        self.triggered_at: str | None = None

    def pull(self) -> None:
        with self._lock:
            self._triggered = True
            if self.triggered_at is None:
                self.triggered_at = iso_now()

    def release(self) -> None:
        with self._lock:
            self._triggered = False
            self.triggered_at = None

    @property
    def active(self) -> bool:
        with self._lock:
            return self._triggered

    def assert_clear(self) -> None:
        from core.exceptions import EmergencyStop as EmergencyStopError
        if self.active:
            raise EmergencyStopError(
                "Emergency stop is active — all agent activity halted.",
                details={"triggered_at": self.triggered_at})


@dataclass
class Confirmation:
    """A pending 'ask the user' gate for one tool invocation."""
    id: str
    task_id: str
    tool: str
    question: str
    created_at: str = field(default_factory=iso_now)
    risk: str = PermissionLevel.LOW
    context: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "id": self.id, "task_id": self.task_id, "tool": self.tool,
            "question": self.question, "created_at": self.created_at,
            "risk": self.risk, "context": self.context,
        }


class ConfirmationStore:
    """Registry of pending confirmations, keyed by task id."""

    def __init__(self) -> None:
        self._items: dict[str, Confirmation] = {}
        self._lock = threading.Lock()

    def create(self, task_id: str, tool: str, question: str,
               risk: str = PermissionLevel.LOW,
               context: dict | None = None) -> Confirmation:
        conf = Confirmation(id=new_id("conf"), task_id=task_id, tool=tool,
                            question=question, risk=risk, context=context or {})
        with self._lock:
            self._items[task_id] = conf
        return conf

    def get_for_task(self, task_id: str) -> Confirmation | None:
        with self._lock:
            return self._items.get(task_id)

    def get(self, conf_id: str) -> Confirmation | None:
        with self._lock:
            for c in self._items.values():
                if c.id == conf_id:
                    return c
        return None

    def resolve(self, conf_id: str, approved: bool) -> bool:
        """Mark a confirmation as approved/declined (consumed by caller)."""
        with self._lock:
            for c in list(self._items.values()):
                if c.id == conf_id:
                    c.context["resolved"] = approved
                    return True
        return False

    def consume(self, task_id: str) -> Confirmation | None:
        with self._lock:
            conf = self._items.pop(task_id, None)
            return conf

    def all(self) -> list[Confirmation]:
        with self._lock:
            return list(self._items.values())


class PermissionManager:
    """Decides whether a tool call may proceed, and how."""

    def __init__(self, settings: Any, session_factory=None,
                 store: ConfirmationStore | None = None) -> None:
        self.settings = settings
        self._session_factory = session_factory
        self.store = store or ConfirmationStore()
        self._session_rules: dict[str, str] = {}

    # ------------------------------------------------------------------
    def check(self, definition: ToolDefinition, args: dict,
              task_id: str) -> str:
        """Return a decision: allow | ask | deny."""
        scope = definition.name

        # 1. explicit session rule wins (only when the user allows remembering)
        if (self.settings.get_bool("permissions.remember_choice", True)
                and scope in self._session_rules):
            return self._session_rules[scope]

        # 2. persisted DB rule next
        persisted = self._persisted_decision(scope)
        if persisted:
            return persisted

        # 3. confirmation-flagged / high-risk tools always ask — unless the
        #    user explicitly disabled that confirmation category in settings
        if definition.requires_confirmation or definition.permission_level == PermissionLevel.HIGH:
            if (scope.startswith("filesystem.delete")
                    and not self.settings.get_bool("permissions.confirm_delete", True)):
                return DECISION_ALLOW
            if (scope.startswith("whatsapp.send")
                    and not self.settings.get_bool("permissions.confirm_messages", True)):
                return DECISION_ALLOW
            if (definition.permission_level == PermissionLevel.HIGH
                    and not self.settings.get_bool("permissions.confirm_privileged", True)):
                return DECISION_ALLOW
            return DECISION_ASK

        # 4. default by risk tier vs configured default mode
        default = self.settings.get_str("permissions.default_mode", "ask")
        if definition.permission_level == PermissionLevel.LOW:
            return DECISION_ALLOW
        if definition.permission_level == PermissionLevel.MEDIUM:
            return DECISION_ALLOW if default == "allow" else DECISION_ASK
        return DECISION_ASK

    def request_confirmation(self, definition: ToolDefinition, args: dict,
                             task_id: str, context: dict | None = None,
                             detail: str | None = None) -> Confirmation:
        from core.utils import json_dumps
        tpl = definition.confirm_message_tpl or "Allow {tool}?"
        try:
            question = tpl.format(tool=definition.name, **self._arg_vars(args))
        except (KeyError, IndexError):
            question = tpl.format(tool=definition.name)
        if definition.permission_level == PermissionLevel.HIGH:
            question = question + " (high-risk action)"
        if detail:
            question = f"{question}\n{detail}"
        conf = self.store.create(task_id, definition.name, question,
                                 risk=definition.permission_level,
                                 context={"args": json_dumps(args, pretty=True),
                                          **(context or {})})
        return conf

    def remember_approval(self, definition: ToolDefinition) -> bool:
        """Apply session-memory of an approval when the user's policy allows it.

        This is the "Remember choices per tool" feature (default on). It is
        required for the executor's retry loop: once the user approves a step,
        the re-executed step must pass without prompting again. When the user
        turns the setting off, nothing is remembered and every use re-asks.
        """
        if not self.settings.get_bool("permissions.remember_choice", True):
            return False
        self.set_session_rule(definition.name, DECISION_ALLOW)
        return True

    def set_session_rule(self, tool: str, decision: str) -> None:
        if decision not in (DECISION_ALLOW, DECISION_ASK, DECISION_DENY):
            raise ValueError(f"invalid decision {decision!r}")
        self._session_rules[tool] = decision

    def clear_session_rule(self, tool: str) -> None:
        self._session_rules.pop(tool, None)

    def clear_session_rules(self) -> None:
        self._session_rules.clear()

    def set_persisted(self, tool: str, decision: str) -> None:
        if decision not in (DECISION_ALLOW, DECISION_ASK, DECISION_DENY):
            raise ValueError(f"invalid decision {decision!r}")
        if self._session_factory is None:
            self._session_rules[tool] = decision
            return
        from database.service import set_permission
        with self._session_factory() as s:
            set_permission(s, tool, decision, persists=True)

    def reset_persisted(self, tool: str) -> None:
        if self._session_factory is None:
            self._session_rules.pop(tool, None)
            return
        from database.service import get_permission
        with self._session_factory() as s:
            row = get_permission(s, tool)
            if row:
                s.delete(row)

    def effective_policy(self, tool: str) -> str:
        if tool in self._session_rules:
            return self._session_rules[tool]
        persisted = self._persisted_decision(tool)
        if persisted:
            return persisted
        return self.settings.get_str("permissions.default_mode", "ask")

    def all_persisted(self) -> dict[str, str]:
        out: dict[str, str] = {}
        if self._session_factory is not None:
            try:
                from database.models import Permission
                from sqlalchemy import select
                with self._session_factory() as s:
                    for row in s.execute(select(Permission)).scalars():
                        out[row.scope] = row.decision
            except Exception:
                pass
        out.update(self._session_rules)
        return out

    def describe_session(self) -> dict:
        """Human/API view of live session permission state (V2 §59)."""
        return {
            "session_rules": dict(self._session_rules),
            "persisted_rules": self.all_persisted(),
            "pending_confirmations": [c.as_dict() for c in self.store.all()],
        }

    # ------------------------------------------------------------------
    def _persisted_decision(self, scope: str) -> str | None:
        if not self.settings.get_bool("permissions.remember_choice", True):
            return None
        if scope in self._session_rules:
            return self._session_rules[scope]
        if self._session_factory is None:
            return None
        try:
            from database.service import get_permission
            with self._session_factory() as s:
                row = get_permission(s, scope)
            if row:
                return row.decision
        except Exception:
            return None
        return None

    @staticmethod
    def _arg_vars(args: dict) -> dict:
        safe: dict[str, str] = {}
        for k, v in args.items():
            if isinstance(v, (str, int, float, bool)):
                safe[k] = str(v)
        return safe
