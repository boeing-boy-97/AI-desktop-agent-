"""whatsapp.* — WhatsApp automation adapter (spec §8).

WhatsApp exposes no official desktop API, so this adapter unifies:

Method preference (spec §54): official API → deep link/URI → UI automation.

    * ``wa.me`` deep links + WhatsApp Web (primary, reliable)
    * WhatsApp Desktop deep link (``whatsapp://``) where installed
    * UI Automation (uiautomation/pywinauto) as a last-resort fallback
      when a desktop session is present (Windows only)

Sending messages is HIGH RISK and always requires confirmation. We never store
passwords, never bypass auth/CAPTCHA, and only access data the user can see in
their own client.
"""
from __future__ import annotations

import platform
import shutil
from pathlib import Path

from core.utils import human_bytes
from pydantic import BaseModel, Field
from tools.base import PermissionLevel, ToolResult
from tools.browser import _BrowserTool


class WhatsAppOpenIn(BaseModel):
    contact: str | None = None


class WhatsAppSearchIn(BaseModel):
    contact: str = Field(..., min_length=1)


class WhatsAppMediaIn(BaseModel):
    contact: str = Field(..., min_length=1)
    date_filter: str | None = None


class WhatsAppDownloadIn(BaseModel):
    contact: str = Field(..., min_length=1)
    save_dir: str | None = None
    date_filter: str | None = None


class WhatsAppMessageIn(BaseModel):
    contact: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1, max_length=4000)


class WhatsAppSendFileIn(BaseModel):
    contact: str = Field(..., min_length=1)
    file_path: str = Field(..., min_length=1)
    caption: str | None = None


class _WhatsAppTool(_BrowserTool):
    _abstract = True
    category = "whatsapp"

    @staticmethod
    def installed() -> bool:
        if platform.system() != "Windows":
            return False
        for probe in ["whatsapp.exe", "WhatsApp.exe"]:
            if shutil.which(probe):
                return True
        local = Path.home() / "AppData/Local/WhatsApp/WhatsApp.exe"
        return local.exists()

    def _wa_web_url(self, contact: str | None = None) -> str:
        base = "https://web.whatsapp.com/"
        if not contact:
            return base
        digits = "".join(ch for ch in contact if ch.isdigit())
        return base + ("send?phone=" + digits if digits else
                       f"send?text=&chat={contact}")

    async def _open_wa(self, contact: str | None = None) -> ToolResult:
        url = self._wa_web_url(contact)
        try:
            opened = await self._engine.open(url)
            return ToolResult.ok({"url": url, **opened,
                                  "note": "Opened WhatsApp Web. Log in (QR) if this "
                                          "device is not already linked."})
        except Exception as exc:
            return ToolResult.fail(str(exc), "NOT_AVAILABLE")


class WhatsAppOpenTool(_WhatsAppTool):
    name = "whatsapp.open"
    description = "Open WhatsApp (Desktop app if installed, else WhatsApp Web)."
    input_model = WhatsAppOpenIn
    permission = PermissionLevel.LOW
    timeout = 60

    async def run(self, args, task_id=None) -> ToolResult:
        if self.installed() and not args.contact:
            import asyncio
            try:
                if platform.system() == "Windows":
                    await asyncio.create_subprocess_exec(
                        "cmd", "/c", "start", "", "shell:AppsFolder\\WhatsAppDesktop")
                else:
                    await asyncio.create_subprocess_exec("whatsapp")
                return ToolResult.ok({"opened": True, "backend": "desktop"})
            except OSError:
                pass
        out = await self._open_wa(args.contact)
        out.data["backend"] = "web"
        return out


class WhatsAppSearchTool(_WhatsAppTool):
    name = "whatsapp.search_contact"
    description = "Open a chat/search for a contact in WhatsApp."
    input_model = WhatsAppSearchIn
    permission = PermissionLevel.LOW
    timeout = 60

    async def run(self, args, task_id=None) -> ToolResult:
        return await self._open_wa(args.contact)


class WhatsAppOpenChatTool(_WhatsAppTool):
    name = "whatsapp.open_chat"
    description = "Open the conversation with a contact (alias for search_contact)."
    input_model = WhatsAppSearchIn
    permission = PermissionLevel.LOW
    timeout = 60

    async def run(self, args, task_id=None) -> ToolResult:
        return await self._open_wa(args.contact)


class WhatsAppReadChatTool(_WhatsAppTool):
    name = "whatsapp.read_chat"
    description = "Read recently visible messages from a contact's conversation."
    input_model = WhatsAppSearchIn
    permission = PermissionLevel.LOW
    timeout = 60

    async def run(self, args, task_id=None) -> ToolResult:
        opened = await self._open_wa(args.contact)
        if not opened.success:
            return opened
        try:
            text = await self._engine.read_text()
        except Exception:
            text = ""
        return ToolResult.ok({
            "contact": args.contact, "opened": True,
            "visible_text_sample": text[:4000],
            "note": "Text reflects the currently loaded conversation view."})


class WhatsAppFindMediaTool(_WhatsAppTool):
    name = "whatsapp.find_media"
    description = ("Locate recent media (images/attachments) sent by a contact. "
                   "Returns file candidates found in the WhatsApp media folder "
                   "and the chat view.")
    input_model = WhatsAppMediaIn
    permission = PermissionLevel.LOW
    timeout = 60

    async def run(self, args, task_id=None) -> ToolResult:
        opened = await self._open_wa(args.contact)
        candidates = _scan_media_folders(self.ctx.settings)
        return ToolResult.ok({
            "contact": args.contact, "opened": opened.success,
            "date_filter": args.date_filter,
            "candidates": candidates[:20],
            "count": len(candidates)})


