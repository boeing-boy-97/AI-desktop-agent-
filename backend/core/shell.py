"""Controlled shell execution.

This is the ONLY code path through which the agent runs subprocesses
(spec §29: "System commands should pass through a controlled execution layer").
It applies the :class:`DangerousCommandDetector`, enforces timeouts, captures
stdout/stderr, and reports structured results.

The agent never executes raw model output directly — commands and arguments
always come through here, wrapped in one of the tools (shell.run etc.).
"""
from __future__ import annotations

import asyncio
import os
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path

from core.exceptions import ExecutionBlocked, NovaError
from core.safety import DangerousCommandDetector

_IS_WINDOWS = platform.system() == "Windows"


class ControlledShell:
    """Structured, safe subprocess runner."""

    def __init__(self, detector: DangerousCommandDetector | None = None) -> None:
        self.detector = detector or DangerousCommandDetector()
        self._block_all = False

    def allow_all(self, enabled: bool) -> None:
        """Developer escape hatch (still logs verdicts). Use with care."""
        self._block_all = not enabled

    # ------------------------------------------------------------------
    def inspect(self, command: str):
        return self.detector.inspection(command)

    async def run(
        self,
        command: str,
        *,
        cwd: str | Path | None = None,
        timeout: float = 60.0,
        capture: bool = True,
        check: bool = False,
        force: bool = False,
    ) -> ShellResult:
        verdict = self.detector.inspection(command)
        if not force and (self._block_all or not verdict.allowed):
            raise ExecutionBlocked(self.detector.block_message(verdict),
                                   details=verdict.as_dict())

        cwd = str(cwd) if cwd else None
        # shell.run receives a command *string*: always run through the platform
        # shell so pipelines/&& work. shell.run_argv runs without a shell and
        # remains the safer option for parameterised invocations. Subprocesses
        # run in a worker thread so the agent's asyncio loop never blocks.
        result = await asyncio.to_thread(
            _run_sync, command, cwd=cwd, timeout=timeout, capture=capture,
            check=check, shell=True)
        result.verdict_risk = verdict.risk
        return result

    async def run_cmd(
        self,
        args: list[str],
        *,
        cwd: str | Path | None = None,
        timeout: float = 60.0,
        check: bool = False,
    ) -> ShellResult:
        """Run an argv list directly (no shell) — same controls as run()."""
        cwd = str(cwd) if cwd else None
        joined = " ".join(_shquote(a) for a in args)
        verdict = self.detector.inspection(joined)
        if self._block_all or not verdict.allowed:
            raise ExecutionBlocked(self.detector.block_message(verdict),
                                   details=verdict.as_dict())
        result = await asyncio.to_thread(
            _run_argv, args, cwd=cwd, timeout=timeout, check=check)
        result.verdict_risk = verdict.risk
        return result


@dataclass
class ShellResult:
    command: str
    returncode: int
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    verdict_risk: str = "none"
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def as_dict(self) -> dict:
        return {"command": self.command, "returncode": self.returncode,
                "stdout": self.stdout, "stderr": self.stderr,
                "duration_ms": self.duration_ms, "ok": self.ok,
                "truncated": self.truncated}

    def short(self) -> str:
        body = (self.stdout or "").strip() or (self.stderr or "").strip()
        return body[:800]


def _run_sync(command: str, *, cwd: str | None, timeout: float,
              capture: bool, check: bool, shell: bool) -> ShellResult:
    import time
    started = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            shell=shell,
            cwd=cwd,
            capture_output=capture,
            text=True,
            timeout=timeout,
            check=False,
            env=_safe_env(),
        )
    except subprocess.TimeoutExpired as exc:
        raise NovaError(f"Command timed out after {timeout}s",
                        code="TOOL_TIMEOUT") from exc
    except OSError as exc:
        raise NovaError(f"Command failed to start: {exc}", code="SHELL_ERROR") from exc

    return _finish(command, proc, started, capture)


def _run_argv(args: list[str], *, cwd: str | None, timeout: float,
              check: bool) -> ShellResult:
    import time
    started = time.monotonic()
    try:
        proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                              timeout=timeout, check=False, env=_safe_env())
    except subprocess.TimeoutExpired as exc:
        raise NovaError(f"Command timed out after {timeout}s", code="TOOL_TIMEOUT") from exc
    except OSError as exc:
        raise NovaError(f"Command failed to start: {exc}", code="SHELL_ERROR") from exc
    cmd = " ".join(a for a in args)
    return _finish(cmd, proc, started, True)


def _finish(command: str, proc, started: float, capture: bool) -> ShellResult:
    import time
    duration = int((time.monotonic() - started) * 1000)
    out = proc.stdout if capture else ""
    err = proc.stderr if capture else ""
    out_t, t_out = _clip(out, 30000)
    err_t, t_err = _clip(err, 30000)
    return ShellResult(command=command, returncode=proc.returncode,
                       stdout=out_t, stderr=err_t, duration_ms=duration,
                       truncated=t_out or t_err)


def _clip(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + "\n…[truncated]", True


def _safe_env() -> dict:
    env = dict(os.environ)
    for k in list(env):
        if "api_key" in k.lower() or "token" in k.lower() or "secret" in k.lower():
            env.pop(k, None)
    return env


def _shquote(s: str) -> str:
    if s and not any(ch in s for ch in " \t\n\"'&|;<>()$`"):
        return s
    return '"' + s.replace('"', '\\"') + '"'


# Module-level shared instance (tools import this). Tests construct their own.
shell = ControlledShell()
