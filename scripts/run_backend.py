#!/usr/bin/env python3
"""Convenience launcher for the NOVA backend (handles sys.path)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from main import main

if __name__ == "__main__":
    main()
