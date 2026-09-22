#!/usr/bin/env python3
"""Fast project health check — syntax, imports, tests, diagnostics.

Usage: python scripts/check.py            (syntax + imports + diagnostics)
       python scripts/check.py --tests    (also run pytest)
"""
from __future__ import annotations

import argparse
import compileall
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tests", action="store_true")
    args = ap.parse_args()

    print("== Python syntax check (whole tree) ==")
    ok = compileall.compile_dir(ROOT / "backend", quiet=1, force=True) and \
         compileall.compile_dir(ROOT / "apps" / "desktop", quiet=1, force=True)
    if not ok:
        print("SYNTAX ERRORS FOUND"); return 1
    print("  syntax OK\n")

    print("== Import + runtime smoke test ==")
    code = subprocess.call([
        sys.executable, "-c",
        ("import sys; sys.path.insert(0, 'backend'); "
         "from runtime import Runtime; rt = Runtime(for_testing=True); "
         "d = rt.diagnostics()['summary']; "
         "print('  tools:', rt.status()['tool_count'], "
         "'| healthy:', d['healthy'], d)")],
        cwd=str(ROOT))
    if code != 0:
        return code

    if args.tests:
        print("\n== pytest ==")
        r = subprocess.call([sys.executable, "-m", "pytest", "-q"],
                            cwd=str(ROOT / "backend"))
        if r != 0:
            print("TESTS FAILED"); return r
        print("  all tests passed")
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
