"""filesystem.* — secure filesystem tools (spec §7).

Design rules:
    * every operation resolves paths and refuses OS-protected areas
    * deletion requires confirmation (high risk) and uses the recycle bin
    * all methods return structured dicts, never raising for user-visible errors
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import ClassVar

from core.exceptions import SafetyError
from core.safety import (
    build_delete_request,
    delete_path,
    is_protected_path,
    resolve_path,
)
from core.utils import human_bytes
from pydantic import BaseModel, Field
from tools.base import PermissionLevel, Tool, ToolResult


# ---------------------------------------------------------------------------
# inputs
# ---------------------------------------------------------------------------
class ListIn(BaseModel):
    path: str = "."
    pattern: str = "*"
    recursive: bool = False
    max_items: int = 200


class SearchIn(BaseModel):
    query: str = Field(..., min_length=1)
    start_dir: str = "."
    recursive: bool = True
    max_items: int = 100


class MakeDirIn(BaseModel):
    path: str = Field(..., min_length=1)


class WriteFileIn(BaseModel):
    path: str = Field(..., min_length=1)
    content: str = ""


class AppendFileIn(BaseModel):
    path: str
    content: str


class ReadFileIn(BaseModel):
    path: str
    max_chars: int = 50000


class RenameIn(BaseModel):
    source: str
    destination: str


class MoveIn(BaseModel):
    source: str
    destination: str


class CopyIn(BaseModel):
    source: str
    destination: str


class DeleteIn(BaseModel):
    paths: list[str] = Field(..., min_length=1)
    use_recycle_bin: bool = True


class MetadataIn(BaseModel):
    path: str


class DuplicatesIn(BaseModel):
    path: str
    min_size: int = 0
    max_items: int = 100


class OrganizeIn(BaseModel):
    path: str = "."
    rules: dict | None = None


class BiggestIn(BaseModel):
    path: str = "."
    top: int = 10


class RevealIn(BaseModel):
    path: str


class OpenIn(BaseModel):
    path: str


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _safe_resolve(path: str) -> Path:
    p = resolve_path(path)
    try:
        r = p.resolve()
    except OSError:
        r = p.absolute()
    if is_protected_path(r):
        raise SafetyError(f"Operation refused on protected path: {path}",
                          details={"path": str(path)})
    return p


class FilesystemBase(Tool):
    _abstract = True
    category = "filesystem"

    # -- V2 §13 undo journal + §30 path locks ---------------------------
    def _record(self, task_id, op: str, path, **extra) -> None:
        journal = getattr(self.ctx, "undo_journal", None)
        if journal is not None:
            journal.record(task_id, op, str(path), **extra)

    def _lock(self, task_id, *paths) -> str | None:
        """Acquire path locks; returns an error message or None on success."""
        locks = getattr(self.ctx, "locks", None)
        if locks is None or not task_id:
            return None
        acquired: list[str] = []
        for p in paths:
            ok, owner = locks.acquire_path(str(p), task_id)
            if not ok:
                for done in acquired:
                    locks.release_path(done, task_id)
                return (f"'{p}' is locked by another task ({owner}). "
                        "Wait for it to finish or cancel it, then retry.")
            acquired.append(str(p))
        return None

    def _unlock(self, task_id, *paths) -> None:
        locks = getattr(self.ctx, "locks", None)
        if locks is None or not task_id:
            return
        for p in paths:
            locks.release_path(str(p), task_id)


class ListDirTool(FilesystemBase):
    name = "filesystem.list"
    description = "List files/folders in a directory (optionally recursive and glob-filtered)."
    input_model = ListIn
    permission = PermissionLevel.LOW
    timeout = 15

    async def run(self, args, task_id=None) -> ToolResult:
        try:
            base = _safe_resolve(args.path)
        except SafetyError as exc:
            return ToolResult.fail(exc.message, "SAFETY")
        if not base.exists():
            return ToolResult.fail(f"Path does not exist: {base}", "NOT_FOUND")
        files = []
        it = base.rglob(args.pattern) if args.recursive else base.glob(args.pattern)
        for p in it:
            try:
                is_dir = p.is_dir()
                st = p.stat()
                files.append({"name": p.name, "path": str(p), "is_dir": is_dir,
                              "size": 0 if is_dir else st.st_size,
                              "modified": st.st_mtime})
            except OSError:
                continue
            if len(files) >= args.max_items:
                break
        files.sort(key=lambda d: (not d["is_dir"], d["name"].lower()))
        return ToolResult.ok({
            "path": str(base), "count": len(files), "items": files})


class SearchFilesTool(FilesystemBase):
    name = "filesystem.search"
    description = "Search for files/folders by name substring or glob."
    input_model = SearchIn
    permission = PermissionLevel.LOW
    timeout = 20

    async def run(self, args, task_id=None) -> ToolResult:
        try:
            base = _safe_resolve(args.start_dir)
        except SafetyError:
            return ToolResult.fail("Invalid start directory", "SAFETY")
        if not base.exists():
            return ToolResult.fail(f"Start directory does not exist: {base}", "NOT_FOUND")
        low = args.query.lower()
        matches = []
        it = base.rglob("*") if args.recursive else base.iterdir()
        for p in it:
            try:
                if low in p.name.lower():
                    matches.append({"name": p.name, "path": str(p), "is_dir": p.is_dir()})
            except OSError:
                continue
            if len(matches) >= args.max_items:
                break
        matches.sort(key=lambda d: d["name"].lower())
        return ToolResult.ok({"query": args.query, "count": len(matches), "matches": matches})


class CreateFolderTool(FilesystemBase):
    name = "filesystem.create_folder"
    description = "Create a folder (and parents if needed)."
    input_model = MakeDirIn
    permission = PermissionLevel.MEDIUM
    timeout = 10

    async def run(self, args, task_id=None) -> ToolResult:
        try:
            p = _safe_resolve(args.path)
        except SafetyError as exc:
            return ToolResult.fail(exc.message, "SAFETY")
        existed = p.exists()
        if (err := self._lock(task_id, p)):
            return ToolResult.fail(err, "LOCKED")
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return ToolResult.fail(f"Could not create folder: {exc}", "IO_ERROR")
        finally:
            self._unlock(task_id, p)
        if not existed:
            self._record(task_id, "create", p)
        return ToolResult.ok({"path": str(p), "created": not existed, "existed": existed})


class WriteFileTool(FilesystemBase):
    name = "filesystem.write_file"
    description = "Create or overwrite a text file with given content."
    input_model = WriteFileIn
    permission = PermissionLevel.MEDIUM
    timeout = 15

    async def run(self, args, task_id=None) -> ToolResult:
        try:
            p = _safe_resolve(args.path)
        except SafetyError as exc:
            return ToolResult.fail(exc.message, "SAFETY")
        existed = p.exists()
        if (err := self._lock(task_id, p)):
            return ToolResult.fail(err, "LOCKED")
        backup = None
        if existed:
            from agent.undo import snapshot_backup
            backup = snapshot_backup(str(p))  # BEFORE overwriting
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(args.content, encoding="utf-8")
        except OSError as exc:
            return ToolResult.fail(f"Could not write file: {exc}", "IO_ERROR")
        finally:
            self._unlock(task_id, p)
        # undo journal: 'modify' keeps the previous bytes, 'create' does not
        if existed:
            self._record(task_id, "modify", p, backup=backup)
        else:
            self._record(task_id, "create", p)
        return ToolResult.ok({"path": str(p), "bytes": len(args.content.encode()),
                              "overwrote": existed})


class AppendFileTool(FilesystemBase):
    name = "filesystem.append_file"
    description = "Append text content to a file."
    input_model = AppendFileIn
    permission = PermissionLevel.MEDIUM
    timeout = 10

    async def run(self, args, task_id=None) -> ToolResult:
        try:
            p = _safe_resolve(args.path)
        except SafetyError as exc:
            return ToolResult.fail(exc.message, "SAFETY")
        if (err := self._lock(task_id, p)):
            return ToolResult.fail(err, "LOCKED")
        backup = None
        if p.exists():
            from agent.undo import snapshot_backup
            backup = snapshot_backup(str(p))  # BEFORE appending
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                f.write(args.content)
        except OSError as exc:
            return ToolResult.fail(f"Could not append: {exc}", "IO_ERROR")
        finally:
            self._unlock(task_id, p)
        self._record(task_id, "modify", p, backup=backup)
        return ToolResult.ok({"path": str(p), "appended": True})


class ReadFileTool(FilesystemBase):
    name = "filesystem.read_file"
    description = "Read a text file's content."
    input_model = ReadFileIn
    permission = PermissionLevel.LOW
    timeout = 15

    async def run(self, args, task_id=None) -> ToolResult:
        try:
            p = _safe_resolve(args.path)
        except SafetyError as exc:
            return ToolResult.fail(exc.message, "SAFETY")
        if not p.exists():
            return ToolResult.fail(f"File does not exist: {p}", "NOT_FOUND")
        if not p.is_file():
            return ToolResult.fail(f"Not a file: {p}", "TYPE_ERROR")
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return ToolResult.fail(f"Could not read: {exc}", "IO_ERROR")
        truncated = len(text) > args.max_chars
        return ToolResult.ok({
            "path": str(p), "content": text[:args.max_chars],
            "truncated": truncated, "length": len(text)})


class RenameFileTool(FilesystemBase):
    name = "filesystem.rename"
    description = "Rename/move a file or folder (source → destination)."
    input_model = RenameIn
    permission = PermissionLevel.MEDIUM
    timeout = 10

    async def run(self, args, task_id=None) -> ToolResult:
        try:
            src = _safe_resolve(args.source)
            dst = _safe_resolve(args.destination)
        except SafetyError as exc:
            return ToolResult.fail(exc.message, "SAFETY")
        if not src.exists():
            return ToolResult.fail(f"Source not found: {src}", "NOT_FOUND")
        if (err := self._lock(task_id, src, dst)):
            return ToolResult.fail(err, "LOCKED")
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)
        except OSError as exc:
            return ToolResult.fail(f"Rename failed: {exc}", "IO_ERROR")
        finally:
            self._unlock(task_id, src, dst)
        self._record(task_id, "rename", dst, **{"from": str(src)})
        return ToolResult.ok({"source": str(src), "destination": str(dst), "renamed": True})


class MoveFileTool(FilesystemBase):
    name = "filesystem.move"
    description = "Move files/folders (source may be a file or directory)."
    input_model = MoveIn
    permission = PermissionLevel.MEDIUM
    timeout = 20

    async def run(self, args, task_id=None) -> ToolResult:
        try:
            src = _safe_resolve(args.source)
            dst = _safe_resolve(args.destination)
        except SafetyError as exc:
            return ToolResult.fail(exc.message, "SAFETY")
        if not src.exists():
            return ToolResult.fail(f"Source not found: {src}", "NOT_FOUND")
        if (err := self._lock(task_id, src, dst)):
            return ToolResult.fail(err, "LOCKED")
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
        except OSError as exc:
            return ToolResult.fail(f"Move failed: {exc}", "IO_ERROR")
        finally:
            self._unlock(task_id, src, dst)
        self._record(task_id, "move", dst, **{"from": str(src)})
        return ToolResult.ok({"source": str(src), "destination": str(dst), "moved": True})


class CopyFileTool(FilesystemBase):
    name = "filesystem.copy"
    description = "Copy files/folders (recursive for directories)."
    input_model = CopyIn
    permission = PermissionLevel.MEDIUM
    timeout = 30

    async def run(self, args, task_id=None) -> ToolResult:
        try:
            src = _safe_resolve(args.source)
            dst = _safe_resolve(args.destination)
        except SafetyError as exc:
            return ToolResult.fail(exc.message, "SAFETY")
        if not src.exists():
            return ToolResult.fail(f"Source not found: {src}", "NOT_FOUND")
        if (err := self._lock(task_id, dst)):
            return ToolResult.fail(err, "LOCKED")
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
        except OSError as exc:
            return ToolResult.fail(f"Copy failed: {exc}", "IO_ERROR")
        finally:
            self._unlock(task_id, dst)
        self._record(task_id, "create", dst)
        return ToolResult.ok({"source": str(src), "destination": str(dst), "copied": True})


class DeleteTool(FilesystemBase):
    name = "filesystem.delete"
    description = "Delete files/folders (recycle bin by default). Requires confirmation."
    input_model = DeleteIn
    permission = PermissionLevel.HIGH
    requires_confirmation = True
    confirm_message_tpl = "Delete the listed file(s) from disk?"
    timeout = 60

    def summarize_confirmation(self, arguments: dict, task_id: str | None = None) -> str | None:
        # surface what & how much is about to be deleted in the confirmation UI
        try:
            req = build_delete_request(
                arguments.get("paths", []),
                use_recycle_bin=arguments.get("use_recycle_bin", True))
            target = "recycle bin" if req["use_recycle_bin"] else "permanent"
            return (f"Delete {req['count']} item(s) ({req['total_size']}, to {target}): "
                    + ", ".join(req["paths"][:6]))
        except Exception:
            return f"Delete {len(arguments.get('paths', []))} item(s) from disk."

    async def run(self, args, task_id=None) -> ToolResult:
        results = []
        # deletion is I/O-heavy but must not block the event loop
        import asyncio
        for raw in args.paths:
            try:
                p = _safe_resolve(raw)
                results.append(await asyncio.to_thread(
                    delete_path, p, use_recycle_bin=args.use_recycle_bin))
            except SafetyError as exc:
                results.append({"path": raw, "deleted": False, "error": exc.message})
            except OSError as exc:
                results.append({"path": raw, "deleted": False, "error": str(exc)})
        n = sum(1 for r in results if r.get("deleted"))
        if results and n == 0:
            # nothing at all was deleted — that is a failure, not a silent success
            reason = next((r.get("error") for r in results if r.get("error")),
                          "no items could be deleted")
            return ToolResult.fail(f"Nothing deleted: {reason}", "DELETE_FAILED",
                                   data={"deleted": 0, "total": len(results),
                                         "results": results})
        for r in results:
            if r.get("deleted"):
                self._record(task_id, "delete", r.get("path"),
                             trash="os_recycle_bin" if args.use_recycle_bin else "permanent")
        return ToolResult.ok({"deleted": n, "total": len(results), "results": results})


class MetadataTool(FilesystemBase):
    name = "filesystem.metadata"
    description = "Return file metadata (size, type, modification time, hashes)."
    input_model = MetadataIn
    permission = PermissionLevel.LOW
    timeout = 15

    async def run(self, args, task_id=None) -> ToolResult:
        try:
            p = _safe_resolve(args.path)
        except SafetyError as exc:
            return ToolResult.fail(exc.message, "SAFETY")
        if not p.exists():
            return ToolResult.fail(f"Not found: {p}", "NOT_FOUND")
        st = p.stat()
        info = {
            "path": str(p), "name": p.name, "is_dir": p.is_dir(),
            "size": st.st_size if p.is_file() else _dir_size(p),
            "size_human": human_bytes(st.st_size if p.is_file() else _dir_size(p)),
            "extension": p.suffix.lower(),
            "detected_type": _detect_type(p),
            "modified": st.st_mtime, "created": st.st_ctime,
        }
        if p.is_file() and st.st_size < 50 * 1024 * 1024:
            try:
                info["sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
            except OSError:
                pass
        return ToolResult.ok(info)


class FindDuplicatesTool(FilesystemBase):
    name = "filesystem.find_duplicates"
    description = "Detect duplicate files in a tree by size then content hash."
    input_model = DuplicatesIn
    permission = PermissionLevel.LOW
    timeout = 60

    async def run(self, args, task_id=None) -> ToolResult:
        try:
            base = _safe_resolve(args.path)
        except SafetyError as exc:
            return ToolResult.fail(exc.message, "SAFETY")
        if not base.exists():
            return ToolResult.fail(f"Not found: {base}", "NOT_FOUND")
        by_size: dict = {}
        for p in base.rglob("*"):
            try:
                if not p.is_file():
                    continue
                if p.stat().st_size < args.min_size:
                    continue
                by_size.setdefault(p.stat().st_size, []).append(p)
            except OSError:
                continue
        groups = []
        for size, paths in by_size.items():
            if len(paths) < 2 or size == 0:
                continue
            hashes = {}
            for p in paths:
                try:
                    h = hashlib.sha256(p.read_bytes()).hexdigest()
                except OSError:
                    continue
                hashes.setdefault(h, []).append(str(p))
            for h, dups in hashes.items():
                if len(dups) > 1:
                    groups.append({"hash": h, "size": size, "paths": dups})
            if len(groups) >= args.max_items:
                break
        return ToolResult.ok({"duplicates": len(groups), "groups": groups})


class OrganizeTool(FilesystemBase):
    name = "filesystem.organize"
    description = "Organize loose files into category subfolders by extension."
    input_model = OrganizeIn
    permission = PermissionLevel.MEDIUM
    timeout = 30

    _CATEGORIES: ClassVar[dict[str, set[str]]] = {
        "images": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"},
        "documents": {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".odt"},
        "spreadsheets": {".xls", ".xlsx", ".csv", ".ods"},
        "presentations": {".ppt", ".pptx", ".odp"},
        "archives": {".zip", ".rar", ".7z", ".tar", ".gz"},
        "audio": {".mp3", ".wav", ".flac", ".m4a", ".ogg"},
        "video": {".mp4", ".mkv", ".avi", ".mov", ".webm"},
        "code": {".py", ".js", ".ts", ".html", ".css", ".json", ".java", ".c", ".cpp"},
    }

    async def run(self, args, task_id=None) -> ToolResult:
        try:
            base = _safe_resolve(args.path)
        except SafetyError as exc:
            return ToolResult.fail(exc.message, "SAFETY")
        if not base.is_dir():
            return ToolResult.fail(f"Not a directory: {base}", "TYPE_ERROR")
        rules = args.rules or {}
        moved = []
        for p in list(base.iterdir()):
            if not p.is_file() or p.name.startswith("."):
                continue
            ext = p.suffix.lower()
            category = None
            for cat, exts in self._CATEGORIES.items():
                if ext in exts:
                    category = cat
                    break
            if not category:
                continue
            dest = base / (rules.get(category, category))
            try:
                dest.mkdir(exist_ok=True)
                p.rename(dest / p.name)
                moved.append({"file": p.name, "category": category})
            except OSError:
                continue
        return ToolResult.ok({"moved": len(moved), "items": moved[:200]})


class LargestFilesTool(FilesystemBase):
    name = "filesystem.largest"
    description = "Find the largest files in a folder tree."
    input_model = BiggestIn
    permission = PermissionLevel.LOW
    timeout = 30

    async def run(self, args, task_id=None) -> ToolResult:
        try:
            base = _safe_resolve(args.path)
        except SafetyError as exc:
            return ToolResult.fail(exc.message, "SAFETY")
        if not base.exists():
            return ToolResult.fail(f"Not found: {base}", "NOT_FOUND")
        sizes = []
        for p in base.rglob("*"):
            try:
                if p.is_file():
                    sizes.append((p.stat().st_size, str(p)))
            except OSError:
                continue
        sizes.sort(reverse=True)
        top = [{"path": p, "size": s, "size_human": human_bytes(s)}
               for s, p in sizes[: args.top]]
        return ToolResult.ok({"path": str(base), "largest": top})


class RevealTool(FilesystemBase):
    name = "filesystem.reveal"
    description = "Reveal a file/folder in the system file manager."
    input_model = RevealIn
    permission = PermissionLevel.LOW
    timeout = 10

    async def run(self, args, task_id=None) -> ToolResult:
        try:
            p = _safe_resolve(args.path)
        except SafetyError as exc:
            return ToolResult.fail(exc.message, "SAFETY")
        import asyncio
        import platform
        try:
            if platform.system() == "Windows":
                await asyncio.create_subprocess_exec("explorer", "/select,", str(p))
            elif platform.system() == "Darwin":
                await asyncio.create_subprocess_exec("open", "-R", str(p))
            else:
                await asyncio.create_subprocess_exec("xdg-open", str(p.parent))
        except OSError as exc:
            return ToolResult.fail(f"Could not reveal: {exc}", "IO_ERROR")
        return ToolResult.ok({"revealed": str(p)})


class OpenFileTool(FilesystemBase):
    name = "filesystem.open"
    description = "Open a file/folder with the default application."
    input_model = OpenIn
    permission = PermissionLevel.LOW
    timeout = 15

    async def run(self, args, task_id=None) -> ToolResult:
        try:
            p = _safe_resolve(args.path)
        except SafetyError as exc:
            return ToolResult.fail(exc.message, "SAFETY")
        import asyncio
        import platform
        try:
            if platform.system() == "Windows":
                await asyncio.create_subprocess_exec("cmd", "/c", "start", "", str(p))
            elif platform.system() == "Darwin":
                await asyncio.create_subprocess_exec("open", str(p))
            else:
                await asyncio.create_subprocess_exec("xdg-open", str(p))
        except OSError as exc:
            return ToolResult.fail(f"Could not open: {exc}", "IO_ERROR")
        return ToolResult.ok({"opened": str(p)})


def _dir_size(p: Path) -> int:
    total = 0
    for child in p.rglob("*"):
        try:
            if child.is_file():
                total += child.stat().st_size
        except OSError:
            continue
    return total


def _detect_type(p: Path) -> str:
    if p.is_dir():
        return "directory"
    ext = p.suffix.lower()
    mapping = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
        ".pdf": "application/pdf", ".doc": "application/msword",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xls": "application/vnd.ms-excel", ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".zip": "application/zip", ".rar": "application/x-rar-compressed",
        ".7z": "application/x-7z-compressed", ".tar": "application/x-tar",
        ".gz": "application/gzip",
        ".mp3": "audio/mpeg", ".wav": "audio/wav", ".flac": "audio/flac",
        ".mp4": "video/mp4", ".mkv": "video/x-matroska",
        ".txt": "text/plain", ".md": "text/markdown", ".html": "text/html",
        ".css": "text/css", ".js": "application/javascript", ".py": "text/x-python",
        ".json": "application/json", ".csv": "text/csv",
    }
    return mapping.get(ext, "application/octet-stream")
