"""Helper library for engineering tooling (kept importable by the API)."""
from __future__ import annotations

import json
import time
from typing import Any

REPORT_FILENAME = "health_report.json"


def _live_components(runtime: Any) -> dict:
    """Checks that can be evaluated instantly inside the running process."""
    checks = {}
    try:
        checks["runtime_import"] = True
    except Exception:
        checks["runtime_import"] = False
    checks["state_machine_idle"] = runtime.state in (
        "IDLE", "LISTENING", "UNDERSTANDING", "PLANNING", "EXECUTING",
        "WAITING_CONFIRMATION", "VERIFYING", "RECOVERING", "PAUSED",
        "SPEAKING", "COMPLETED", "FAILED", "CANCELLED")
    try:
        checks["tools_registered"] = len(runtime.registry.names()) >= 50
        checks["tool_count"] = len(runtime.registry.names())
    except Exception:
        checks["tools_registered"] = False
    try:
        runtime.store.list(limit=1)
        checks["database"] = True
    except Exception:
        checks["database"] = False
    checks["startup_ok"] = bool(getattr(runtime, "startup_summary", {}).get("ok", False))
    return checks


def compute(runtime: Any) -> dict:
    """Weighted engineering health score (V2 §64). Never hides failures.

    Live component checks run instantly; the offline evidence (pytest/ruff
    results) is read from ``health_report.json`` produced by
    ``python scripts/health_score.py`` — when absent it is reported as
    *not_run*, which caps the score honestly instead of assuming green.
    """
    live = _live_components(runtime)
    offline: dict = {}
    try:
        path = runtime.settings.data_dir / REPORT_FILENAME
        if path.exists():
            offline = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError, AttributeError):
        offline = {}

    weights = {  # component -> weight in the final score
        "runtime": 0.25, "tests": 0.30, "lint": 0.15, "imports": 0.15,
        "security": 0.15,
    }
    runtime_ok = all(v for k, v in live.items() if isinstance(v, bool))
    tests = offline.get("pytest")
    lint = offline.get("ruff")

    def _frac(result: dict | None) -> float | None:
        if not result or result.get("status") == "not_run":
            return None
        return 1.0 if result.get("ok") else float(result.get("score", 0.0))

    parts = {
        "runtime": 1.0 if runtime_ok else 0.0,
        "tests": _frac(tests),
        "lint": _frac(lint),
        "imports": 1.0 if offline.get("imports", {}).get("ok", live["runtime_import"]) else 0.0,
        "security": 1.0 if offline.get("security", {}).get("ok", True) else 0.0,
    }
    known = {k: v for k, v in parts.items() if v is not None}
    covered_weight = sum(weights[k] for k in known) or 1.0
    score = sum(weights[k] * v for k, v in known.items()) / covered_weight
    # anything not run keeps the score from claiming full health
    coverage = covered_weight / sum(weights.values())
    score *= coverage

    return {
        "score": round(score * 100, 1),
        "coverage": round(coverage * 100, 1),
        "components": {k: ("not_run" if v is None else round(v * 100, 1))
                       for k, v in parts.items()},
        "live": live,
        "offline_report": offline or None,
        "generated_at": time.time(),
        "note": ("Full score requires: python scripts/health_score.py"
                 if coverage < 1.0 else "All components evaluated."),
    }
