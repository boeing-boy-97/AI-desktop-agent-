# NOVA — Neural Operating & Voice Automation Assistant

> A lightweight, futuristic **Windows desktop AI voice agent**.
> Press a floating orb (or a global shortcut), speak one natural-language
> command, and NOVA understands → plans → executes → observes → verifies →
> reports — recovering from common errors along the way.

![status](https://img.shields.io/badge/status-V2%20validated-brightgreen)
![tests](https://img.shields.io/badge/tests-175%20passing-green)
![acceptance](https://img.shields.io/badge/acceptance-28%2F28-green)
![health](https://img.shields.io/badge/health%20score-100%2F100-green)
![python](https://img.shields.io/badge/python-3.10%2B-blue)

**V2 — Ultra-Elite Production Upgrade.** NOVA V2 adds a formal 14-state agent
state machine, a multi-task queue with pause/resume/cancel, rollback +
"undo the last thing", session context with expiring approvals, risk-tiered
confirmations, prompt-injection defenses, a health-score engine, developer
commands, and a hardened localhost API. See
[docs/V2_AUDIT_AND_PLAN.md](docs/V2_AUDIT_AND_PLAN.md) for the audit and
[docs/architecture.md](docs/architecture.md) for the design.

---

## What it is

NOVA is a small always-on-top assistant "living" on your desktop — **not** a
chat website and **not** a Chrome extension. The optional browser extension is
only a companion for browser-specific automation.

![NOVA orb preview](docs/screenshots/orb-preview.png)

```
        [ NOVA ○ ]          ← floating orb, always on top, draggable
             │
   click → talk / type
             │
"Open VS Code, create a React project called NovaDemo, add a modern landing
 page, install dependencies, run it, fix any errors and open it in Chrome."
             │
   NOVA plans → executes tools → verifies → recovers → speaks: "The project is running."
```

---

## Features

- **Floating orb** — tiny, translucent, draggable, multi-monitor aware, DPI
  aware, remembers position, idle/listening/processing/speaking animations,
  hide-for-1-hour, snap options.
- **Compact command panel** — mic button, text input, live task/step status,
  stop button. No giant chat window.
- **System tray** — Activate / Pause / Resume / Settings / History /
  Permissions / Diagnostics / Restart / Exit.
- **Voice pipeline** — push-to-talk + click-to-talk (+ wake-word hook), VAD,
  faster-whisper STT, pluggable TTS (pyttsx3 / Kokoro / Piper), interruption.
- **Agent brain** — Planner / Executor / Observer / Verifier / Memory /
  ToolRegistry / PermissionManager / ErrorRecovery / TaskManager state machine.
- **V2 runtime** — formal 14-state machine with invalid-transition protection,
  multi-task queue (single-flight computer control), pause/resume/cancel,
  rollback journal ("Undo the last thing"), session context with expiring
  approvals, bounded self-healing recovery, truthful file-change summaries.
- **96 tools** in 12 categories: computer, filesystem, process/shell, browser,
  windows, vscode, whatsapp, downloads, web, memory, aliases, introspection +
  core-control (developer commands).
- **Coding / Build mode** — scaffold, write files, install deps, run, read
  errors, fix, restart, open — verified on the real filesystem.
- **Screen understanding** — ScreenObserver (screenshot/OCR/active-window),
  before/after verification.
- **Safety** — default-deny for risky actions, confirmations, dangerous-command
  & path validation, recycle-bin deletes, **emergency stop (Ctrl+Alt+X)**,
  audit logs.
- **Local + cloud AI** — OpenAI-compatible, Ollama, mock/demo. Keys from env
  only, never persisted.
- **Memory & workflows** — "My college projects are in D:\College\Projects",
  "Start College Mode" macros with `{name}` variables ("make a note called
  Report from Rahul" fills `{name}`/`{contact}` from what you said),
  conditions, delays and retries.
- **Update checker** — report-only version checks; NOVA never installs
  updates silently (Settings → Updates).
- **Developer dashboard** — live events, task plans, tools, diagnostics,
  self-repair loop, DEBUG MODE.

---

## Architecture

See **[docs/architecture.md](docs/architecture.md)** for the full diagram and
design rationale.

```
nova-agent/
├── apps/
│   ├── desktop/            # Qt floating orb, panel, tray, settings, history
│   └── browser-extension/  # MV3 companion (page context ⇄ tab commands)
├── backend/
│   ├── api/                # FastAPI routes + SSE + dashboard serving
│   ├── agent/              # TaskManager, Executor, Verifier, Memory, store
│   ├── planner/            # Intelligent (LLM) + heuristic planners
│   ├── executor/           # (via agent/executor.py)
│   ├── observer/           # ScreenObserver
│   ├── verifier/           # (via agent/verifier.py)
│   ├── memory/             # (via agent/memory.py)
│   ├── permissions/        # PermissionManager + emergency stop
│   ├── workflows/          # sequential/parallel workflow engine
│   ├── providers/          # ai / stt / tts / browser
│   ├── database/           # SQLAlchemy + SQLite models
│   ├── core/               # config, shell safety, logging, utils
│   ├── diagnostics/        # runtime checks + self-repair
│   ├── dashboard/          # developer dashboard (served by the API)
│   ├── main.py             # backend entrypoint
│   └── runtime.py          # composition root
├── tools/                  # 96 tool plugins (the registry discovers these)
├── tests/                  # unit + integration (158 tests)
├── scripts/                # dev setup, checks, acceptance.py, health_score.py,
│                           # Windows build
├── installer/              # install.ps1 + PyInstaller spec
├── docs/                   # architecture
├── .env.example            # configuration template
└── requirements*.txt
```

---

## Requirements

- **Windows 10/11** (primary target; macOS/Linux supported in degradable mode)
- **Python 3.10+**
- A microphone (for voice); optional Playwright/Chromium (for browser
  automation); optional VS Code + `code` on PATH.

---

## Installation

### From source

```powershell
git clone <repo> nova-agent
cd nova-agent
python scripts/dev_setup.py --with-desktop        # venv + deps + DB init
```

### Windows installer

```powershell
powershell -ExecutionPolicy Bypass -File .\installer\install.ps1
```

Installs to `%LOCALAPPDATA%\NOVA`, creates shortcuts and optional autostart.

### Standalone executables

```powershell
python -m pip install -r requirements-desktop.txt pyinstaller
python scripts/build_windows_exe.py all
# → dist\NovaBackend.exe, dist\NovaDesktop.exe
```

---

## Development setup

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-desktop.txt
```

## Environment variables (see `.env.example`)

| Variable           | Purpose                       | Default                    |
|--------------------|-------------------------------|----------------------------|
| `AI_PROVIDER`      | openai / ollama / mock        | openai                     |
| `OPENAI_API_KEY`   | cloud API key (never stored)  | —                          |
| `OPENAI_BASE_URL`  | any /v1-compatible endpoint   | https://api.openai.com/v1  |
| `OPENAI_MODEL`     | model name                    | gpt-4o-mini                |
| `OLLAMA_BASE_URL`  | local Ollama                  | http://127.0.0.1:11434     |
| `OLLAMA_MODEL`     | local model                   | llama3.1                   |
| `STT_PROVIDER`     | faster-whisper / mock         | faster-whisper             |
| `STT_MODEL`        | tiny/base/small/medium/large  | base                       |
| `TTS_PROVIDER`     | pyttsx3 / kokoro / piper / none | pyttsx3                 |
| `DATABASE_URL`     | SQLAlchemy URL                | sqlite (auto)              |
| `LOG_LEVEL`        | logging level                 | INFO                       |
| `NOVA_API_TOKEN`   | auth token for localhost API  | auto-generated (data dir)  |

---

## How to run

```powershell
# 1. backend (from repo root)
python -m backend.main --port 8765
#    …or: cd backend && uvicorn main:app --port 8765

# 2. desktop UI (second terminal)
python -m apps.desktop.main
```

The **developer dashboard** is served at `http://127.0.0.1:8765/dev` with the
backend running (API docs at `/docs`, real-time SSE at `/api/events/stream`).

> Headless UI smoke test (CI): `set NOVA_QT_OFFSCREEN=1 && python -m apps.desktop.main --check`

---

## How to configure Whisper

```powershell
pip install faster-whisper
set STT_MODEL=base          # first run downloads weights (~140 MB)
```

## How to configure TTS

- **Windows**: `pyttsx3` uses SAPI voices out of the box.
- **Kokoro/Piper**: set `TTS_PROVIDER=kokoro` (or `piper`) and `TTS_CLI`/`TTS_MODEL`
  to the installed binary path — the `CliFileTTS` provider renders + plays WAV.

## How to configure AI

- **Cloud**: `set OPENAI_API_KEY=sk-…` (or edit `.env.example` → `.env`).
- **Local**: install Ollama, `ollama pull llama3.1`, set `AI_PROVIDER=ollama`.
- **Offline/demo**: set `AI_PROVIDER=mock` — the deterministic heuristic
  planner drives real tools without any model.

---

## Running tests

```powershell
cd backend
python -m pytest -q              # 158 tests (unit + integration + API)

# from repo root:
ruff check backend scripts       # static analysis (0 findings)
python scripts/acceptance.py     # 28 end-to-end acceptance scenarios
python scripts/health_score.py   # engineering health report → health_report.json
```

> Dangerous/destructive operations are never tested automatically against real
> data — they run inside `tests/sandbox/` / temp dirs with confirmation gates.

### V2 API highlights

`/api/tasks/{id}/pause` · `/resume` · `/cancel` — task queue control ·
`/api/system/state_history` — agent state-machine audit trail ·
`/api/system/health_score` — live engineering health ·
`/api/system/startup_checks` — startup configuration validation ·
`/api/export` / `/api/import` — settings/workflows/memory/history backup ·
`/api/system/updates` — report-only update check (never auto-installs) ·
`/api/emergency_stop` — model-independent kill switch.
Token auth activates with `api.auth_enabled` + `NOVA_API_TOKEN`.

## Build installer

```powershell
python scripts/build_windows_exe.py all      # PyInstaller executables
pyinstaller installer/nova.spec              # backend spec
powershell -File installer/install.ps1       # install
```

---

## Example commands (demo mode included)

"Open Chrome." · "Open VS Code." · "Find my Downloads folder." ·
"Create a folder called AI Projects." · "Open my college project." ·
"Take a screenshot." · "Open WhatsApp." · "Open Rahul's chat." ·
"Download the latest photo." · "Build a complete React portfolio." ·
"Run the project." · "Fix the errors." · "Search the web for AI news." ·
"Start work mode." · "Stop everything."

Follow-ups use **conversational memory** — after "Open Rahul's chat." you can
say "Download the latest photo." and NOVA keeps the context.

---

## Permissions & security

- Tools declare **low / medium / high** risk; decisions: **ask once / allow for
  session / always allow / deny** per tool.
- Sending messages, deleting files, terminating processes, shutdown/restart
  always ask.
- Shell commands pass through a **controlled execution layer** with dangerous
  pattern detection; filesystem paths validated against protected areas.
- Secrets redacted from logs; screenshots/audio never uploaded silently.
- **Emergency stop**: `Ctrl+Alt+X` or the tray/orb menu.

## Privacy

NOVA distinguishes local vs cloud processing (cloud toggle in settings),
never stores API keys, and lets you delete task history, clear memory and
disable screenshots.

---

## WhatsApp setup

1. Install WhatsApp Desktop (optional — WhatsApp Web is the automatic
   fallback) and log in once.
2. NOVA opens the chat via `wa.me` deep links / WhatsApp Web and locates media
   in the local WhatsApp folders.
3. Sending messages builds the message then **always asks** for confirmation
   (unless explicitly disabled). NOVA never stores passwords or bypasses
   authentication.

## VS Code setup

Install VS Code and add the CLI — **Terminal → Install 'code' command in PATH**.
NOVA then drives it via `code`, direct file writes and terminal commands
(build/run/fix flows use the same tool paths on real projects).

## Browser extension setup

`chrome://extensions` → Developer mode → **Load unpacked** →
`apps/browser-extension`. It bridges page context/selection to NOVA over the
local API (127.0.0.1 only). See `apps/browser-extension/README.md`.

## Adding a custom tool

Create `backend/tools/spotify.py`:

```python
from tools.base import Tool, ToolResult, PermissionLevel
from pydantic import BaseModel

class PlayTrackIn(BaseModel):
    track: str

class PlayTool(Tool):
    name = "spotify.play"
    category = "spotify"
    permission = PermissionLevel.MEDIUM
    description = "Play a track."
    input_model = PlayTrackIn

    async def run(self, args, task_id=None) -> ToolResult:
        return ToolResult.ok({"playing": args.track})
```

Register it in `tools/__init__.py::_BUILTIN_MODULES` (or drop a module in the
`tools/` package — discovery walks the package). Add a `plugins/spotify/`
folder for bundled assets if needed.

---

## Known platform limitations

- **Windows is the primary OS.** Mac/Linux run the backend, agent, tools and
  voice (with degradations); UI-automation/window-tools use best-effort
  backends.
- **WhatsApp** has no official automation API — NOVA uses deep links + Web +
  local media folders; some in-app gestures need a visible session.
- **system.volume / brightness** report "pycaw/display API required" when the
  optional packages aren't installed (documented, not silent).
- **OCR** is optional (rapidocr/pytesseract); the observer works without it.
- **Browser automation** requires Playwright + Chromium (`playwright install chromium`).

## Troubleshooting

| Symptom                          | Fix                                                            |
|----------------------------------|----------------------------------------------------------------|
| Backend not reachable            | start `python -m backend.main --port 8765` first               |
| No STT                            | `pip install faster-whisper`, set `STT_PROVIDER=faster-whisper`|
| No TTS sound                      | `pip install pyttsx3` (or set `TTS_PROVIDER=none` for silent)  |
| AI errors                          | set `OPENAI_API_KEY` or switch `AI_PROVIDER=ollama`/`mock`     |
| No mic in UI                      | `pip install sounddevice` (or pyaudio)                          |
| "code not found"                  | install VS Code + add `code` to PATH                            |
| UI won't start (Linux headless)  | `sudo apt install libxkbcommon0 libgl1` (offscreen Qt deps)     |

---

## License

Provided as a reference implementation. Configure API providers per their
terms.
