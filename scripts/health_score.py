#!/usr/bin/env python3
"""NOVA engineering health score (V2 §64).

Runs the offline evidence pipeline — pytest, ruff, import check, security
grep — and writes ``health_report.json`` into the NOVA data dir where the
``/api/system/health_score`` endpoint reads it.  Failures are NEVER hidden:
a failing suite lowers the score and is printed.

    python scripts/health_score.py [--json]
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def run(cmd: list[str], cwd: Path, timeout: int = 600) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           timeout=timeout)
        return p.returncode, (p.stdout + p.stderr)[-4000:]
    except FileNotFoundError as exc:
        return 127, f"missing binary: {exc}"
    except subprocess.TimeoutExpired:
        return 124, "timeout"


def pytest_result() -> dict:
    code, out = run([sys.executable, "-m", "pytest", "-q",
                     "-p", "no:cacheprovider"], BACKEND)
    m = re.search(r"(\d+) passed", out)
    passed = int(m.group(1)) if m else 0
    return {"ok": code == 0, "passed": passed, "score": 0.0 if code else 1.0,
            "tail": out[-500:], "status": "run"}


def ruff_result() -> dict:
    code, out = run(["ruff", "check", "backend", "apps", "scripts"], ROOT)
    findings = len(re.findall(r"^\S+\.py:\d+", out, re.M))
    return {"ok": code == 0, "findings": findings,
            "score": 0.0 if code else 1.0, "tail": out[-300:],
            "status": "run"}


def imports_result() -> dict:
    mods = ["runtime", "api.app", "agent.task_manager", "tools",
            "planner.heuristic", "workflows.engine", "diagnostics.checks"]
    failed = []
    for m in mods:
        code, _ = run([sys.executable, "-c", f"import {m}"], BACKEND, timeout=60)
        if code != 0:
            failed.append(m)
    return {"ok": not failed, "failed": failed,
            "score": 1.0 - len(failed) / len(mods), "status": "run"}


def security_result() -> dict:
    """Cheap static red flags; real security review lives in the docs."""
    problems = []
    for path in BACKEND.rglob("*.py"):
        if any(part in ("tests", "__pycache__") for part in path.parts):
            continue
        try:
            text = path.read_text("utf-8", errors="ignore")
        except OSError:
            continue
        if re.search(r"(api[_-]?key|secret|password)\s*=\s*['\"][A-Za-z0-9]{16,}",
                     text, re.I):
            problems.append(f"possible hardcoded secret in {path.name}")
        if "os.system(" in text:
            problems.append(f"os.system() call in {path.name}")
    return {"ok": not problems, "problems": problems,
            "score": 1.0 if not problems else 0.0, "status": "run"}


def main() -> int:
    report = {
        "generated_at": time.time(),
        "pytest": pytest_result(),
        "ruff": ruff_result(),
        "imports": imports_result(),
        "security": security_result(),
    }
    ok = all(report[k]["ok"] for k in ("pytest", "ruff", "imports", "security"))
    report["ok"] = ok

    # persist for the API endpoint
    try:
        sys.path.insert(0, str(BACKEND))
        from core.config import Settings
        out = Settings().data_dir / "health_report.json"
        out.write_text(json.dumps(report, indent=1), "utf-8")
        print(f"report written: {out}")
    except Exception as exc:
        print(f"could not persist report: {exc}")

    brief = {k: {"ok": v.get("ok")} for k, v in report.items()
             if isinstance(v, dict)}
    print(json.dumps(brief, indent=1))
    if "--json" in sys.argv:
        print(json.dumps(report))
    print("HEALTH:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
