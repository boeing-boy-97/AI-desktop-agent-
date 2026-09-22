# NOVA — Architecture (V2)

## V2 runtime layers

```
Desktop Layer (PySide6 orb/panel/tray)
      ↓
Voice Layer (VAD → faster-whisper STT → intent; interrupts STOP/CANCEL/ABORT)
      ↓
Agent Runtime (runtime.py — composition root; context, task id, retries,
               session context, cancellation state)
      ↓
Planner (heuristic deterministic / LLM structured intentions — UNTRUSTED
         producer; can only pick whitelisted tools)
      ↓
Policy / Permissions (risk tiers SAFE→CRITICAL, allow/ask/deny,
                      session approvals, confirmations)
      ↓
Tool Registry (96 schema-driven tools: input_schema, risk, timeout,
               retry, verify(), rollback())
      ↓
Tool Execution (ControlledShell, path safety, resource locks)
      ↓
Computer Observation (screen/filesystem/process state diffs)
      ↓
Verification (no evidence ⇒ no success claim)
      ↓
Memory / Context (segmented memory, expiring session context, secrets blocked)
      ↓
Task State (14-state machine with invalid-transition protection)
      ↓
User Feedback (SSE events + heartbeat → dashboard / desktop / extension)
```

## System overview

```
                    ┌─────────────────────────────────────────────┐
                    │            DESKTOP UI (PySide6/PyQt6)       │
                    │  floating orb · command panel · tray ·      │
                    │  settings · history · hotkeys               │
                    └───────────────┬─────────────────────────────┘
                                    │ HTTP + SSE (127.0.0.1:8765)
                    ┌───────────────▼─────────────────────────────┐
                    │              FASTAPI BACKEND                │
                    │  ┌───────────────────────────────────────┐  │
                    │  │          AGENT BRAIN                  │  │
                    │  │ Planner → Executor → Observer →       │  │
                    │  │ Verifier → Recovery (TaskManager)     │  │
                    │  └──────────┬────────────────────────────┘  │
                    │             │                                │
                    │  ┌──────────▼────────────┐  ┌─────────────┐  │
                    │  │    TOOL REGISTRY      │  │ PERMISSIONS │  │
                    │  │ computer.* filesystem.* │  │ (allow/ask/ │  │
                    │  │ browser.*  whatsapp.*   │  │  deny) +    │  │
                    │  │ vscode.*   process.*    │  │ EMERGENCY   │  │
                    │  │ shell (controlled)      │  │ STOP latch  │  │
                    │  └──────────┬────────────┘  └─────────────┘  │
                    │             │                                │
                    │  ┌──────────▼────────────┐  ┌─────────────┐  │
                    │  │ PROVIDERS             │  │ SQLAlchemy/ │  │
                    │  │ AI(openai/ollama)     │  │ SQLite DB   │  │
                    │  │ STT(faster-whisper)   │  │  (memory,   │  │
                    │  │ TTS(pyttsx3/kokoro)   │  │  tasks...)  │  │
                    │  │ browser(playwright)   │  └─────────────┘  │
                    │  └───────────────────────┘                   │
                    └───────────────┬─────────────────────────────┘
                                    │
              ┌─────────────────────┼──────────────────────┐
              ▼                     ▼                       ▼
      Computer Control        Browser (Playwright)   Browser Extension
      (mouse/key/window     (open/search/click/     (MV3 companion:
       /apps via            download)                page context + tab
       pyautogui +                                     commands to NOVA)
       UI Automation)
```

## Data flow of a voice command

```
 mic → VAD → STT (faster-whisper) → intent text
     → Planner (AI tool-calling or deterministic heuristic)
     → TaskManager (state machine)
     → Executor (permission gate → tool run → verification)
     → error recovery (classify → retry/repair)
     → summary → TTS + compact status
```

## Key design decisions

1. **Method preference (spec §54)** — official APIs → direct app interfaces →
   filesystem/system APIs → UI automation → browser automation → raw
   mouse/keyboard. VS Code is driven via its CLI + direct file writes, not by
   clicking menus; file ops go through the filesystem tool, not simulated
   typing.

2. **LLM is an untrusted planner (spec §29)** — every shell command passes
   through `core/shell.py` (`ControlledShell`) with a `DangerousCommandDetector`;
   every filesystem path through `core/safety.py`. The model can only select
   tools from the registry's whitelist.

