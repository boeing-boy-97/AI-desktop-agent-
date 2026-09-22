"""vscode.* — VS Code automation (spec §9).

Method preference (spec §54): CLI → filesystem → UI automation. We therefore
implement everything through the ``code`` CLI plus direct file writes, and only
fall back to launching via shell when the CLI is missing.
"""
from __future__ import annotations

import platform
import shutil
from pathlib import Path

from core.safety import resolve_path
from core.shell import shell
from tools.base import PermissionLevel, Tool, ToolResult


class _VSCodeTool(Tool):
    _abstract = True
    category = "vscode"

    # -- helpers --------------------------------------------------------
    @staticmethod
    def _cli_path() -> str | None:
        if platform.system() == "Windows":
            candidates = [
                shutil.which("code"),
                Path("C:/Program Files/Microsoft VS Code/bin/code.cmd"),
                Path(str(Path.home() / "AppData/Local/Programs/Microsoft VS Code/bin/code.cmd")),
            ]
        else:
            candidates = [shutil.which("code"),
                          Path("/usr/local/bin/code"), Path("/usr/bin/code")]
        for c in candidates:
            try:
                if c and str(c).strip() and Path(str(c)).exists():
                    return str(c)
            except OSError:
                continue
        if shutil.which("code"):
            return shutil.which("code")
        return None

    def is_installed(self) -> bool:
        return self._cli_path() is not None

    async def _run_cli(self, *argv: str) -> ToolResult:
        cli = self._cli_path()
        if cli is None:
            return ToolResult.fail(
                "VS Code command line ('code') not found. Install VS Code and add it "
                "to PATH, or open it manually once (Shell Command: Install 'code').",
                "NOT_FOUND")
        cmd = " ".join([str(cli)] + [str(a) for a in argv])
        try:
            res = await shell.run(cmd, timeout=30, force=True)
        except Exception as exc:
            return ToolResult.fail(str(exc), "SHELL_ERROR")
        if res.returncode != 0:
            return ToolResult.fail(res.stderr or res.stdout or f"code exited {res.returncode}",
                                   "CLI_ERROR")
        return ToolResult.ok({"command": cmd, "exit": res.returncode})


class VSCodeDetectTool(_VSCodeTool):
    name = "vscode.detect"
    description = "Check whether VS Code is installed and where."
    input_model = None
    permission = PermissionLevel.LOW
    timeout = 10

    async def run(self, args, task_id=None) -> ToolResult:
        cli = self._cli_path()
        return ToolResult.ok({"installed": cli is not None, "cli": cli or ""})


class VSCodeOpenTool(_VSCodeTool):
    name = "vscode.open"
    description = "Open VS Code (optionally a specific folder/workspace path)."
    input_model = None
    permission = PermissionLevel.LOW
    timeout = 30

    async def run(self, args, task_id=None) -> ToolResult:
        path = (args or {}).get("path")
        argv = []
        if path:
            p = resolve_path(path)
            if not p.exists():
                return ToolResult.fail(f"Path does not exist: {p}", "NOT_FOUND")
            argv.append(str(p))
        if self._cli_path() is not None:
            return await self._run_cli(*argv)
        # graceful fallback (spec §54): no 'code' CLI → open VS Code as an app
        from tools._platform import Computer
        launched = Computer("auto").launch("code")
        if launched.get("launched"):
            return ToolResult.ok({"opened": True, "backend": "app-launch",
                                  "path": str(argv[0]) if argv else None,
                                  "note": "opened via app launcher ('code' CLI not in PATH)"})
        return ToolResult.fail(
            "VS Code command line ('code') not found and app launch failed. "
            "Install VS Code and add it to PATH, or open it manually once "
            "(Shell Command: Install 'code').",
            "NOT_FOUND")


class VSCodeWriteFileTool(_VSCodeTool):
    name = "vscode.write_file"
    description = "Create/overwrite a file inside a project (direct filesystem write)."
    input_model = None
    permission = PermissionLevel.MEDIUM
    timeout = 15

    async def run(self, args, task_id=None) -> ToolResult:
        path = (args or {}).get("path")
        content = (args or {}).get("content", "")
        if not path:
            return ToolResult.fail("path required", "INVALID_ARGS")
        p = resolve_path(path)
        existed = p.exists()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        except OSError as exc:
            return ToolResult.fail(str(exc), "IO_ERROR")
        return ToolResult.ok({"path": str(p), "bytes": len(content.encode()),
                              "overwrote": existed})


class VSCodeRunCommandTool(_VSCodeTool):
    name = "vscode.run_command"
    description = "Run a CLI command inside a project directory (npm/python/git/...)."
    input_model = None
    permission = PermissionLevel.MEDIUM
    timeout = 300

    async def run(self, args, task_id=None) -> ToolResult:
        command = (args or {}).get("command")
        cwd = (args or {}).get("cwd")
        if not command:
            return ToolResult.fail("command required", "INVALID_ARGS")
        try:
            res = await shell.run(command, cwd=cwd, timeout=280, force=False)
        except Exception as exc:
            return ToolResult.fail(str(exc), getattr(exc, "code", "SHELL_ERROR"))
        return ToolResult.ok(res.as_dict(), message=f"exit {res.returncode}")


