"""Startup configuration validation (V2 §66).

Runs once during Runtime construction and produces *actionable* results:
every failing check explains what is wrong and what to do about it.  Nothing
here raises — degraded operation is allowed (V2 §41), but the problems are
surfaced in ``/api/system/status`` and diagnostics so nothing fails silently.
"""
from __future__ import annotations

import os
import platform
import sys
from pathlib import Path
from typing import Any


def run_startup_checks(settings: Any = None) -> list[dict]:
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str, fix: str = "",
            severity: str = "warning") -> None:
        checks.append({"check": name, "ok": ok, "detail": detail,
                       "fix": fix, "severity": severity})

    # 1. Python version
    v = sys.version_info
    add("python_version", v >= (3, 10),
        f"Python {v.major}.{v.minor}.{v.micro}",
        "NOVA requires Python 3.10+; reinstall with a newer interpreter.",
        "error" if v < (3, 10) else "info")

    # 2. Operating system support
    system = platform.system()
    supported = system == "Windows"
    add("operating_system", True,
        f"{system} ({platform.release()})"
        + ("" if supported else " — Windows-only automation tools degrade "
                                "gracefully on this platform"),
        "Run on Windows for full computer-control capability.", "info")

    # 3. Data directories writable
    try:
        data_dir = Path(getattr(settings, "data_dir", None) or
                        Path.home() / ".nova")
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".startup_probe"
        probe.write_text("ok", "utf-8")
        probe.unlink()
        add("data_directory", True, str(data_dir), severity="info")
    except OSError as exc:
        add("data_directory", False, f"cannot write data dir: {exc}",
            "Check disk permissions or set NOVA_DATA_DIR to a writable folder.",
            "error")

    # 4. Core dependencies importable
    for module, purpose in (
            ("sqlalchemy", "database"), ("fastapi", "API server"),
            ("pydantic", "schemas")):
        try:
            __import__(module)
            add(f"dependency_{module}", True, purpose, severity="info")
        except Exception as exc:
            add(f"dependency_{module}", False, str(exc),
                f"pip install {module}", "error")

    # 5. Optional capability providers (informational — never fatal)
    optional = {
        "pyautogui": "mouse/keyboard automation",
        "mss": "fast screen capture",
        "playwright": "browser automation",
        "faster_whisper": "local speech recognition",
        "pyttsx3": "offline text-to-speech",
        "sounddevice": "microphone capture",
    }
    for module, purpose in optional.items():
        try:
            __import__(module)
            add(f"optional_{module}", True, purpose, severity="info")
        except Exception:
            # any import failure (OSError for missing native libs, etc.) just
            # means the capability is unavailable — never fatal (§62)
            add(f"optional_{module}", False, f"{purpose} unavailable",
                f"pip install {module} to enable {purpose}", "info")

    # 6. AI provider configuration
    if os.environ.get("OPENAI_API_KEY"):
        add("ai_provider", True, "cloud AI configured", severity="info")
    else:
        add("ai_provider", False,
            "no cloud AI key — heuristic planner will be used",
            "Set OPENAI_API_KEY for production planning; local automation "
            "still works without it.", "info")

    return checks


def summarise(checks: list[dict]) -> dict:
    problems = [c for c in checks if not c["ok"] and c["severity"] == "error"]
    warnings = [c for c in checks if not c["ok"] and c["severity"] != "error"]
    return {
        "ok": not problems,
        "errors": problems,
        "warnings": warnings,
        "total_checks": len(checks),
    }
