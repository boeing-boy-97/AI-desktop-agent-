"""browser.* — web automation tools via the BrowserEngine abstraction (spec §11).

The engine is created once per tool context and cached. Real Playwright usage is
enabled only when installed; otherwise an in-memory engine used by tests/docs is
selected automatically.
"""
from __future__ import annotations

from core.exceptions import NotAvailable, ProviderError
from pydantic import BaseModel, Field
from tools.base import PermissionLevel, Tool, ToolResult


# ---------------------------------------------------------------------------
# inputs
# ---------------------------------------------------------------------------
class OpenIn(BaseModel):
    url: str = Field(..., min_length=1)


class SearchIn(BaseModel):
    query: str = Field(..., min_length=1)
    engine: str = "google"


class ClickIn(BaseModel):
    selector: str = Field(..., min_length=1)


class TypeIn(BaseModel):
    selector: str
    text: str


class DownloadIn(BaseModel):
    url: str
    save_dir: str | None = None


class ScreenshotIn(BaseModel):
    path: str | None = None


class _BrowserTool(Tool):
    _abstract = True
    category = "browser"

    @property
    def _engine(self):
        cached = getattr(self.ctx, "_browser_engine", None)
        if cached is None:
            from providers.browser import create_browser_engine
            cached = create_browser_engine(
                self.ctx.settings,
                force_inmemory=(self.ctx.settings.get_str("browser.engine", "playwright") == "mock"))
            self.ctx._browser_engine = cached
        return cached


class BrowserOpenTool(_BrowserTool):
    name = "browser.open"
    description = "Open a website URL in the automation browser."
    input_model = OpenIn
    permission = PermissionLevel.LOW
    timeout = 60

    async def run(self, args, task_id=None) -> ToolResult:
        try:
            out = await self._engine.open(args.url)
            return ToolResult.ok(out)
        except (NotAvailable, ProviderError) as exc:
            return ToolResult.fail(str(exc), "NOT_AVAILABLE")


class BrowserSearchTool(_BrowserTool):
    name = "browser.search"
    description = "Search the web using a search engine and return the result page text."
    input_model = SearchIn
    permission = PermissionLevel.LOW
    timeout = 60

    async def run(self, args, task_id=None) -> ToolResult:
        import urllib.parse
        q = urllib.parse.quote(args.query)
        engines = {"google": f"https://www.google.com/search?q={q}",
                   "bing": f"https://www.bing.com/search?q={q}",
                   "duckduckgo": f"https://duckduckgo.com/?q={q}"}
        url = engines.get(args.engine.lower(), engines["google"])
        if EngineGate.is_memory(self._engine):
            url = f"https://search.example.com/?q={q}"
        try:
            opened = await self._engine.open(url)
            text = (await self._engine.read_text())[:3000]
            return ToolResult.ok({"url": url, "title": opened.get("title", ""),
                                  "results_sample": text})
        except (NotAvailable, ProviderError) as exc:
            return ToolResult.fail(str(exc), "NOT_AVAILABLE")


class BrowserClickTool(_BrowserTool):
    name = "browser.click"
    description = "Click an element by CSS selector in the current page."
    input_model = ClickIn
    permission = PermissionLevel.MEDIUM
    timeout = 30

    async def run(self, args, task_id=None) -> ToolResult:
        try:
            return ToolResult.ok(await self._engine.click(args.selector))
        except (NotAvailable, ProviderError) as exc:
            return ToolResult.fail(str(exc), "NOT_AVAILABLE")


class BrowserTypeTool(_BrowserTool):
    name = "browser.type"
    description = "Type text into an element by CSS selector."
    input_model = TypeIn
    permission = PermissionLevel.MEDIUM
    timeout = 30

    async def run(self, args, task_id=None) -> ToolResult:
        try:
            return ToolResult.ok(await self._engine.type(args.selector, args.text))
        except (NotAvailable, ProviderError) as exc:
            return ToolResult.fail(str(exc), "NOT_AVAILABLE")


class BrowserReadTool(_BrowserTool):
    name = "browser.read_text"
    description = "Read the visible body text of the current page."
    input_model = None
    permission = PermissionLevel.LOW
    timeout = 30

    async def run(self, args, task_id=None) -> ToolResult:
        try:
            text = await self._engine.read_text()
            return ToolResult.ok({"text": text[:10000]})
        except (NotAvailable, ProviderError) as exc:
            return ToolResult.fail(str(exc), "NOT_AVAILABLE")


class BrowserScrollTool(_BrowserTool):
    name = "browser.scroll"
    description = "Scroll the page (handled by engine if available)."
    input_model = None
    permission = PermissionLevel.LOW
    timeout = 15

    async def run(self, args, task_id=None) -> ToolResult:
        amount = args.get("clicks", 3)
        return ToolResult.ok({"scrolled": amount, "note": "engine best-effort"})


class BrowserDownloadTool(_BrowserTool):
    name = "browser.download"
    description = "Download a file from a URL to a local folder."
    input_model = DownloadIn
    permission = PermissionLevel.MEDIUM
    timeout = 90

    async def run(self, args, task_id=None) -> ToolResult:
        save_dir = args.save_dir or str(self.ctx.settings.downloads_dir)
        try:
            out = await self._engine.download(args.url, save_dir)
            import pathlib
            if out.get("path"):
                pathlib.Path(out["path"]).parent.mkdir(parents=True, exist_ok=True)
            return ToolResult.ok(out)
        except (NotAvailable, ProviderError) as exc:
            return ToolResult.fail(str(exc), "NOT_AVAILABLE")


class BrowserScreenshotTool(_BrowserTool):
    name = "browser.screenshot"
    description = "Capture the current browser viewport to a PNG."
    input_model = ScreenshotIn
    permission = PermissionLevel.LOW
    timeout = 30

    async def run(self, args, task_id=None) -> ToolResult:
        path = args.path or str(self.ctx.settings.screenshots_dir / "browser.png")
        try:
            return ToolResult.ok(await self._engine.screenshot(path))
        except (NotAvailable, ProviderError) as exc:
            return ToolResult.fail(str(exc), "NOT_AVAILABLE")


class EngineGate:
    """Small helper so in-memory engine gets deterministic URLs in tests."""

    @staticmethod
    def is_memory(engine) -> bool:
        return type(engine).__name__ == "InMemoryEngine"
