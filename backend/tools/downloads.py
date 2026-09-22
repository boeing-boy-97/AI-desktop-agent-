"""downloads.* — direct (non-browser) file downloads via httpx with size limits.

Used for reliable "download this PDF/photo" operations when a URL is known and
no browser session is required. Streams to disk and verifies the file appeared.
"""
from __future__ import annotations

from pathlib import Path

import httpx
from core.safety import resolve_path
from pydantic import BaseModel, Field
from tools.base import PermissionLevel, Tool, ToolResult


class DownloadUrlIn(BaseModel):
    url: str = Field(..., min_length=1)
    save_dir: str | None = None
    filename: str | None = None
    max_size_mb: float = 200.0


class DirectDownloadTool(Tool):
    name = "downloads.download_url"
    description = ("Download a file directly from a URL (no browser) into a local "
                   "folder; verifies the file appears and reports its size.")
    input_model = DownloadUrlIn
    permission = PermissionLevel.MEDIUM
    timeout = 180

    async def run(self, args, task_id=None) -> ToolResult:
        save_dir = Path(args.save_dir or str(self.ctx.settings.downloads_dir))
        try:
            save_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return ToolResult.fail(f"Invalid save directory: {exc}", "IO_ERROR")

        filename = args.filename or _derive_filename(args.url)
        dest = resolve_path(save_dir / filename)

        try:
            async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client, \
                    client.stream("GET", args.url) as resp:
                if resp.status_code >= 400:
                    return ToolResult.fail(f"HTTP {resp.status_code} from {args.url}",
                                           "HTTP_ERROR")
                content_length = int(resp.headers.get("content-length", 0) or 0)
                if content_length and content_length > args.max_size_mb * 1024 * 1024:
                    return ToolResult.fail(
                        f"File too large ({content_length} bytes > {args.max_size_mb}MB)",
                        "SIZE_LIMIT")
                written = 0
                with dest.open("wb") as f:
                    async for chunk in resp.aiter_bytes():
                        f.write(chunk)
                        written += len(chunk)
                        if written > args.max_size_mb * 1024 * 1024:
                            dest.unlink(missing_ok=True)
                            return ToolResult.fail("File exceeded size limit", "SIZE_LIMIT")
        except httpx.HTTPError as exc:
            return ToolResult.fail(f"Download failed: {exc}", "NETWORK_ERROR")
        except OSError as exc:
            return ToolResult.fail(f"Could not write file: {exc}", "IO_ERROR")

        verified = dest.exists() and dest.stat().st_size > 0
        from core.utils import human_bytes
        return ToolResult.ok({
            "path": str(dest), "size": dest.stat().st_size,
            "size_human": human_bytes(dest.stat().st_size),
            "verified": verified})


def _derive_filename(url: str) -> str:
    from urllib.parse import unquote, urlparse
    name = unquote(urlparse(url).path.rstrip("/").split("/")[-1])
    if not name or "." not in name:
        return "download.bin"
    # strip query fragments safety
    return name.split("?")[0]
