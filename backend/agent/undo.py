"""Undo journal + rollback system (V2 §13/§21/§47).

Every filesystem mutation executed by a tool is recorded here *before or
immediately after* the operation, together with enough information to roll it
back:

* ``create``  -> rollback moves the created item to the trash
* ``modify``  -> the previous content is snapshotted (size-capped) and restored
* ``move`` / ``rename`` -> rollback moves the item back
* ``delete``  -> items go through the OS trash, so rollback is best-effort
  (the trash location is OS controlled); the journal still records it so the
  user is told exactly where the item went.

The journal is persisted to disk (bounded), so "undo what you did" keeps
working across restarts.  Nothing here ever executes model output — it only
reverses operations NOVA itself performed.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

MAX_ENTRIES = 500
BACKUP_CAP_BYTES = 1_000_000  # only snapshot small files for byte-rollback


def snapshot_backup(path: str) -> str | None:
    """Copy a (small) file to a private .nova-bak BEFORE it is modified.

    Returns the backup path so callers can hand it to
    :meth:`UndoJournal.record` — the journal only snapshots itself when no
    backup is supplied, which is too late for callers that overwrite in place.
    """
    try:
        p = Path(path)
        if p.is_file() and p.stat().st_size <= BACKUP_CAP_BYTES:
            backup = p.with_name(p.name + ".nova-bak")
            shutil.copy2(p, backup)
            return str(backup)
    except OSError:
        pass
    return None


class UndoResult:
    def __init__(self, undone: list[dict], skipped: list[dict],
                 summary: str) -> None:
        self.undone = undone
        self.skipped = skipped
        self.summary = summary

    def as_dict(self) -> dict:
        return {"undone": self.undone, "skipped": self.skipped,
                "summary": self.summary}


class UndoJournal:
    def __init__(self, journal_path: str | Path | None = None) -> None:
        self._path = Path(journal_path) if journal_path else None
        self._entries: list[dict[str, Any]] = []
        if self._path and self._path.exists():
            try:
                self._entries = json.loads(self._path.read_text("utf-8"))
                if not isinstance(self._entries, list):
                    self._entries = []
            except (OSError, json.JSONDecodeError):
                self._entries = []

    # ------------------------------------------------------------------
    def _persist(self) -> None:
        if not self._path:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._entries[-MAX_ENTRIES:], indent=1), "utf-8")
        except OSError:
            pass  # journal persistence is best-effort; never break the tool

    def record(self, task_id: str | None, op: str, path: str, **extra: Any) -> None:
        entry = {"task_id": task_id, "op": op, "path": str(path),
                 "at": time.time(), **extra}
        if op == "modify" and "backup" not in extra:
            entry["backup"] = self._snapshot(path)
        self._entries.append(entry)
        if len(self._entries) > MAX_ENTRIES:
            del self._entries[:len(self._entries) - MAX_ENTRIES]
        self._persist()

    @staticmethod
    def _snapshot(path: str) -> str | None:
        """Copy small files to a private backup so modify can be reversed."""
        try:
            p = Path(path)
            if p.is_file() and p.stat().st_size <= BACKUP_CAP_BYTES:
                backup = p.with_name(p.name + ".nova-bak")
                shutil.copy2(p, backup)
                return str(backup)
        except OSError:
            pass
        return None

    # ------------------------------------------------------------------
    def entries_for(self, task_id: str) -> list[dict]:
        return [e for e in self._entries if e.get("task_id") == task_id]

    def last_task_id(self) -> str | None:
        for e in reversed(self._entries):
            if e.get("task_id"):
                return e["task_id"]
        return None

    def describe_recent(self, limit: int = 20) -> list[dict]:
        return list(reversed(self._entries[-limit:]))

    # ------------------------------------------------------------------
    def undo_last(self, task_id: str | None = None) -> UndoResult:
        """Roll back the most recent task's operations (newest first).

        Without *task_id*, the most recent task with journal entries is used.
        """
        target = task_id or self.last_task_id()
        if not target:
            return UndoResult([], [], "Nothing to undo: no recorded operations.")
        entries = [e for e in self._entries if e.get("task_id") == target]
        if not entries:
            return UndoResult([], [], "Nothing to undo for that task.")

        undone: list[dict] = []
        skipped: list[dict] = []
        for entry in reversed(entries):
            ok, note = self._rollback(entry)
            (undone if ok else skipped).append(
                {"op": entry["op"], "path": entry["path"], "note": note})
            if ok:
                self._entries.remove(entry)
        self._persist()
        summary = (f"Undid {len(undone)} operation(s)"
                   + (f"; {len(skipped)} could not be reversed automatically"
                      if skipped else "")
                   + ".")
        return UndoResult(undone, skipped, summary)

    # ------------------------------------------------------------------
    def _rollback(self, entry: dict) -> tuple[bool, str]:
        op = entry.get("op")
        path = entry.get("path", "")
        try:
            if op == "create":
                if self._trash(path):
                    return True, "created item moved to trash"
                return False, "created item no longer exists"
            if op == "modify":
                backup = entry.get("backup")
                if backup and Path(backup).exists():
                    shutil.copy2(backup, path)
                    Path(backup).unlink(missing_ok=True)
                    return True, "previous content restored"
                return False, "no backup available for this file"
            if op in ("move", "rename"):
                src = entry.get("from")
                if src and Path(path).exists():
                    Path(src).parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(path, src)
                    return True, f"moved back to {src}"
                return False, "moved item no longer exists where expected"
            if op == "delete":
                return False, ("item was moved to the OS trash — restore it "
                               "from the Recycle Bin/trash")
        except OSError as exc:
            return False, f"rollback failed: {exc}"
        return False, f"no rollback strategy for operation '{op}'"

    @staticmethod
    def _trash(path: str) -> bool:
        try:
            import send2trash
            if Path(path).exists():
                send2trash.send2trash(path)
                return True
            return False
        except Exception:
            try:
                if Path(path).is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    os.unlink(path)
                return True
            except OSError:
                return False
