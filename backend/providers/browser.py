"""Browser engine abstraction.

    * Playwright (Chromium) — full automation: open, search, click, type, scroll,
      read text, downloads, uploads, screenshot. Used on real machines.
    * In-memory engine — a safe stand-in used by tests/CI: supports navigation
      to ``about:``/local pages and records interactions so the agent loop can
      be verified without driving a real browser.

Playwright is imported lazily so NOVA works without it for non-browser tasks.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.exceptions import NotAvailable, ProviderError


@dataclass
class BrowserState:
    url: str = ""
    title: str = ""
    text: str = ""
    loaded: bool = False
    download_path: str | None = None
    screenshot_path: str | None = None
    history: list = field(default_factory=list)


class BrowserEngine(ABC):
    @abstractmethod
    async def open(self, url: str, **kwargs) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def read_text(self) -> str:
        raise NotImplementedError

    async def click(self, selector: str) -> dict:
        raise NotAvailable("click not supported by this engine")

    async def type(self, selector: str, text: str) -> dict:
        raise NotAvailable("type not supported by this engine")

    async def screenshot(self, path: str) -> dict:
        raise NotAvailable("screenshot not supported by this engine")

    async def download(self, url: str, save_dir: str) -> dict:
        raise NotAvailable("download not supported by this engine")

    async def title(self) -> str:
        return ""

    async def start(self) -> None:
        return

    async def close(self) -> None:
        return


class PlaywrightEngine(BrowserEngine):
    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self._playwright = None
        self._browser = None
        self._page = None

    def _import(self):
        if self._playwright is None:
            try:
                from playwright.async_api import async_playwright
            except Exception as exc:
                raise NotAvailable(
                    "Playwright is not installed. Run: pip install playwright && "
                    f"playwright install chromium ({exc})") from exc
            self._playwright = async_playwright
        return self._playwright

    async def start(self) -> None:
        pw = self._import()
        self._pw = await pw().start()
        launch_kwargs: dict = {"headless": bool(self.settings.get_bool("browser.headless", True))}
        channel = self.settings.get_str("browser.channel", "")
        if channel:
            launch_kwargs["channel"] = channel
        try:
            self._browser = await self._pw.chromium.launch(**launch_kwargs)
        except Exception as exc:
            raise NotAvailable(f"Chromium launch failed: {exc}") from exc
        self._page = await self._browser.new_page()

    async def open(self, url: str, **kwargs) -> dict:
        if self._page is None:
            await self.start()
        await self._page.goto(url, wait_until="domcontentloaded", timeout=45000)
        title = await self._page.title()
        return {"url": url, "title": title, "opened": True}

    async def read_text(self) -> str:
        if self._page is None:
            return ""
        return await self._page.inner_text("body") or ""

    async def click(self, selector: str) -> dict:
        if self._page is None:
            raise ProviderError("browser not started")
        await self._page.click(selector, timeout=15000)
        return {"clicked": selector}

    async def type(self, selector: str, text: str) -> dict:
        if self._page is None:
            raise ProviderError("browser not started")
        await self._page.fill(selector, text)
        return {"typed": selector, "length": len(text)}

    async def screenshot(self, path: str) -> dict:
        if self._page is None:
            raise ProviderError("browser not started")
        await self._page.screenshot(path=path, full_page=False)
        return {"path": path, "captured": True}

    async def download(self, url: str, save_dir: str) -> dict:
        if self._page is None:
            raise ProviderError("browser not started")
        Path(save_dir).mkdir(parents=True, exist_ok=True)
        # navigate directly for asset downloads
        resp = await self._page.goto(url, wait_until="load", timeout=60000)
        body = await resp.body() if resp else None
        if body is None:
            raise ProviderError("empty download response")
        name = url.rstrip("/").split("/")[-1] or "download.bin"
        dest = Path(save_dir) / name
        dest.write_bytes(body)
        return {"path": str(dest), "size": len(body), "downloaded": True}

    async def title(self) -> str:
        return (await self._page.title()) if self._page else ""

    async def close(self) -> None:
        try:
            if self._browser:
                await self._browser.close()
            if getattr(self, "_pw", None):
                await self._pw.stop()
        except Exception:
            pass
        self._browser = None
        self._page = None
        self._playwright = None


class InMemoryEngine(BrowserEngine):
    """Deterministic engine for tests/demos. Documents itself via history."""

    def __init__(self, settings: Any, pages: dict | None = None) -> None:
        self.settings = settings
        self.pages = pages or {
            "https://example.com": "Example Domain body text for testing",
            "https://news.example.com/ai": "AI news: new models released today",
            "about:blank": "",
        }
        self.state = BrowserState()

    async def open(self, url: str, **kwargs) -> dict:
        self.state.history.append({"action": "open", "url": url})
        self.state.url = url
        self.state.loaded = True
        self.state.title = url.rstrip("/").split("/")[-1] or "page"
        self.state.text = self.pages.get(url, "")
        return {"url": url, "title": self.state.title, "opened": True,
                "engine": "in-memory"}

    async def read_text(self) -> str:
        self.state.history.append({"action": "read", "url": self.state.url})
        return self.state.text

    async def click(self, selector: str) -> dict:
        self.state.history.append({"action": "click", "selector": selector})
        return {"clicked": selector, "engine": "in-memory"}

    async def type(self, selector: str, text: str) -> dict:
        self.state.history.append({"action": "type", "selector": selector, "text": text})
        return {"typed": selector}

    async def download(self, url: str, save_dir: str) -> dict:
        dest = Path(save_dir) / ("download-" + url.rstrip("/").split("/")[-1] or "file.bin")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"NOVA in-memory download fixture")
        self.state.download_path = str(dest)
        self.state.history.append({"action": "download", "url": url, "path": str(dest)})
        return {"path": str(dest), "size": dest.stat().st_size, "downloaded": True,
                "engine": "in-memory"}

    async def screenshot(self, path: str) -> dict:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"fake-png")
        self.state.screenshot_path = path
        self.state.history.append({"action": "screenshot", "path": path})
        return {"path": path, "captured": True, "engine": "in-memory"}

    async def title(self) -> str:
        return self.state.title

    async def close(self) -> None:
        pass


def create_browser_engine(settings: Any, *, force_inmemory: bool = False) -> BrowserEngine:
    engine = settings.get_str("browser.engine", "playwright")
    if force_inmemory or engine in ("mock", "memory", "in-memory"):
        return InMemoryEngine(settings)
    return PlaywrightEngine(settings)
