#!/usr/bin/env python3
"""NOVA development setup (cross-platform).

Creates a virtualenv, installs dependencies and initialises the SQLite
database. Run::

    python scripts/dev_setup.py [--with-desktop] [--with-playwright]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"


def run(cmd: list[str], **kw) -> int:
    print("+", " ".join(cmd))
    return subprocess.call(cmd, cwd=str(ROOT), **kw)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-desktop", action="store_true")
    ap.add_argument("--with-playwright", action="store_true")
    ap.add_argument("--no-venv", action="store_true")
    args = ap.parse_args()

    py = sys.executable
    if not args.no_venv and not (VENV / "bin").exists():
        if (VENV / "Scripts").exists():  # Windows layout
            py = str(VENV / "Scripts" / "python.exe")
        else:
            print(f"Creating virtualenv at {VENV} …")
            venv.EnvBuilder(with_pip=True).create(VENV)
            py = str(VENV / "bin" / "python")

    pip = [py, "-m", "pip", "install", "-q", "--disable-pip-version-check"]
    reqs = ["-r", "requirements.txt"]
    if args.with_desktop:
        reqs = ["-r", "requirements-desktop.txt"]
    run(pip + reqs)

    if args.with_playwright:
        run(pip + ["install", "-q", "playwright"])
        run([py, "-m", "playwright", "install", "chromium"])

    # initialise the database
    print("Initialising database …")
    code = run([py, "-c",
                ("import sys; sys.path.insert(0, 'backend'); "
                 "from runtime import Runtime; "
                 "rt = Runtime(); print('DB ready:', rt.database.migration_status()['up_to_date'])")])
    if code == 0:
        print("\nNOVA development environment ready.")
        print("  Start backend : python -m backend.main --port 8765   (or: uvicorn main:app)")
        print("  Start desktop : python -m apps.desktop.main")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
