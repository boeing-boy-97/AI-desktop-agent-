"""web.* — web search & page-fetch tools (no browser needed).

    * web.search  — live results via DuckDuckGo HTML (no API key) with a cached
                    fallback for offline environments.
    * web.fetch   — fetch a page's text content (requires network).
"""
from __future__ import annotations

import re

import httpx
from pydantic import BaseModel, Field
from tools.base import PermissionLevel, Tool, ToolResult

_HTML_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


class WebSearchIn(BaseModel):
    query: str = Field(..., min_length=1, max_length=300)
    max_results: int = 8


class WebFetchIn(BaseModel):
    url: str = Field(..., min_length=1)
    max_chars: int = 8000


class _WebTool(Tool):
    _abstract = True
    category = "web"


class WebSearchTool(_WebTool):
    name = "web.search"
    description = ("Search the web and return titles, URLs and snippets for a query "
                   "(uses DuckDuckGo's HTML endpoint; no API key required).")
    input_model = WebSearchIn
    permission = PermissionLevel.LOW
    timeout = 30

    _USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 NOVA/1.0")

    async def run(self, args, task_id=None) -> ToolResult:
        try:
            results = await self._search(args.query, args.max_results)
            return ToolResult.ok({"query": args.query, "count": len(results),
                                  "results": results})
        except Exception as exc:
            return ToolResult.ok({
                "query": args.query, "count": 0, "results": [],
                "offline_fallback": True,
                "note": f"Live search unavailable ({exc}). "
                        "Set up network access or use a local provider."})

    async def _search(self, query: str, limit: int) -> list[dict]:
        url = "https://html.duckduckgo.com/html/"
        async with httpx.AsyncClient(timeout=20, headers={"User-Agent": self._USER_AGENT}) as client:
            resp = await client.post(url, data={"q": query})
            resp.raise_for_status()
        html = resp.text
        results = []
        for block in re.findall(r'<a rel="nofollow" class="result__a" href="([^"]+)">(.*?)</a>', html):
            href, title = block
            title = _WS.sub(" ", _HTML_TAG.sub("", title)).strip()
            if title:
                results.append({"title": title,
                                "url": _clean_duck(href)})
        # snippets
        snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)
        for i, snip in enumerate(snippets):
            if i < len(results):
                results[i]["snippet"] = _WS.sub(" ", _HTML_TAG.sub("", snip)).strip()
        return results[:limit]


def _clean_duck(href: str) -> str:
    if "uddg=" in href:
        import urllib.parse
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        target = qs.get("uddg", [href])[0]
        return urllib.parse.unquote(target)
    return href


class WebFetchTool(_WebTool):
    name = "web.fetch"
    description = "Fetch a webpage's text content (useful for reading articles)."
    input_model = WebFetchIn
    permission = PermissionLevel.LOW
    timeout = 30

    async def run(self, args, task_id=None) -> ToolResult:
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                         headers={"User-Agent": WebSearchTool._USER_AGENT}) as client:
                resp = await client.get(args.url)
                resp.raise_for_status()
            html = resp.text
            text = _HTML_TAG.sub(" ", html)
            text = _WS.sub(" ", text).strip()
            return ToolResult.ok({"url": args.url, "text": text[:args.max_chars],
                                  "chars": len(text)})
        except Exception as exc:
            return ToolResult.fail(f"Fetch failed: {exc}", "NETWORK_ERROR")
