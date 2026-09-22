# NOVA installer

## Windows installer script

```powershell
powershell -ExecutionPolicy Bypass -File .\installer\install.ps1
```

Behaviour:
1. installs to `%LOCALAPPDATA%\NOVA` (or `-InstallDir`)
2. copies prebuilt `dist\NovaBackend.exe` / `dist\NovaDesktop.exe` if present
3. creates a Start-Menu shortcut and an optional Run-at-login autostart entry
4. writes an `.env.example` template for AI/voice configuration

## Standalone executables (PyInstaller)

```powershell
python -m pip install pyinstaller
python scripts/build_windows_exe.py all      # → dist\NovaBackend.exe + dist\NovaDesktop.exe
```

or via spec file:

```powershell
pyinstaller installer/nova.spec
```

## Setup flow the user sees

1. Download installer → run `install.ps1`
2. Launch NOVA
3. Configure microphone (Windows Settings → Privacy → Microphone)
4. Select AI provider (cloud OpenAI key, or local Ollama, or mock/demo)
5. Grant required permissions (the permission panel asks before risky actions)
6. Click Finish
7. The floating NOVA orb appears on the desktop
