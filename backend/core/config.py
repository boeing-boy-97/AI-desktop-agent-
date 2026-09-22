"""Central configuration loader.

Configuration priority (highest first):
    1. Runtime overrides (applied via :meth:`Settings.apply`)
    2. Environment variables (dotenv if python-dotenv is installed)
    3. In-code defaults

Secrets are never hard-coded. The nested :class:`Config` object is a flat,
JSON-serialisable tree persisted to SQLite so settings survive restarts.
"""
from __future__ import annotations

import copy
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:  # pragma: no cover - optional dependency
    from dotenv import load_dotenv  # type: ignore
    _HAS_DOTENV = True
except Exception:  # pragma: no cover
    _HAS_DOTENV = False

# ---------------------------------------------------------------------------
# Directory resolution
# ---------------------------------------------------------------------------
PACKAGE_ROOT = Path(__file__).resolve().parents[1]          # backend/
REPO_ROOT = PACKAGE_ROOT.parent                             # nova-agent/
APPS_DIR = REPO_ROOT / "apps"


def _default_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "NOVA"


def _load_env_file() -> None:
    if not _HAS_DOTENV:
        return
    for candidate in (REPO_ROOT / ".env", Path.cwd() / ".env"):
        if candidate.exists():
            try:
                load_dotenv(candidate, override=False)
            except Exception:
                pass


_load_env_file()

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_CONFIG: dict[str, Any] = {
    # AI
    "ai.provider": "openai",           # openai | ollama | mock
    "ai.openai_base_url": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    "ai.openai_model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
    "ai.ollama_base_url": os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
    "ai.ollama_model": os.environ.get("OLLAMA_MODEL", "llama3.1"),
    "ai.temperature": 0.2,
    "ai.timeout_seconds": 120,
    "ai.max_planner_iterations": 12,
    # Voice
    "voice.stt_provider": "faster-whisper",   # faster-whisper | mock
    "voice.stt_model": "base",
    "voice.stt_language": "en",
    "voice.tts_provider": "pyttsx3",          # pyttsx3 | none
    "voice.rate": 170,
    "voice.volume": 1.0,
    "voice.interruption": "user_voice",       # none | user_voice | any_mic
    # Permissions
    "permissions.default_mode": "ask",        # deny | ask | allow
    "permissions.remember_choice": True,
    "permissions.confirm_messages": True,
    "permissions.confirm_delete": True,
    "permissions.confirm_privileged": True,
    # Automation
    "automation.max_retries": 2,
    "automation.step_timeout_seconds": 60,
    "automation.screenshot_dir": str(_default_data_dir() / "screenshots"),
    "automation.downloads_dir": str(Path.home() / "Downloads"),
    "automation.screenshots_enabled": True,
    # Appearance / behaviour
    "desktop.theme": "dark",
    "desktop.opacity": 0.92,
    "desktop.always_on_top": True,
    "desktop.orb_scale": 1.0,
    "desktop.orb_x": -1,
    "desktop.orb_y": -1,
    "desktop.start_minimized": True,
    "desktop.confirm_on_exit": True,
    "hotkeys.activate": "ctrl+alt+space",
    "hotkeys.emergency_stop": "ctrl+alt+x",
    "browser.engine": "playwright",           # playwright | mock
    "browser.channel": "chrome",
    "browser.headless": False,
    # Privacy
    "privacy.cloud_processing_enabled": True,
    "privacy.log_filenames": True,
    # Updates (§54 — never installs silently)
    "updates.enabled": True,
    "updates.manifest_url": "",
}

BOOL_KEYS = {
    "permissions.remember_choice", "permissions.confirm_messages",
    "permissions.confirm_delete", "permissions.confirm_privileged",
    "automation.screenshots_enabled", "desktop.always_on_top",
    "desktop.start_minimized", "desktop.confirm_on_exit",
    "browser.headless", "privacy.cloud_processing_enabled",
    "privacy.log_filenames",
    "developer.direct_actions", "api.auth_enabled",
    "updates.enabled",
}
INT_KEYS: set[str] = set()
FLOAT_KEYS = {
    "ai.temperature", "ai.timeout_seconds", "ai.max_planner_iterations",
    "voice.rate", "voice.volume", "desktop.opacity", "desktop.orb_scale",
    "desktop.orb_x", "desktop.orb_y", "automation.max_retries",
    "automation.step_timeout_seconds",
}
SECRET_KEYS = {"ai.openai_api_key", "ai.anthropic_api_key"}

