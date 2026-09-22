"""Vercel serverless entrypoint — NOVA API + dashboard in the cloud.

What this deployment IS
    The full NOVA FastAPI backend + developer dashboard, running the agent
    brain (planner → queue → executor → memory → workflows) inside a
    serverless sandbox. Filesystem tools operate on the sandboxed /tmp area.

What it is NOT
    NOVA is a desktop agent: controlling YOUR computer (mouse, keyboard,
    microphone, apps) requires the desktop build running on your machine.
    Those tools are explicitly DENIED here (§56 — never expose shell/system
    control to a public network). They report a clear "denied by policy"
    result instead of failing silently.

Cloud notes
    * Data dir lives under /tmp (the only writable area; ephemeral between
      cold starts — that is serverless by design, not a bug).
    * Set NOVA_API_TOKEN in the Vercel project settings and
      api.auth_enabled=true to require a bearer token on every API call.
"""
from __future__ import annotations

import os
import sys

# --- serverless-safe paths BEFORE any NOVA import (the settings singleton
# --- reads XDG_DATA_HOME at import time)
os.environ.setdefault("XDG_DATA_HOME", "/tmp")

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.normpath(os.path.join(_HERE, "..", "backend"))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

# This file lives in a root-level ``api/`` directory (Vercel convention) that
# would otherwise shadow the real ``backend/api`` package as a namespace
# package. Drop any cached shadow before importing.
sys.modules.pop("api", None)

from serverless_app import app  # noqa: F401  (re-exported for Vercel)
