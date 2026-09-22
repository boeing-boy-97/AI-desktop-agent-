# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the NOVA backend executable (Windows).
# Build:  pyinstaller installer/nova.spec
from pathlib import Path

ROOT = Path(SPECPATH).parent.parent  # noqa: F821  (SPECPATH provided by PyInstaller)

a = Analysis(
    ["backend/main.py"],
    pathex=[str(ROOT / "backend"), str(ROOT)],
    binaries=[],
    datas=[(str(ROOT / "backend" / "dashboard"), "dashboard")],
    hiddenimports=[
        "sqlalchemy", "database.models",
        "tools.computer", "tools.filesystem", "tools.browser", "tools.whatsapp",
        "tools.vscode", "tools.windows", "tools.process_ctl", "tools.web_tools",
        "tools.downloads", "tools.alias", "tools.memory_tools", "tools._platform",
        "faster_whisper",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["PyQt6", "PyQt6-WebEngine", "pywinauto", "playwright"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="NovaBackend",
    debug=False,
    console=True,
    upx=False,
)
