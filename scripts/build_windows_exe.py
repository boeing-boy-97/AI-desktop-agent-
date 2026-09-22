#!/usr/bin/env python3
"""Build standalone Windows executables for NOVA (PyInstaller). Run ON WINDOWS.

    python scripts/build_windows_exe.py backend   -> dist/NovaBackend.exe
    python scripts/build_windows_exe.py desktop   -> dist/NovaDesktop.exe
    python scripts/build_windows_exe.py all
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(spec_name: str, entry: str, name: str, console: bool, extra: list) -> int:
    cmd = [sys.executable, "-m", "PyInstaller",
           "--noconfirm", "--clean", "--onefile",
           "--name", name,
           "--paths", str(ROOT / "backend"),
           # static deps
           "--hidden-import", "sqlalchemy",
           "--hidden-import", "database.models",
           # tool plugins are discovered dynamically (tools/__init__.py)
           "--collect-submodules", "tools",
           # V2 agent/planner/core layers (function-level imports)
           "--collect-submodules", "agent",
           "--collect-submodules", "planner",
           "--collect-submodules", "providers",
           "--collect-submodules", "core",
           "--collect-submodules", "database",
           "--collect-submodules", "diagnostics",
           "--collect-submodules", "api",
           # health-score engine imported dynamically by /api/system/health_score
           "--hidden-import", "scripts_lib",
           "--collect-submodules", "faster_whisper"]
    if console:
        cmd.append("--console")
    else:
        cmd.append("--noconsole")
    for e in extra:
        cmd += ["--add-data", e]
    cmd += [entry]
    print("+", " ".join(cmd))
    return subprocess.call(cmd, cwd=str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", choices=["backend", "desktop", "all"], default="all")
    args = ap.parse_args()

    results = []
    if args.target in ("backend", "all"):
        results.append(build(
            "backend", str(ROOT / "backend" / "main.py"), "NovaBackend",
            console=True,
            extra=[str(ROOT / "backend" / "dashboard" + ";dashboard")]))
    if args.target in ("desktop", "all"):
        results.append(build(
            "desktop", str(ROOT / "apps" / "desktop" / "main.py"), "NovaDesktop",
            console=False, extra=[str(ROOT / "apps" / "desktop" + ";apps/desktop")]))

    if any(results):
        print("BUILD FAILED"); return 1
    print("✓ Build complete — see dist/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
