"""Update system architecture (spec §54).

Design rules:
* NOVA NEVER downloads or installs an update silently. The checker only
  reports availability; installation is always a deliberate user action.
* The checker is modular: the transport is an injected async callable so a
  future updater binary / service can be plugged in without touching this
  module.
* Every failure mode degrades to a status string with a reason — an update
  check can never crash the application.

Settings:
* ``updates.enabled``      — master switch (default True)
* ``updates.manifest_url`` — JSON manifest location (default "" = not
  configured → status ``not_configured``)

Manifest format (JSON):
    {"version": "2.1.0",
     "url": "https://example.com/nova-2.1.0-setup.exe",
     "notes": "…",
     "released_at": "2026-09-01"}
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

# injectable transport: async (url) -> raw text; default is urllib in a thread
Fetcher = Callable[[str], Awaitable[str]]

CURRENT_VERSION = "2.0.0"


@dataclass
class UpdateInfo:
    latest_version: str
    url: str = ""
    notes: str = ""
    released_at: str = ""

    def as_dict(self) -> dict:
        return {"latest_version": self.latest_version, "url": self.url,
                "notes": self.notes, "released_at": self.released_at}


def parse_version(v: str) -> tuple[int, ...]:
    """'2.10.3' -> (2, 10, 3); non-numeric segments count as 0."""
    parts: list[int] = []
    for seg in v.strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in seg if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def is_newer(candidate: str, current: str) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    n = max(len(a), len(b))
    a += (0,) * (n - len(a))
    b += (0,) * (n - len(b))
    return a > b


class UpdateChecker:
    """Reports whether a newer NOVA version is available. Never installs."""

    def __init__(self, settings=None, *, fetcher: Fetcher | None = None,
                 current_version: str = CURRENT_VERSION) -> None:
        self.settings = settings
        self.fetcher = fetcher or self._default_fetcher
        self.current_version = current_version

    # ------------------------------------------------------------------
    async def check(self) -> dict[str, Any]:
        enabled = True
        manifest_url = ""
        if self.settings is not None:
            enabled = self.settings.get_bool("updates.enabled", True)
            manifest_url = self.settings.get_str("updates.manifest_url", "")

        if not enabled:
            return {"enabled": False, "status": "disabled",
                    "current_version": self.current_version,
                    "message": "Update checks are turned off in Settings → Updates."}
        if not manifest_url:
            return {"enabled": True, "status": "not_configured",
                    "current_version": self.current_version,
                    "message": "No update manifest configured "
                               "(Settings → Updates → manifest URL)."}
        try:
            raw = await self.fetcher(manifest_url)
            manifest = json.loads(raw)
        except json.JSONDecodeError:
            return {"enabled": True, "status": "unavailable",
                    "current_version": self.current_version,
                    "message": "Update manifest is not valid JSON."}
        except Exception as exc:
            return {"enabled": True, "status": "unavailable",
                    "current_version": self.current_version,
                    "message": f"Could not reach the update server ({exc}). "
                               f"NOVA keeps working offline."}

        latest = str(manifest.get("version", "")).strip()
        if not latest:
            return {"enabled": True, "status": "unavailable",
                    "current_version": self.current_version,
                    "message": "Update manifest has no version field."}

        info = UpdateInfo(latest_version=latest,
                          url=str(manifest.get("url", "")),
                          notes=str(manifest.get("notes", "")),
                          released_at=str(manifest.get("released_at", "")))
        if is_newer(latest, self.current_version):
            return {"enabled": True, "status": "available",
                    "current_version": self.current_version,
                    "update": info.as_dict(),
                    "message": f"NOVA {latest} is available. Install it from "
                               f"Settings → Updates when you are ready — "
                               f"NOVA never installs updates silently."}
        return {"enabled": True, "status": "up_to_date",
                "current_version": self.current_version,
                "message": f"NOVA {self.current_version} is up to date."}

    # ------------------------------------------------------------------
    async def request_install(self) -> dict[str, Any]:
        """'Install now' — deliberately NOT automatic (spec §54)."""
        status = await self.check()
        if status.get("status") != "available":
            return {"started": False,
                    "message": "No update is available to install."}
        upd = status.get("update", {})
        return {"started": False, "manual": True,
                "download_url": upd.get("url", ""),
                "message": "NOVA never installs updates silently. Download the "
                           "installer from the link and run it, or connect an "
                           "updater service in Settings → Updates."}

    @staticmethod
    async def _default_fetcher(url: str) -> str:
        import asyncio
        import urllib.request

        def _get() -> str:
            from urllib.parse import urlparse
            if urlparse(url).scheme not in ("http", "https"):
                raise ValueError("update manifest must use http(s)")
            req = urllib.request.Request(  # noqa: S310  (scheme validated above)
                url, headers={"User-Agent": "NOVA-updater"})
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
                return resp.read().decode("utf-8", "replace")

        return await asyncio.to_thread(_get)
