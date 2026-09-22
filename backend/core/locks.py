"""Resource locks (V2 §30).

Two tasks must never fight over the same exclusive resource:

* ``input``      — the mouse/keyboard stream (single-flight today, locked
                   explicitly so future parallel tasks stay safe)
* ``screen``     — screenshot/observation while input is being automated
* file paths     — two tasks must not edit the same file simultaneously

Locks are advisory and cooperative (tools acquire/release around work); they
are the safety net that makes multi-task execution non-destructive.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path


class ResourceLocks:
    def __init__(self) -> None:
        self._named: dict[str, asyncio.Lock] = {}
        self._paths: dict[str, str] = {}  # normalised path -> owning task id

    def _lock(self, name: str) -> asyncio.Lock:
        if name not in self._named:
            self._named[name] = asyncio.Lock()
        return self._named[name]

    def input_lock(self) -> asyncio.Lock:
        return self._lock("input")

    def screen_lock(self) -> asyncio.Lock:
        return self._lock("screen")

    # -- file path locking -------------------------------------------------
    @staticmethod
    def _norm(path: str) -> str:
        try:
            return str(Path(os.path.abspath(os.path.expanduser(path))).resolve())
        except OSError:
            return path

    def acquire_path(self, path: str, task_id: str) -> tuple[bool, str]:
        """Try to lock *path* for *task_id*. Returns (ok, owner_or_empty)."""
        key = self._norm(path)
        owner = self._paths.get(key)
        if owner and owner != task_id:
            return False, owner
        self._paths[key] = task_id
        return True, ""

    def release_path(self, path: str, task_id: str) -> None:
        key = self._norm(path)
        if self._paths.get(key) == task_id:
            del self._paths[key]

    def release_task(self, task_id: str) -> None:
        """Drop every lock held by a task (cancel/crash safety)."""
        for key in [k for k, v in self._paths.items() if v == task_id]:
            del self._paths[key]

    def held(self) -> dict[str, str]:
        return dict(self._paths)
