"""NOVA backend entrypoint.

Starts the FastAPI server used by the desktop UI and the dashboard::

    python -m backend.main         (from repo root, or)
    uvicorn main:app --port 8765
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure the backend package is importable when run as a script.
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.config import settings
from core.logging_config import setup_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="NOVA backend API server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    # boot configuration from env before logging
    log_dir = settings.data_dir / "logs"
    setup_logging(args.log_level, log_dir=log_dir)

    from runtime import Runtime
    runtime = Runtime()

    from api.app import build_app
    app = build_app(runtime)

    import uvicorn
    print(f"NOVA API listening on http://{args.host}:{args.port} "
          f"(docs at /docs)")
    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload,
                log_level=args.log_level.lower())


if __name__ == "__main__":
    main()
