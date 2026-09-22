"""Tiny development proxy.

Serves:
    * the NOVA FastAPI backend on one port
    * the developer dashboard at / (same origin → SSE works)
    * the browser-extension popup preview at /extension

Binds 0.0.0.0 so container previews work; points the preview origin at the
backend host instead of localhost (the frontend uses relative URLs anyway).
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from api.app import build_app
from core.config import settings
from core.logging_config import setup_logging
from runtime import Runtime


def main() -> None:
    setup_logging("INFO", log_dir=settings.data_dir / "logs")
    runtime = Runtime()
    app = build_app(runtime)

    from fastapi.responses import HTMLResponse, JSONResponse

    # HTML preview for the extension popup (so users can see it)
    ext_popup = (_ROOT.parent / "apps" / "browser-extension" / "popup" / "popup.html")
    ext_serve = _ROOT.parent / "apps" / "browser-extension"

    @app.get("/extension")
    async def extension_preview():
        if ext_popup.exists():
            return HTMLResponse(ext_popup.read_text(encoding="utf-8"))
        return HTMLResponse("<h3>Extension popup missing</h3>", 404)

    @app.get("/api/preview-source")
    async def preview_source():
        manifest = ext_serve / "manifest.json"
        return JSONResponse({
            "extension": {
                "manifest": manifest.read_text() if manifest.exists() else "",
            }
        })

    import uvicorn
    print("NOVA dev proxy on http://0.0.0.0:8765  (dashboard at /dev, "
          "extension popup at /extension)")
    uvicorn.run(app, host="0.0.0.0", port=8765, log_level="info")


if __name__ == "__main__":
    main()
