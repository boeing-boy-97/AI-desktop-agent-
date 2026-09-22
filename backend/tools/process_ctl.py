"""process.* + shell.* — controlled subprocess & process management tools.

All shell execution flows through :class:`ControlledShell` (dangerous command
detection + timeouts + redaction). Processes are listed via psutil or a POSIX
fallback. Terminating a process is high-risk and requires confirmation.
"""
from __future__ import annotations

from core.exceptions import ExecutionBlocked, NovaError
from core.shell import ControlledShell, ShellResult
from core.shell import shell as default_shell
from pydantic import BaseModel, Field
from tools.base import PermissionLevel, Tool, ToolResult


# ---------------------------------------------------------------------------
# inputs
# ---------------------------------------------------------------------------
class RunIn(BaseModel):
    command: str = Field(..., min_length=1)
    cwd: str | None = None
    timeout: float = 60.0


class RunForbiddenTestIn(BaseModel):
    command: str


class StartIn(BaseModel):
    command: str = Field(..., min_length=1)
    cwd: str | None = None


class StopIn(BaseModel):
    pid: int = Field(..., ge=1)
    force: bool = False


class ListIn(BaseModel):
    name_filter: str | None = None


class DetectIn(BaseModel):
    name: str = Field(..., min_length=1)


class _ProcessTool(Tool):
    _abstract = True
    category = "process"

    @property
    def _shell(self) -> ControlledShell:
        cached = getattr(self.ctx, "_shell", None)
        if cached is None:
            cached = default_shell
            self.ctx._shell = cached
        return cached


class ShellRunTool(_ProcessTool):
    name = "shell.run"
    description = ("Run a shell command under the controlled execution layer "
                   "(dangerous patterns are blocked; timeout enforced). "
                   "Returns stdout/stderr/returncode.")
    input_model = RunIn
    permission = PermissionLevel.MEDIUM
    timeout = 70

    async def run(self, args, task_id=None) -> ToolResult:
        try:
            result: ShellResult = await self._shell.run(
                args.command, cwd=args.cwd, timeout=args.timeout, capture=True)
        except ExecutionBlocked as exc:
            return ToolResult.fail(exc.message, "EXECUTION_BLOCKED", data=exc.details)
        except NovaError as exc:
            return ToolResult.fail(exc.message, exc.code)
        out = result.as_dict()
        return ToolResult.ok(out, message=f"exit {result.returncode}")


class ShellArgvTool(_ProcessTool):
    name = "shell.run_argv"
    description = "Run a command from an argument list without a shell (safer)."
    input_model = None  # argument list handled directly
    permission = PermissionLevel.MEDIUM
    timeout = 70

    async def run(self, args, task_id=None) -> ToolResult:
        argv = args.get("argv")
        if not isinstance(argv, list) or not argv:
            return ToolResult.fail("argv list required", "INVALID_ARGS")
        try:
            result = await self._shell.run_cmd(argv, cwd=args.get("cwd"),
                                               timeout=float(args.get("timeout", 60)))
        except ExecutionBlocked as exc:
            return ToolResult.fail(exc.message, "EXECUTION_BLOCKED", data=exc.details)
        except NovaError as exc:
            return ToolResult.fail(exc.message, exc.code)
        return ToolResult.ok(result.as_dict(), message=f"exit {result.returncode}")


class ProcessListTool(_ProcessTool):
    name = "process.list"
    description = "List running processes (optionally filtered by name)."
    input_model = ListIn
    permission = PermissionLevel.LOW
    timeout = 15

    async def run(self, args, task_id=None) -> ToolResult:
        procs = self._list_procs()
        if args.name_filter:
            low = args.name_filter.lower()
            procs = [p for p in procs if low in p["name"].lower()]
        return ToolResult.ok({"count": len(procs), "processes": procs[:200]})


    def _list_procs(self) -> list[dict]:
        try:
            import psutil
            out = []
            for p in psutil.process_iter(["pid", "name", "exe"]):
                try:
                    info = p.info
                except psutil.Error:  # process vanished mid-iteration
                    continue
                out.append({"pid": info["pid"], "name": info.get("name") or "",
                            "exe": info.get("exe") or ""})
            out.sort(key=lambda d: d["name"].lower())
            return out
        except Exception:
            import subprocess
            try:
                r = subprocess.run(["ps", "-eo", "pid,comm"], capture_output=True,
                                   text=True, timeout=5, check=False)
                out = []
                for line in r.stdout.splitlines()[1:]:
                    parts = line.split(None, 1)
                    if len(parts) == 2:
                        out.append({"pid": int(parts[0]), "name": parts[1], "exe": ""})
                return out
            except Exception:
                return []


class ProcessDetectTool(_ProcessTool):
    name = "process.detect"
    description = "Check whether a process matching a name is running."
    input_model = DetectIn
    permission = PermissionLevel.LOW
    timeout = 10

    async def run(self, args, task_id=None) -> ToolResult:
        low = args.name.lower()
        found = [p for p in self._list() if low in p["name"].lower()]
        return ToolResult.ok({"running": bool(found), "matches": found[:20]})

    def _list(self) -> list[dict]:
        return ProcessListTool._list_procs(self)


class ProcessStartTool(_ProcessTool):
    name = "process.start"
    description = "Start a process (detached) and return its PID."
    input_model = StartIn
    permission = PermissionLevel.MEDIUM
    timeout = 15

    async def run(self, args, task_id=None) -> ToolResult:
        # gate through the dangerous-command detector before launching
        from core.exceptions import ExecutionBlocked
        try:
            verdict = self._shell.inspect(args.command)
            if not verdict.allowed:
                raise ExecutionBlocked(self._shell.detector.block_message(verdict),
                                       details=verdict.as_dict())
        except ExecutionBlocked as exc:
            return ToolResult.fail(exc.message, "EXECUTION_BLOCKED", data=exc.details)

        import asyncio
        import subprocess
        try:
            proc = await asyncio.create_subprocess_shell(
                args.command, cwd=args.cwd or None,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            return ToolResult.fail(f"Could not start process: {exc}", "IO_ERROR")
        return ToolResult.ok({"pid": proc.pid, "command": args.command, "started": True})


class ProcessStopTool(_ProcessTool):
    name = "process.stop"
    description = "Terminate a process by PID (force kill optional). Requires confirmation."
    input_model = StopIn
    permission = PermissionLevel.HIGH
    requires_confirmation = True
    confirm_message_tpl = "Terminate process with PID {pid}?"
    timeout = 20

    async def run(self, args, task_id=None) -> ToolResult:
        try:
            import os
            import signal
            os.kill(args.pid, signal.SIGKILL if args.force else signal.SIGTERM)
            return ToolResult.ok({"pid": args.pid, "terminated": True, "force": args.force})
        except ProcessLookupError:
            return ToolResult.fail(f"No process with PID {args.pid}", "NOT_FOUND")
        except PermissionError as exc:
            return ToolResult.fail(f"Permission denied terminating {args.pid}: {exc}", "PERMISSION")
        except Exception as exc:
            return ToolResult.fail(str(exc), "SYSTEM_ERROR")