ENV_SECRET_MAP = {
    "ai.openai_api_key": "OPENAI_API_KEY",
    "ai.anthropic_api_key": "ANTHROPIC_API_KEY",
    "ai.openai_base_url": "OPENAI_BASE_URL",
    "ai.openai_model": "OPENAI_MODEL",
    "ai.ollama_base_url": "OLLAMA_BASE_URL",
    "ai.ollama_model": "OLLAMA_MODEL",
    "database.url": "DATABASE_URL",
    "core.log_level": "LOG_LEVEL",
}


@dataclass
class Settings:
    """Mutable runtime settings with a JSON serialisable backing store."""

    _data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self._data:
            self._data = copy.deepcopy(DEFAULT_CONFIG)
        self._apply_env()
    @property
    def data(self) -> dict[str, Any]:
        return self._data

    def snapshot(self, *, include_secrets: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, val in sorted(self._data.items()):
            if not include_secrets and key in SECRET_KEYS:
                continue
            if key.endswith("_api_key") and not include_secrets:
                out[key] = _mask(val)
            else:
                out[key] = val
        return out

    def load(self, mapping: Mapping[str, Any], *, include_secrets: bool = True) -> None:
        for key, value in mapping.items():
            if key == "ai.openai_api_key" and not value:
                continue  # never blank out a live secret with empty string
            self._data[key] = _coerce(key, value)

    def update(self, updates: Mapping[str, Any]) -> None:
        for key, value in updates.items():
            if key.endswith("_api_key") and not value:
                continue
            self._data[key] = _coerce(key, value)

    # -- typed getters ---------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def get_str(self, key: str, default: str = "") -> str:
        val = self._data.get(key, default)
        return "" if val is None else str(val)

    def get_int(self, key: str, default: int = 0) -> int:
        try:
            return int(self._data.get(key, default))
        except (TypeError, ValueError):
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        try:
            return float(self._data.get(key, default))
        except (TypeError, ValueError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        val = self._data.get(key, default)
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return bool(val)
        return str(val).strip().lower() in {"1", "true", "yes", "on"}

    # -- directories -----------------------------------------------------
    @property
    def data_dir(self) -> Path:
        d = Path(self.get_str("storage.data_dir", str(_default_data_dir())))
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def database_path(self) -> Path:
        return self.data_dir / "nova.db"

    @property
    def screenshots_dir(self) -> Path:
        d = Path(self.get_str("automation.screenshot_dir"))
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def downloads_dir(self) -> Path:
        d = Path(self.get_str("automation.downloads_dir"))
        d.mkdir(parents=True, exist_ok=True)
        return d

    # -- ai convenience --------------------------------------------------
    def openai_api_key(self) -> str | None:
        key = self._data.get("ai.openai_api_key") or ""
        return key.strip() or None

    def _apply_env(self) -> None:
        for key, env in ENV_SECRET_MAP.items():
            if os.environ.get(env):
                self._data[key] = os.environ[env]


def _mask(value: Any) -> str:
    if not value:
        return ""
    value = str(value)
    if len(value) <= 8:
        return "****"
    return value[:3] + "…" + value[-3:]


def _coerce(key: str, value: Any) -> Any:
    if isinstance(value, bool):
        truthy = str(value).lower() in {"true", "1"}
        if key in INT_KEYS or key in FLOAT_KEYS:
            return float(value)
        if key in BOOL_KEYS:
            return truthy
        return value
    if key in BOOL_KEYS:
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
    if key in FLOAT_KEYS:
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    if key in INT_KEYS:
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    return value


# Module-level singleton. The runtime services hold references to it; tests
# construct isolated instances.
settings = Settings()
