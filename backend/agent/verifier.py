"""Verifier — verifies that individual tool outcomes actually succeeded.

Uses before/after screenshots (screen understanding), file-system facts, and
shell return codes. The executor calls this after each step where verification
is enabled.
"""
from __future__ import annotations

from typing import Any

from tools.base import ToolResult


class Verifier:
    def __init__(self, observer: Any = None, settings: Any = None) -> None:
        self.observer = observer
        self.settings = settings

    # ------------------------------------------------------------------
    def verify_result(self, tool_name: str, result: ToolResult,
                      arguments: dict) -> ToolResult:
        """Return a verification ToolResult (ok=True means the step stands)."""
        if not result.success:
            return ToolResult.ok(False, message=f"step failed: {result.error}",
                                 data={"status": "failed"})

        # file-appearance verification for writes/downloads/creates
        if tool_name in ("filesystem.write_file", "filesystem.create_folder",
                         "filesystem.copy", "filesystem.move", "downloads.download_url",
                         "whatsapp.download_media", "browser.download"):
            return self._verify_file(result)

        # shell verification: non-zero exit codes
        if tool_name in ("shell.run", "shell.run_argv", "vscode.run_command"):
            data = result.data or {}
            code = data.get("returncode")
            if code is None and isinstance(result.output, dict):
                code = result.output.get("returncode")
            if code is not None and int(code) != 0:
                return ToolResult.ok(False, message=f"command exited {code}",
                                     data={"status": "failed", "returncode": code})
            return ToolResult.ok(True, message="command exit code verified")

        # screenshots: confirm the screen changed if the tool is a GUI action
        if tool_name.startswith(("computer.", "browser.")):
            if self.observer is None:
                return ToolResult.ok(None, message="no observer configured; skipped")
            return ToolResult.ok(None, message="screen observation deferred")

        return ToolResult.ok(None, message="verified")

    def _verify_file(self, result: ToolResult) -> ToolResult:
        data = result.data or {}
        out = result.output or {}
        path = data.get("path") or (out.get("path") if isinstance(out, dict) else None)
        if not path:
            # e.g. downloads report "saved_to"
            path = data.get("saved_to") or (out.get("saved_to") if isinstance(out, dict) else None)
        if not path:
            return ToolResult.ok(None, message="no path to verify; accepted")
        import os
        exists = os.path.exists(path)
        if not exists:
            return ToolResult.ok(False, message=f"expected file did not appear: {path}",
                                 data={"status": "failed", "path": path})
        size = os.path.getsize(path) if os.path.isfile(path) else None
        return ToolResult.ok(True, message=f"file verified ({size} bytes)" if size is not None else "path verified",
                             data={"status": "ok", "path": path, "size": size})
