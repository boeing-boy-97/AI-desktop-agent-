"""Unit tests for core foundations: config, safety, permissions, DB."""
import os

import pytest
from core.config import Settings
from core.exceptions import EmergencyStop as EmergencyStopError
from core.safety import (
    DangerousCommandDetector,
    build_delete_request,
    is_protected_path,
    resolve_path,
)
from database.session import Database
from permissions import (
    DECISION_ALLOW,
    DECISION_ASK,
    DECISION_DENY,
    ConfirmationStore,
    EmergencyStop,
    PermissionManager,
)
from tools.base import PermissionLevel, ToolDefinition


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
def test_settings_defaults():
    s = Settings({})
    assert s.get_str("ai.provider") in ("openai", "ollama", "mock")
    assert s.get_int("voice.rate") > 0


def test_settings_env_secret_not_in_snapshot():
    os.environ["OPENAI_API_KEY"] = "sk-test-123456789"
    s = Settings({})
    snap = s.snapshot(include_secrets=False)
    assert "sk-test-123456789" not in str(snap.values())
    assert s.openai_api_key() == "sk-test-123456789"
    del os.environ["OPENAI_API_KEY"]


def test_settings_bool_coercion():
    s = Settings({})
    s.update({"permissions.confirm_delete": "false"})
    assert s.get_bool("permissions.confirm_delete") is False


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------
def test_dangerous_detector_blocks():
    det = DangerousCommandDetector()
    for cmd in ["rm -rf /", "del /f /s C:\\*.*", "shutdown /s", "format c:",
                "diskpart", "rm -rf ~"]:
        v = det.inspection(cmd)
        assert not v.allowed, cmd


def test_dangerous_detector_allows_safe():
    det = DangerousCommandDetector()
    for cmd in ["npm install", "python -m pytest tests/", "node server.js",
                "git status", "echo hello"]:
        v = det.inspection(cmd)
        assert v.allowed, cmd


def test_protected_paths():
    assert is_protected_path(resolve_path("/etc/passwd"))
    assert is_protected_path(resolve_path("/usr/bin/python"))
    assert not is_protected_path(resolve_path("/home/user/projects/x"))
    assert not is_protected_path(resolve_path("/tmp/scratch/file.txt"))
    if os.name == "nt":
        assert is_protected_path(resolve_path("C:/Windows/System32/x.dll"))


def test_build_delete_request():
    req = build_delete_request(["a.txt", "b.txt"], use_recycle_bin=True)
    assert req["count"] == 2
    assert req["use_recycle_bin"] is True


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------
def test_permission_level_rank():
    assert PermissionLevel.meets("low", "high")
    assert PermissionLevel.meets("medium", "high")
    assert not PermissionLevel.meets("high", "low")


def test_permission_manager_low_allow():
    pm = PermissionManager(Settings({}))
    d = ToolDefinition("computer.click", "click", PermissionLevel.LOW, "computer")
    assert pm.check(d, {}, "t1") == DECISION_ALLOW


def test_permission_manager_high_ask():
    pm = PermissionManager(Settings({}))
    d = ToolDefinition("filesystem.delete", "delete", PermissionLevel.HIGH,
                       "filesystem", requires_confirmation=True)
    assert pm.check(d, {}, "t1") == DECISION_ASK


def test_permission_manager_deny_from_rule():
    pm = PermissionManager(Settings({}))
    pm.set_session_rule("system.shutdown", DECISION_DENY)
    d = ToolDefinition("system.shutdown", "shutdown", PermissionLevel.HIGH, "windows")
    assert pm.check(d, {}, "t1") == DECISION_DENY


def test_emergency_stop_latch():
    stop = EmergencyStop()
    assert not stop.active
    stop.pull()
    assert stop.active
    with pytest.raises(EmergencyStopError):
        stop.assert_clear()
    stop.release()
    stop.assert_clear()


def test_confirmation_store():
    store = ConfirmationStore()
    store.create("t1", "filesystem.delete", "Delete?")
    assert store.get_for_task("t1").tool == "filesystem.delete"
    store.resolve(store.get_for_task("t1").id, True)
    c = store.consume("t1")
    assert c is not None
    assert store.get_for_task("t1") is None


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
def test_database_roundtrip():
    db = Database(url="sqlite://")
    db.create_all()
    status = db.migration_status()
    assert status["up_to_date"]
    with db.session() as s:
        from database.service import get_memory, set_memory
        set_memory(s, "college_projects", "D:/College/Projects")
    with db.session() as s:
        from database.service import get_memory
        row = get_memory(s, "college_projects")
        assert row.value == "D:/College/Projects"


# ---------------------------------------------------------------------------
# Permission policy: remember-choice + destructive category toggles
# ---------------------------------------------------------------------------
def test_high_risk_approval_remembered_when_choice_memory_on():
    """With 'remember choices' on (default), an approval lets the retry loop
    proceed; the confirmation itself still happened first."""
    pm = PermissionManager(Settings({}))
    d = ToolDefinition("filesystem.delete", "delete", PermissionLevel.HIGH,
                       "filesystem", requires_confirmation=True)
    assert pm.check(d, {}, "t1") == DECISION_ASK  # asks first
    assert pm.remember_approval(d) is True        # then remembered per tool
    assert pm.check(d, {}, "t2") == DECISION_ALLOW


def test_medium_risk_remembered_when_enabled():
    pm = PermissionManager(Settings({}))
    d = ToolDefinition("filesystem.create_folder", "create", PermissionLevel.MEDIUM,
                       "filesystem")
    assert pm.remember_approval(d) is True
    assert pm.check(d, {}, "t2") == DECISION_ALLOW


def test_remember_choice_disabled_forgets():
    s = Settings({})
    s.load({"permissions.remember_choice": False})
    pm = PermissionManager(s)
    d = ToolDefinition("filesystem.create_folder", "create", PermissionLevel.MEDIUM,
                       "filesystem")
    assert pm.remember_approval(d) is False
    pm.set_session_rule("filesystem.create_folder", DECISION_ALLOW)
    # check() must ignore session rules when remembering is disabled
    assert pm.check(d, {}, "t2") == DECISION_ASK


def test_confirm_delete_toggle_disables_prompt():
    s = Settings({})
    s.load({"permissions.confirm_delete": False})
    pm = PermissionManager(s)
    d = ToolDefinition("filesystem.delete", "delete", PermissionLevel.HIGH,
                       "filesystem", requires_confirmation=True)
    assert pm.check(d, {}, "t1") == DECISION_ALLOW


def test_confirm_delete_defaults_to_ask():
    pm = PermissionManager(Settings({}))
    d = ToolDefinition("filesystem.delete", "delete", PermissionLevel.HIGH,
                       "filesystem", requires_confirmation=True)
    assert pm.check(d, {}, "t1") == DECISION_ASK
