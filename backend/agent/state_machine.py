"""Formal agent state machine (V2 §5).

Every transition is explicit and validated against ``TRANSITIONS``.  Invalid
transitions raise :class:`InvalidTransition` instead of silently corrupting
state, and every accepted transition is recorded (bounded history) and can be
broadcast through the event bus.
"""
from __future__ import annotations

import time
from typing import Any, Callable

VALID_STATES = {
    "IDLE", "LISTENING", "TRANSCRIBING", "UNDERSTANDING", "PLANNING",
    "WAITING_CONFIRMATION", "EXECUTING", "OBSERVING", "VERIFYING",
    "RECOVERING", "PAUSED", "SPEAKING",
    "COMPLETED", "FAILED", "CANCELLED",
}

TERMINAL_STATES = {"COMPLETED", "FAILED", "CANCELLED"}

# from-state -> allowed next states.  Terminal states can only return to IDLE
# (ready for the next task).
TRANSITIONS: dict[str, set[str]] = {
    "IDLE": {"LISTENING", "TRANSCRIBING", "UNDERSTANDING", "PLANNING",
             "EXECUTING", "SPEAKING"},
    "LISTENING": {"TRANSCRIBING", "UNDERSTANDING", "IDLE", "CANCELLED"},
    "TRANSCRIBING": {"UNDERSTANDING", "IDLE", "CANCELLED"},
    "UNDERSTANDING": {"PLANNING", "IDLE", "FAILED", "CANCELLED"},
    "PLANNING": {"EXECUTING", "WAITING_CONFIRMATION", "FAILED", "CANCELLED",
                 "IDLE"},
    "WAITING_CONFIRMATION": {"EXECUTING", "CANCELLED", "FAILED"},
    "EXECUTING": {"OBSERVING", "VERIFYING", "WAITING_CONFIRMATION",
                  "RECOVERING", "PAUSED", "SPEAKING", "COMPLETED", "FAILED",
                  "CANCELLED"},
    "OBSERVING": {"VERIFYING", "EXECUTING", "RECOVERING", "FAILED",
                  "CANCELLED"},
    "VERIFYING": {"EXECUTING", "RECOVERING", "SPEAKING", "COMPLETED",
                  "FAILED", "CANCELLED"},
    "RECOVERING": {"EXECUTING", "OBSERVING", "PLANNING", "FAILED",
                   "CANCELLED"},
    "PAUSED": {"EXECUTING", "CANCELLED", "FAILED"},
    "SPEAKING": {"COMPLETED", "IDLE", "FAILED"},
    "COMPLETED": {"IDLE"},
    "FAILED": {"IDLE"},
    "CANCELLED": {"IDLE"},
}


class InvalidTransition(RuntimeError):
    """Raised when a state change violates the transition table."""

    def __init__(self, current: str, requested: str) -> None:
        self.current = current
        self.requested = requested
        super().__init__(
            f"Invalid agent state transition: {current} -> {requested}. "
            f"Allowed from {current}: {sorted(TRANSITIONS.get(current, set())) or 'none'}")


class StateMachine:
    """Explicit, guarded state machine for the agent runtime."""

    def __init__(self,
                 on_transition: Callable[[str, str, dict], None] | None = None,
                 history_size: int = 200) -> None:
        self._state = "IDLE"
        self._history: list[dict[str, Any]] = []
        self._history_size = history_size
        self._on_transition = on_transition

    # ------------------------------------------------------------------
    @property
    def state(self) -> str:
        return self._state

    def history(self, limit: int = 50) -> list[dict]:
        return list(self._history[-limit:])

    def can_transition(self, target: str) -> bool:
        if target not in VALID_STATES:
            return False
        if target == self._state:
            return True  # staying in a state is always legal
        return target in TRANSITIONS.get(self._state, set())

    def transition(self, target: str, **data: Any) -> str:
        """Move to *target*; raises :class:`InvalidTransition` when illegal.

        Re-entering the current state is allowed (steps loop through
        EXECUTING) and refreshes the timestamp without a duplicate event.
        """
        if target not in VALID_STATES:
            raise InvalidTransition(self._state, target)
        previous = self._state
        if target == previous:
            return previous
        if target not in TRANSITIONS.get(previous, set()):
            raise InvalidTransition(previous, target)
        self._state = target
        entry = {"from": previous, "to": target, "at": time.time(),
                 "data": {k: v for k, v in data.items()
                          if isinstance(v, (str, int, float, bool, type(None)))}}
        self._history.append(entry)
        if len(self._history) > self._history_size:
            del self._history[:len(self._history) - self._history_size]
        if self._on_transition:
            self._on_transition(previous, target, data)
        return target

    def force(self, target: str, reason: str = "") -> None:
        """Unconditional reset (emergency stop / crash recovery only)."""
        if target not in VALID_STATES:
            raise InvalidTransition(self._state, target)
        previous = self._state
        self._state = target
        self._history.append({"from": previous, "to": target,
                              "at": time.time(), "forced": True,
                              "reason": reason})
        if len(self._history) > self._history_size:
            del self._history[:len(self._history) - self._history_size]
        if self._on_transition:
            self._on_transition(previous, target, {"forced": True,
                                                   "reason": reason})

    def reset(self) -> None:
        """Return to IDLE after a terminal state (or force from anywhere)."""
        if self._state in TERMINAL_STATES or self._state != "IDLE":
            self.force("IDLE", reason="reset")