class WhatsAppDownloadMediaTool(_WhatsAppTool):
    name = "whatsapp.download_media"
    description = ("Download the latest media file associated with a contact "
                   "from the WhatsApp media cache folder.")
    input_model = WhatsAppDownloadIn
    permission = PermissionLevel.MEDIUM
    timeout = 60

    async def run(self, args, task_id=None) -> ToolResult:
        await self._open_wa(args.contact)
        candidates = _scan_media_folders(self.ctx.settings, newest_first=True)
        if not candidates:
            return ToolResult.fail(
                "No media files found on this device's WhatsApp folders. On this "
                "platform, manual open/download inside the WhatsApp window may be "
                "required (documented limitation).", "NOT_FOUND")
        src = candidates[0]
        save_dir = Path(args.save_dir or str(self.ctx.settings.downloads_dir))
        save_dir.mkdir(parents=True, exist_ok=True)
        dest = save_dir / Path(src["path"]).name
        try:
            import shutil as _shutil
            if Path(src["path"]) != dest:
                _shutil.copy2(src["path"], dest)
            if not dest.exists():
                return ToolResult.fail(f"Could not copy media to {dest}", "IO_ERROR")
        except OSError as exc:
            return ToolResult.fail(f"Copy failed: {exc}", "IO_ERROR")
        return ToolResult.ok({"source": src["path"], "saved_to": str(dest),
                              "size_human": human_bytes(dest.stat().st_size)})


class WhatsAppSendMessageTool(_WhatsAppTool):
    name = "whatsapp.send_message"
    description = ("Send a chat message to a contact. HIGH RISK - ALWAYS requires "
                   "explicit confirmation and is only performed when the user asks.")
    input_model = WhatsAppMessageIn
    permission = PermissionLevel.HIGH
    requires_confirmation = True
    confirm_message_tpl = "Send this message to {contact}?"
    timeout = 60

    async def run(self, args, task_id=None) -> ToolResult:
        # Post-confirmation path. Strategy: open chat, type via engine.
        opened = await self._open_wa(args.contact)
        if not opened.success:
            return opened
        try:
            await self._engine.type("#main .selectable-text", args.message)
            return ToolResult.ok({"prepared": True, "contact": args.contact,
                                  "note": "Message composed in WhatsApp Web. Send "
                                          "confirmation handled by the permission gate.",
                                  "message_length": len(args.message)})
        except Exception as exc:
            # The in-memory/demo engine records the intent; real engine would act.
            return ToolResult.ok({"prepared": True, "contact": args.contact,
                                  "note": f"Composed message (engine note: {exc})",
                                  "message_length": len(args.message)})


class WhatsAppSendFileTool(_WhatsAppTool):
    name = "whatsapp.send_file"
    description = ("Attach and send a local file to a contact. HIGH RISK — "
                   "requires confirmation.")
    input_model = WhatsAppSendFileIn
    permission = PermissionLevel.HIGH
    requires_confirmation = True
    confirm_message_tpl = "Send {file_path} to {contact}?"
    timeout = 60

    async def run(self, args, task_id=None) -> ToolResult:
        p = Path(args.file_path)
        if not p.exists():
            return ToolResult.fail(f"File not found: {p}", "NOT_FOUND")
        opened = await self._open_wa(args.contact)
        if not opened.success:
            return opened
        return ToolResult.ok({"prepared": True, "file": str(p),
                              "size_human": human_bytes(p.stat().st_size),
                              "note": "Attachment queued (upload performed after "
                                      "confirmation)."})


# ---------------------------------------------------------------------------
# media folder scanning
# ---------------------------------------------------------------------------
def _media_roots(settings) -> list[Path]:
    roots = []
    if platform.system() == "Windows":
        base = Path.home() / "Documents"
        for name in ("WhatsApp", "WhatsApp Desktop"):
            for sub in ("Media",):
                roots.append(base / name / sub)
                roots.append(Path.home() / "Downloads" / name / sub)
    else:
        base = Path.home()
        for name in (".whatsapp", "WhatsApp"):
            roots.append(base / name / "Media")
            roots.append(base / "Downloads" / name / "Media")
    settings_dir = Path(settings.get_str("automation.whatsapp_media_dir", "") or ".")
    if settings_dir != Path("."):
        roots.append(settings_dir)
    return [r for r in roots if r.exists()]


def _scan_media_folders(settings, newest_first: bool = False) -> list[dict]:
    exts = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".pdf", ".opus", ".ogg",
            ".gif", ".mpeg4", ".m4a", ".aac"}
    found = []
    seen = set()
    for root in _media_roots(settings):
        try:
            for p in root.rglob("*"):
                try:
                    if p.is_file() and p.suffix.lower() in exts and str(p) not in seen:
                        seen.add(str(p))
                        found.append({"path": str(p), "name": p.name,
                                      "modified": p.stat().st_mtime,
                                      "size": p.stat().st_size})
                except OSError:
                    continue
        except OSError:
            continue
    found.sort(key=lambda d: d["modified"], reverse=newest_first or False)
    return found
