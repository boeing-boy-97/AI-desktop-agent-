"""Cloud/serverless application builder for NOVA (Vercel & friends).

Creates the Runtime, locks down tools that must never run on a public
network (§56), and exports the ASGI ``app``. The Vercel entrypoint
(``api/index.py``) imports this module after fixing ``sys.path``.
"""
from __future__ import annotations

from api.app import build_app
from runtime import Runtime

# Tools that must never execute in a public cloud deployment: remote shell,
# power/lock controls, process management, raw input injection.
_CLOUD_DENY = {
    "shell.run", "shell.run_argv",
    "system.shutdown", "system.restart", "system.lock",
    "system.volume", "system.brightness",
    "process.start", "process.stop",
    "computer.click", "computer.double_click", "computer.right_click",
    "computer.drag", "computer.scroll", "computer.type", "computer.press",
    "computer.hotkey", "computer.move", "computer.clipboard_write",
    "computer.launch_app", "computer.close_app",
}

runtime = Runtime()
_registered = set(runtime.registry.names())
for _tool in sorted(_CLOUD_DENY & _registered):
    runtime.permissions.set_session_rule(_tool, "deny")

app = build_app(runtime)
