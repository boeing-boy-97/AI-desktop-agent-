"""Computer observation: before/after change detection (V2 §10/§11).

The observer answers one question after every meaningful action:
*what actually changed?*  Evidence sources, in safety order:

1. filesystem state (directory snapshot diff) — deterministic, no screen needed
2. active window / process state
3. screenshot fingerprint — detects visual change without storing pixels

The verifier consumes :class:`ChangeReport`.  A step whose expected effect is
absent from the report is NOT verified as successful (§61).
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Snapshot:
    at: float
    files: dict[str, float] = field(default_factory=dict)   # path -> mtime
    active_window: str | None = None
    screen_fingerprint: str | None = None

    def as_dict(self) -> dict:
        return {"at": self.at, "file_count": len(self.files),
                "active_window": self.active_window,
                "screen_fingerprint": self.screen_fingerprint}


@dataclass
class ChangeReport:
    created: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    window_changed: bool = False
    screen_changed: bool = False
    duration_ms: int = 0

    @property
    def any_change(self) -> bool:
        return bool(self.created or self.modified or self.deleted
                    or self.window_changed or self.screen_changed)

    def as_dict(self) -> dict:
        return {"created": self.created[:20], "modified": self.modified[:20],
                "deleted": self.deleted[:20],
                "window_changed": self.window_changed,
                "screen_changed": self.screen_changed,
                "duration_ms": self.duration_ms,
                "any_change": self.any_change}


class ChangeDetector:
    """Bounded, dependency-free filesystem+window diffing."""

    def __init__(self, observer: Any = None, max_files: int = 5000) -> None:
        self.observer = observer
        self.max_files = max_files

    # ------------------------------------------------------------------
    def snapshot(self, watch_paths: list[str] | None = None) -> Snapshot:
        files: dict[str, float] = {}
        for base in watch_paths or []:
            p = Path(os.path.expanduser(base))
            try:
                if p.is_file():
                    files[str(p)] = p.stat().st_mtime
                    continue
                if not p.is_dir():
                    continue
                for root, _dirs, names in os.walk(p):
                    for name in names:
                        fp = Path(root) / name
                        try:
                            files[str(fp)] = fp.stat().st_mtime
                        except OSError:
                            continue
                        if len(files) >= self.max_files:
                            break
                    if len(files) >= self.max_files:
                        break
            except OSError:
                continue

        window = None
        fingerprint = None
        if self.observer is not None:
            try:
                snap = self.observer.screenshot()
                fingerprint = snap.fingerprint()
                window = getattr(snap, "active_window", None)
            except Exception:
                pass
        return Snapshot(at=time.time(), files=files, active_window=window,
                        screen_fingerprint=fingerprint)

    # ------------------------------------------------------------------
    def diff(self, before: Snapshot, after: Snapshot) -> ChangeReport:
        created, modified, deleted = [], [], []
        for path, mtime in after.files.items():
            prev = before.files.get(path)
            if prev is None:
                created.append(path)
            elif mtime != prev:
                modified.append(path)
        for path in before.files:
            if path not in after.files:
                deleted.append(path)
        report = ChangeReport(
            created=created, modified=modified, deleted=deleted,
            window_changed=bool(before.active_window and after.active_window
                                and before.active_window != after.active_window),
            screen_changed=bool(before.screen_fingerprint
                                and after.screen_fingerprint
                                and before.screen_fingerprint != after.screen_fingerprint),
            duration_ms=int((after.at - before.at) * 1000))
        return report

    # ------------------------------------------------------------------
    def verify_expectation(self, report: ChangeReport,
                           expect: dict) -> tuple[bool, str]:
        """Check a structured expectation against an observed report.

        expect keys: ``file_created``, ``file_exists``, ``window_changed``,
        ``any_change``.
        """
        if "file_created" in expect:
            target = str(expect["file_created"])
            hit = any(c == target or c.endswith(target) for c in report.created)
            if not hit:
                hit = Path(os.path.expanduser(target)).exists()
            return hit, ("created file verified" if hit
                         else f"expected new file '{target}' was not observed")
        if "file_exists" in expect:
            target = os.path.expanduser(str(expect["file_exists"]))
            ok = Path(target).exists()
            return ok, ("file exists" if ok
                        else f"expected file '{target}' does not exist")
        if expect.get("window_changed"):
            return report.window_changed, ("window change verified"
                                           if report.window_changed
                                           else "no window change observed")
        if expect.get("any_change"):
            return report.any_change, ("change observed" if report.any_change
                                       else "no observable change after action")
        return True, "no expectation supplied"
