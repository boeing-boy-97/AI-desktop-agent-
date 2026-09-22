"""State machine tests (V2 §5)."""
import pytest

from agent.state_machine import (InvalidTransition, StateMachine,
                                 TERMINAL_STATES, TRANSITIONS, VALID_STATES)


def test_starts_idle():
    assert StateMachine().state == "IDLE"


def test_happy_path_transitions():
    sm = StateMachine()
    for target in ("UNDERSTANDING", "PLANNING", "EXECUTING",
                   "WAITING_CONFIRMATION", "EXECUTING", "VERIFYING",
                   "SPEAKING", "COMPLETED", "IDLE"):
        sm.transition(target)
    assert sm.state == "IDLE"


def test_invalid_transition_raises():
    sm = StateMachine()
    sm.transition("UNDERSTANDING")
    with pytest.raises(InvalidTransition) as ei:
        sm.transition("SPEAKING")  # cannot speak straight from understanding
    assert "UNDERSTANDING" in str(ei.value)
    assert "SPEAKING" in str(ei.value)
    # state unchanged after a rejected transition
    assert sm.state == "UNDERSTANDING"


def test_unknown_state_rejected():
    sm = StateMachine()
    with pytest.raises(InvalidTransition):
        sm.transition("NOT_A_STATE")


def test_reentry_allowed():
    sm = StateMachine()
    sm.transition("EXECUTING")
    assert sm.transition("EXECUTING") == "EXECUTING"  # step loop


def test_terminal_states_only_return_to_idle():
    for terminal in TERMINAL_STATES:
        sm = StateMachine()
        sm.transition("EXECUTING")
        sm.transition(terminal)
        with pytest.raises(InvalidTransition):
            sm.transition("EXECUTING")
        sm.transition("IDLE")
        assert sm.state == "IDLE"


def test_force_bypasses_guard_for_emergency():
    sm = StateMachine()
    sm.transition("EXECUTING")
    sm.force("CANCELLED", reason="emergency_stop")
    assert sm.state == "CANCELLED"
    assert sm.history()[-1]["forced"] is True


def test_history_records_from_to():
    events = []
    sm = StateMachine(on_transition=lambda f, t, d: events.append((f, t)))
    sm.transition("PLANNING")
    sm.transition("EXECUTING")
    h = sm.history()
    assert h[0]["from"] == "IDLE" and h[0]["to"] == "PLANNING"
    assert events == [("IDLE", "PLANNING"), ("PLANNING", "EXECUTING")]


def test_transition_table_covers_every_state():
    assert set(TRANSITIONS) == VALID_STATES
    for src, targets in TRANSITIONS.items():
        assert targets <= VALID_STATES, src


def test_can_transition_predicate():
    sm = StateMachine()
    assert sm.can_transition("PLANNING")
    assert not sm.can_transition("VERIFYING")
    assert not sm.can_transition("bogus")
