"""NOVA desktop app entrypoint.

Usage::

    python -m apps.desktop.main [--base-url http://127.0.0.1:8765]

Set ``NOVA_QT_OFFSCREEN=1`` for headless startup checks (CI).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# make repository imports work regardless of cwd
_ROOT = Path(__file__).resolve().parents[2]      # nova-agent/
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# backend package access (for settings defaults when API is down)
_BACKEND = _ROOT / "backend"
if _BACKEND.exists() and str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def main() -> int:
    parser = argparse.ArgumentParser(description="NOVA desktop UI")
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--check", action="store_true",
                        help="smoke-test UI startup (off-screen) then exit")
    args = parser.parse_args()

    if args.check or os.environ.get("NOVA_QT_OFFSCREEN") == "1":
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import QApplication

    from apps.desktop.controller import NovaController

    app = QApplication(sys.argv)
    app.setApplicationName("NOVA")
    app.setOrganizationName("NovaAI")

    controller = NovaController(base_url=args.base_url, app=app)
    controller.apply_theme()
    controller.orb.show()
    controller.orb.raise_()

    if args.check or os.environ.get("NOVA_QT_OFFSCREEN") == "1":
        # headless smoke test: construct everything, verify widget tree, exit 0
        from PyQt6.QtCore import QTimer
        ok = {"result": False}

        def _finish():
            # orb + panel are mandatory; the tray is optional (headless/offscreen
            # sessions may legitimately have no system tray).
            ok["result"] = (controller.orb is not None
                            and controller.panel is not None)
            QApplication.instance().quit()

        QTimer.singleShot(800, _finish)
        app.exec()
        print("UI smoke check:", "OK" if ok["result"] else "FAILED")
        return 0 if ok["result"] else 1

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