class VSCodeReadFileTool(_VSCodeTool):
    name = "vscode.read_file"
    description = "Read a project file's content."
    input_model = None
    permission = PermissionLevel.LOW
    timeout = 15

    async def run(self, args, task_id=None) -> ToolResult:
        path = (args or {}).get("path")
        if not path:
            return ToolResult.fail("path required", "INVALID_ARGS")
        p = resolve_path(path)
        if not p.exists():
            return ToolResult.fail(f"Not found: {p}", "NOT_FOUND")
        try:
            return ToolResult.ok({"path": str(p), "content": p.read_text(encoding="utf-8",
                                                                         errors="replace")[:60000]})
        except OSError as exc:
            return ToolResult.fail(str(exc), "IO_ERROR")


class VSCodeListTool(_VSCodeTool):
    name = "vscode.list_tree"
    description = "List a project tree (files only, capped)."
    input_model = None
    permission = PermissionLevel.LOW
    timeout = 20

    async def run(self, args, task_id=None) -> ToolResult:
        path = (args or {}).get("path", ".")
        p = resolve_path(path)
        if not p.exists():
            return ToolResult.fail(f"Not found: {p}", "NOT_FOUND")
        items = []
        for child in p.rglob("*"):
            try:
                if child.is_file() and ".git" not in child.parts:
                    items.append({"path": str(child), "rel": str(child.relative_to(p))})
            except OSError:
                continue
            if len(items) >= 500:
                break
        return ToolResult.ok({"root": str(p), "count": len(items),
                              "files": [i["rel"] for i in items]})


class VSCodeRunTestsTool(_VSCodeTool):
    name = "vscode.run_tests"
    description = "Run a project's test command (default: pytest or npm test)."
    input_model = None
    permission = PermissionLevel.MEDIUM
    timeout = 300

    async def run(self, args, task_id=None) -> ToolResult:
        cwd = (args or {}).get("path") or "."
        command = (args or {}).get("command")
        cwd_p = resolve_path(cwd)
        if command:
            try:
                res = await shell.run(command, cwd=str(cwd_p), timeout=280)
            except Exception as exc:
                return ToolResult.fail(str(exc), getattr(exc, "code", "SHELL_ERROR"))
            return ToolResult.ok(res.as_dict(), message=f"exit {res.returncode}")
        if (cwd_p / "package.json").exists():
            try:
                res = await shell.run("npm test", cwd=str(cwd_p), timeout=280)
            except Exception as exc:
                return ToolResult.fail(str(exc), getattr(exc, "code", "SHELL_ERROR"))
            return ToolResult.ok(res.as_dict(), message=f"exit {res.returncode}")
        try:
            res = await shell.run(
                self.ctx.settings.get_str("tests.command", "python -m pytest -q"),
                cwd=str(cwd_p), timeout=280)
        except Exception as exc:
            return ToolResult.fail(str(exc), getattr(exc, "code", "SHELL_ERROR"))
        return ToolResult.ok(res.as_dict(), message=f"exit {res.returncode}")


class VSCodeInspectErrorsTool(_VSCodeTool):
    name = "vscode.inspect_errors"
    description = "Search recent command output / logs for error signatures."
    input_model = None
    permission = PermissionLevel.LOW
    timeout = 20

    async def run(self, args, task_id=None) -> ToolResult:
        log = (args or {}).get("output", "")
        if not log and self.ctx.observer:
            snap = self.ctx.observer.screenshot()
            log = snap.text or ""
        patterns = _ERROR_PATTERNS
        found = []
        for pat in patterns:
            import re
            for m in re.finditer(pat, log):
                found.append({"pattern": pat, "match": m.group(0)[:200]})
                if len(found) >= 20:
                    break
        return ToolResult.ok({"errors_detected": len(found), "errors": found})


_ERROR_PATTERNS = [
    r"error[:\s][A-Z ]+", r"Error[:\s].*", r"Traceback \(most recent call last\)",
    r"Exception[:\s].*", r"npm ERR!.*", r"FAILED.*", r"failed[:\s].*",
    r"ModuleNotFoundError:.*", r"SyntaxError:.*", r"TypeError:.*",
    r"ReferenceError:.*", r"EADDRINUSE.*", r"Cannot find module.*",
]


class VSCodeStartDevServerTool(_VSCodeTool):
    name = "vscode.start_dev_server"
    description = "Start a dev server for a project (npm run dev / python)."
    input_model = None
    permission = PermissionLevel.MEDIUM
    timeout = 30

    async def run(self, args, task_id=None) -> ToolResult:
        cwd = (args or {}).get("path") or "."
        cwd_p = resolve_path(cwd)
        port = (args or {}).get("port", "")
        if (cwd_p / "package.json").exists():
            import asyncio
            import subprocess as sp
            argv = ["npm", "run", "dev"]
            if port:
                argv += ["--", "--port", str(port)]
            try:
                proc = await asyncio.create_subprocess_exec(
                    *argv, cwd=str(cwd_p), stdout=sp.DEVNULL, stderr=sp.DEVNULL)
            except OSError as exc:
                return ToolResult.fail(f"Could not start dev server: {exc}", "IO_ERROR")
            return ToolResult.ok({"started": True, "pid": proc.pid,
                                  "url": f"http://localhost:{port or 5173}"})
        return ToolResult.fail("No package.json found for a JS dev server", "NOT_FOUND")
