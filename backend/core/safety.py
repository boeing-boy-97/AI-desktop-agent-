"""Safety primitives for the execution layer.

The AI model is treated as an *untrusted planner*: every shell command and
every filesystem path passes through checks here before touching the OS.
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from core.exceptions import SafetyError

_IS_WINDOWS = platform.system() == "Windows"

# ---------------------------------------------------------------------------
# Dangerous shell command detection
# ---------------------------------------------------------------------------
_BLOCKED_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?:^|[\s;&|])format\s+[a-z]:", re.IGNORECASE),          # format c:
    re.compile(r"(?:^|[\s;&|])(del|erase|rmdir|rd)\b.*(?:^|\s)(/s|/q|-r)[/\s].*[%*]",
               re.IGNORECASE),
    re.compile(r"(?:^|[\s;&|])(del|erase)\b(?:.*\s)?(/f|/p)(?:\s|$).*[%*]?",
               re.IGNORECASE),
    re.compile(r"(?:^|[\s;&|])(rm|rmdir)\b.*(?:^|\s)(-rf|--recursive|--force)(?:\s|$)",
               re.IGNORECASE),
    re.compile(r"(?:^|[\s;&|])(rmdir|rd)\s+/s\s+/q\s+[a-z]:[\\/]", re.IGNORECASE),
    re.compile(r"rm\s+-rf\s+(?:\s*/\s*$|\*\s*$|~\s*$)", re.IGNORECASE),
    re.compile(r"del\s+/[fq]\s+[^ ]*\\?\*\." , re.IGNORECASE),
    re.compile(r"(?:^|[\s;&|])(shutdown)\b.*(?:^|\s)(/s|/r|/g|/p|-h|-r|-P)(?:\s|$)",
               re.IGNORECASE),
    re.compile(r"(?:^|[\s;&|])(shutdown|reboot|poweroff|halt)\b", re.IGNORECASE),
    re.compile(r"(?:^|[\s;&|])(mkfs|fdisk|parted|diskpart)\b", re.IGNORECASE),
    re.compile(r"(?:^|[\s;&|])(chkdsk|scandisk|defrag)\b\s+/", re.IGNORECASE),
    re.compile(r"(?:^|[\s;&|])(chmod|chown|chgrp)\b.*\b(777|--reference)\b", re.IGNORECASE),
    re.compile(r"(?:^|[\s;&|])(bcdedit|bootrec|sfc|dism)\b.*(?:^|\s)(/cleanup|/revert|/repair|/delete)(?:\s|$)",
               re.IGNORECASE),
    re.compile(r"(?:^|[\s;&|])powershell\b.*(?:^|\s)(-enc(?:odedcommand)?|-ec)(?:\s|$)",
               re.IGNORECASE),
    re.compile(r"(?:^|[\s;&|])powershell\b.*remove-item\b.*-recurse", re.IGNORECASE),
    re.compile(r"(?:^|[\s;&|])cmd(?:\.exe)?\b.*(?:^|\s)(/c|/k)(?:\s|$).*\brd\b",
               re.IGNORECASE),
    re.compile(r">\s*([a-z]:[\\/]|[\\/])\s*$", re.IGNORECASE),  # redirection to root drive
    re.compile(r"(?:^|[\s;&|])iptables\b", re.IGNORECASE),
    re.compile(r"(?:^|[\s;&|])netsh\b.*advfirewall\b.*delete\b", re.IGNORECASE),
    re.compile(r"(?:^|[\s;&|])cipher\b\s+/w", re.IGNORECASE),
    re.compile(r"(?:^|[\s;&|])reg\s+(?:add|delete)\b", re.IGNORECASE),
    re.compile(r"(?:^|[\s;&|])sudo\b", re.IGNORECASE),
    re.compile(r"(?:^|[\s;&|])dd\s+if=", re.IGNORECASE),
    re.compile(r"(?:^|[\s;&|])taskkill\b.*(?:^|\s)(/f|/t|/im)(?:\s|$).*(?:^|\s)(/f)(?:\s|$)",
               re.IGNORECASE),
]

_URL_RE = re.compile(r"https?://[^\s\"']+", re.IGNORECASE)
_BASE64_RE = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")


@dataclass
class CommandVerdict:
    allowed: bool
    reason: str = ""
    risk: str = "none"          # none | low | medium | high | blocked
    sanitised: str = ""
    encoding_suspicious: bool = False
    matches: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"allowed": self.allowed, "reason": self.reason, "risk": self.risk,
                "encoding_suspicious": self.encoding_suspicious, "matches": self.matches}


class DangerousCommandDetector:
    """Stateless command classifier used by the shell execution layer."""

    def inspection(self, command: str) -> CommandVerdict:
        command = (command or "").strip()
        if not command:
            return CommandVerdict(allowed=False, reason="empty command")

        verdict = CommandVerdict(allowed=True, sanitised=command)
        for pat in _BLOCKED_PATTERNS:
            m = pat.search(command)
            if m:
                verdict.allowed = False
                verdict.risk = "blocked"
                verdict.matches.append(pat.pattern)
                verdict.reason = f"command matches dangerous pattern: {pat.pattern}"
                return verdict

        if _BASE64_RE.search(command) and len(command) > 80 and "base64" not in command.lower():
            # large opaque token — flagged as suspicious, not automatically blocked
            verdict.encoding_suspicious = True

        low = command.lower()
        if _is_destructive(low):
            verdict.risk = "high"
            verdict.reason = "destructive operation (delete/overwrite)" if verdict.allowed else verdict.reason
        elif _is_privileged(low):
            verdict.risk = "high"
            verdict.reason = "privileged/system operation"
        else:
            verdict.risk = "low"
        return verdict

    def block_message(self, verdict: CommandVerdict) -> str:
        return (f"Blocked command: {verdict.reason}. "
                f"Manual terminal execution is required for this operation.")


def _is_destructive(low: str) -> bool:
    return any(tok in low for tok in (
        "rm -rf", "rmdir /s", "del /f", "del /q", "format ", "diskpart",
        "remove-item -recurse", "--force --purge", "dd if=",
    ))


def _is_privileged(low: str) -> bool:
    return any(tok in low for tok in (
        "sudo ", "runas", " /uac", "reg add", "reg delete", "sc config",
        "netsh", "bcdedit", "shutdown", "taskkill /f /t", "net user",
    ))


# ---------------------------------------------------------------------------
# Filesystem path validation
# ---------------------------------------------------------------------------
_PROTECTED_WIN = {
    "c:\\windows", "c:\\program files", "c:\\program files (x86)",
    "c:\\programdata", "c:\\$recycle.bin", "c:\\system volume information",
}
_PROTECTED_POSIX = {"/", "/etc", "/usr", "/bin", "/sbin", "/lib", "/boot",
                    "/proc", "/sys", "/dev", "/var", "/opt", "/root"}


def resolve_path(path: str | Path) -> Path:
    return Path(path).expanduser()


def is_protected_path(path: Path) -> bool:
    """Whether a path points at (or inside) an OS-protected area."""
    p = str(path.resolve()).lower().rstrip("\\/")
    if not p:
        return False
    protected = _PROTECTED_WIN if _IS_WINDOWS else _PROTECTED_POSIX
    sep = "\\" if _IS_WINDOWS else "/"
    for entry in protected:
        entry_norm = entry.lower().rstrip("\\/")
        if not entry_norm:
            # bare root ("/") — only the root itself is protected, not its children
            if p == "/":
                return True
            continue
        if p == entry_norm or p.startswith(entry_norm + sep):
            return True
    return False


def ensure_within(root: Path, path: Path) -> Path:
    """Ensure ``path`` is inside ``root`` (resolved). Raises SafetyError otherwise."""
    try:
        r = path.resolve()
    except OSError:
        r = path.absolute()
    try:
        root_r = root.resolve()
    except OSError:
        root_r = root.absolute()
    if r != root_r and root_r not in r.parents:
        raise SafetyError(f"Path escapes allowed area: {path} (root={root})",
                          details={"path": str(path), "root": str(root)})
    return r


def build_delete_request(paths: list[str], use_recycle_bin: bool = True) -> dict:
    paths = [str(p) for p in paths if str(p).strip()]
    try:
        from core.utils import human_bytes
        total = sum(_file_size(Path(p)) for p in paths)
        size_str = human_bytes(total)
    except Exception:
        size_str = "unknown size"
    return {
        "count": len(paths),
        "paths": paths[:40],
        "total_size": size_str,
        "use_recycle_bin": use_recycle_bin,
    }


def _file_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            continue
    return total


def delete_path(path: str | Path, *, use_recycle_bin: bool = True) -> dict:
    """Delete a file/folder. Recycle-bin when possible, permanent as fallback.

    Returns a dict describing the outcome. Protected paths are refused.
    """
    path = resolve_path(path)
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path.absolute()

    if is_protected_path(resolved):
        raise SafetyError(f"Refusing to delete protected path: {path}",
                          details={"path": str(path)})
    if not resolved.exists():
        return {"path": str(path), "existed": False, "deleted": False,
                "method": "none", "message": "path does not exist"}

    method = "recycle_bin"
    try:
        if use_recycle_bin:
            _send2trash(str(resolved))
        else:
            method = "permanent"
            raise RuntimeError("fallthrough")
    except Exception:
        method = "permanent"
        if resolved.is_dir():
            shutil.rmtree(resolved)
        else:
            resolved.unlink(missing_ok=True)
    return {"path": str(path), "existed": True, "deleted": True,
            "method": method, "message": f"deleted via {method}"}


def _send2trash(path: str) -> None:
    """Move to OS recycle bin; on Windows via PowerShell shell API, else send2trash if present."""
    if _IS_WINDOWS:
        script = (
            "Add-Type -AssemblyName Microsoft.VisualBasic;"
            f"[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory("
            f"'{path.replace(chr(39), chr(39) + chr(39))}',"
            "'OnlyErrorDialogs','SendToRecycleBin')"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, timeout=30, check=False)
        if Path(path).exists():
            # Recycle bin API failed (network drive etc.) — caller falls back
            raise RuntimeError("recycle failed")
        return
    try:
        from send2trash import send2trash  # type: ignore
        send2trash(path)
    except Exception:
        # POSIX fallback: trash-cli if available, else our own ~/.local/share/Trash
        trash = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "Trash/files"
        trash.mkdir(parents=True, exist_ok=True)
        src = Path(path)
        dest = trash / (src.name + "-" + _suffix())
        shutil.move(str(src), str(dest))


def _suffix() -> str:
    import uuid
    return uuid.uuid4().hex[:8]