3. **Permission system (spec §15, §53)** — tools declare low/medium/high risk.
   Decisions resolve as allow / ask / deny from a per-tool persisted rule →
   session rule → risk tier. High-risk tools (delete, send_message, shutdown,
   process.stop) always ask. The global **emergency stop** latch is checked
   before every step.

4. **Single-flight execution + V2 queue** — `TaskManager` runs one task at a
   time; additional tasks queue FIFO with pause/resume/cancel at execution
   gates. Voice interrupts ("stop everything") take a fast path that cancels
   the busy task synchronously instead of queueing behind it. The 14-state
   machine (`agent/state_machine.py`) guards every transition, emits an event
   per change, and keeps a queryable history (`/api/system/state_history`).

5. **Rollback & undo** — `agent/undo.py` keeps a journal with
   snapshot-before-write so "undo the last thing" restores files; every task
   records a truthful `changes` summary (created/modified/deleted/moved).

6. **Security posture** — `core/untrusted.py` treats webpage/file content as
   data (prompt-injection defense), `api/auth.py` adds token middleware,
   `/actions/{tool}` is locked behind `developer.direct_actions`, and the
   health-score engine (`scripts_lib.py` + `scripts/health_score.py`) reports
   test/lint/import/security/startup coverage without hiding failures.

7. **Providers everywhere (spec §16–17)** — AI (openai/ollama/mock), STT
   (faster-whisper/mock), TTS (pyttsx3/kokoro/piper/none), browser
   (playwright/in-memory). No provider is hard-coded into the core.

8. **Graceful platform fallbacks (spec §58)** — when a capability is unavailable
   on the current machine (WhatsApp Desktop absent, no display, no Playwright),
   tools return structured results and the agent recovers or documents the
   limitation rather than failing hard. Startup checks (`core/startup_check.py`)
   treat any optional-import failure as informational — NOVA never crashes on
   boot because a microphone or codec library is missing.

9. **Workflows & updates** — the workflow engine supports `{name}` variables,
   conditions, delays and retries; the update checker (`core/updater.py`)
   reports version availability only — it never downloads or installs silently.

## Module map

| Module                              | Responsibility                                        |
|-------------------------------------|-------------------------------------------------------|
| `core/config.py`                    | Settings (env → defaults), secrets never persisted    |
| `core/shell.py` + `core/safety.py`  | Controlled subprocess + dangerous-command/path checks |
| `database/`                         | SQLAlchemy engine, models, service layer              |
| `permissions/`                      | PermissionManager, ConfirmationStore, EmergencyStop   |
| `providers/`                        | ai, stt, tts, browser engines                         |
| `observer/screen.py`                | ScreenObserver (screenshots/OCR/active window)        |
| `agent/`                            | TaskManager, Executor, Verifier, Memory, errors, store, **state_machine, session, undo, recovery, error_analyzer** |
| `planner/`                          | IntelligentPlanner + HeuristicPlanner (session + dev commands + workflow variables) |
| `tools/`                            | 96 tools as plugins (incl. `introspection`, `core_control`) |
| `workflows/engine.py`               | Sequential/parallel workflow engine with retries, conditions, delays, `{variables}` |
| `voice/pipeline.py`                 | mic → VAD → STT → TTS pipeline                        |
| `api/app.py` + `api/auth.py`        | FastAPI routes + SSE heartbeat + token middleware + dashboard |
| `core/untrusted.py`, `core/locks.py`, `core/startup_check.py`, `core/updater.py` | prompt-injection defense, resource locks, boot validation, update checker |
| `scripts_lib.py`                    | health-score engine (tests/lint/imports/security/startup) |
| `runtime.py`                        | Composition root wiring everything together (+ crash-recovery reaping of stale tasks) |
| `apps/desktop/`                     | Qt orb, panel, tray, settings, history, hotkeys       |
| `apps/browser-extension/`           | MV3 companion extension                               |

## Threading model

- The FastAPI app is async (uvicorn). CPU-heavy inference (whisper) and TTS run
  in worker threads/executors, never on the UI thread.
- The desktop UI is a single Qt main thread; backend calls run in background
  threads (`threading.Thread`) and results are marshalled back via Qt signals;
  the SSE stream arrives on a dedicated daemon thread.
- The orb stays lightweight: a 33 ms paint timer only runs while listening/
  processing, idle CPU is near zero.
