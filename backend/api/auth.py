"""Local API security (V2 §56).

The NOVA API is a localhost control surface for the desktop UI.  Threats:
another LAN device reaching an accidentally exposed port, or a local process
pretending to be the UI.

Mitigations:

* production entrypoint binds 127.0.0.1 by default (``backend/main.py``)
* when ``NOVA_API_TOKEN`` (env) is set — or ``api.token`` in settings —
  every mutating/state route requires ``Authorization: Bearer <token>`` or
  ``?token=<token>``.  Read-only health/openapi/docs stay open so browsers
  and diagnostics can still inspect.
* the token is generated, never hard-coded; it is printed once at startup
  and stored in the data dir with user-only permissions.

The middleware is deliberately simple and dependency-free (Starlette
BaseHTTPMiddleware is avoided for latency; a plain ASGI wrapper is used).
"""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any, Callable

SAFE_PREFIXES = ("/docs", "/redoc", "/openapi.json", "/static", "/favicon")
SAFE_EXACT = {"/", "/dashboard", "/dev", "/api/health"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def load_or_create_token(data_dir: str | Path | None = None) -> str | None:
    """Token from env, settings file, or freshly generated (persisted)."""
    env = os.environ.get("NOVA_API_TOKEN", "").strip()
    if env:
        return env
    if not data_dir:
        return None
    path = Path(data_dir) / "api_token"
    try:
        if path.exists():
            tok = path.read_text("utf-8").strip()
            if tok:
                return tok
        tok = secrets.token_urlsafe(24)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(tok, "utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return tok
    except OSError:
        return None


def _token_from(scope: dict, headers: dict) -> str | None:
    auth = headers.get(b"authorization", b"").decode("latin-1")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    qs = scope.get("query_string", b"").decode("latin-1")
    for part in qs.split("&"):
        if part.startswith("token="):
            return part[6:]
    return None


def build_auth_middleware(token: str,
                          on_denied_log: Callable[[str], None] | None = None):
    """Return an ASGI middleware enforcing bearer auth on sensitive routes."""

    async def middleware(scope: dict, receive: Any, send: Any) -> bool:
        """Returns True when the request may proceed."""
        if scope.get("type") != "http":
            return True
        path = scope.get("path", "")
        method = scope.get("method", "GET")
        if (method in SAFE_METHODS and path.startswith(SAFE_PREFIXES)) or path in SAFE_EXACT:
            return True
        headers = dict(scope.get("headers", []))
        supplied = _token_from(scope, headers)
        if supplied is not None and secrets.compare_digest(supplied, token):
            return True
        if on_denied_log:
            on_denied_log(f"denied {method} {path} (missing/invalid token)")
        return False

    return middleware


def wrap_app(app: Any, token: str | None,
             log: Callable[[str], None] | None = None) -> Any:
    """Wrap *app* with auth when a token is configured; otherwise no-op."""
    if not token:
        return app
    check = build_auth_middleware(token, on_denied_log=log)

    original = app

    async def guarded(scope: dict, receive: Any, send: Any) -> None:
        if not await check(scope, receive, send):
            body = json.dumps({"detail": "unauthorized: provide the NOVA API "
                                          "token (Authorization: Bearer <token>)"}).encode()
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"application/json"),
                                    (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return
        await original(scope, receive, send)

    return guarded
