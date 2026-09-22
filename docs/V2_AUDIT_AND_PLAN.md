# NOVA V2 — Audit & Upgrade Plan

Audit date: 2026-09-21 · Basis: full repository inspection (93 .py, 16 .js files).

## 1. What already exists and works (REUSE — do not rebuild)

| Subsystem | Location | Verdict |
|---|---|---|
| FastAPI API (32 routes, SSE, OpenAPI tags, health) | `api/app.py` | solid |
| Task orchestration, confirmation loop, retries | `agent/task_manager.py` | solid, extended in V2 |
| Executor w/ per-step verify hook, permission gating | `agent/executor.py` | solid |
| Verifier (file existence, exit codes) | `agent/verifier.py` | extended in V2 |
| ScreenObserver (screenshot, OCR, windows) | `observer/screen.py` | extended in V2 |
| PermissionManager (risk levels, toggles, remember policy) | `permissions/manager.py` | solid |
| Heuristic + production planners, untrusted-model gating | `planner/` | extended in V2 |
| Schema-driven ToolRegistry, 40+ tools, 12 modules | `tools/` | extended in V2 |
| MemoryContext (facts, @placeholders, conversation) | `agent/memory.py` | extended in V2 |
| WorkflowEngine (conditions, variables, retries) | `workflows/engine.py` | solid |
| VoicePipeline (VAD, mic, barge-in hooks), STT/TTS providers | `voice/`, `providers/` | solid |
| EventBus + SSE bridge | `events/`, `api/app.py` | solid |
| SQLite/SQLAlchemy, migration_status, interrupted-task reaping | `database/` | solid |
| Diagnostics + self-repair | `diagnostics/` | solid |
| Dashboard SPA, PySide6 desktop app, MV3 extension, installer | `dashboard/`, `apps/`, `installer/` | solid |

No fake/mock production paths found. All `NotImplementedError` raises are abstract
interface contracts. 84 tests pass, ruff clean, 20/20 acceptance (pre-V2 baseline).

## 2. Gaps found during audit → V2 work items

| # | Spec § | Gap (evidence) | Fix |
|---|---|---|---|
| G1 | §5 | `_set_state` only checks state membership — no transition legality | `agent/state_machine.py`: explicit TRANSITIONS table, invalid-transition protection, from→to events |
| G2 | §30/31 | Tasks start immediately; `_active_task` overwritten by concurrent submits; no pause/resume | TaskManager queue + single-flight gate + `pause/resume` + `/api/tasks/{id}/pause|resume` |
| G3 | §13/§21 | No rollback, no checkpoints, no "undo the last thing" | `agent/undo.py` UndoJournal + filesystem tools record ops + `undo.last` tool + planner branch + change stats (§47) |
| G4 | §12/§23 | Retry loop has no failure classification or alternative strategy; no error analyzer | `agent/recovery.py` classifier + `agent/error_analyzer.py` structured error parsing |
| G5 | §16/§17 | No structured session state, no TTL expiry, no pronoun coreference | `agent/session.py` SessionContext + planner coreference resolution |
| G6 | §56 | No API auth; any LAN client could call tools | `api/auth.py` bearer-token middleware (opt-in via `NOVA_API_TOKEN`), production entry stays 127.0.0.1 |
| G7 | §44/§45 | No explicit untrusted-content firewall | `core/untrusted.py` + planner contract (only user text plans) + injection tests |
| G8 | §66 | No startup configuration validation | `core/startup_check.py` actionable checks, surfaced in `/api/system/status` |
| G9 | §59 | No introspection/developer commands | `tools/introspection.py` + planner branches ("show plan/tasks/logs/errors/tools/memory", "clear memory", "run diagnostics") |
| G10 | §10/§11 | No structured before/after change observation | `observer/changes.py` ChangeDetector (fs diff + screen fingerprint), wired into Verifier + `SCREEN_UPDATED` events |
| G11 | §68 | No export/restore | `/api/export`, `/api/import` (settings, workflows, memory, tasks) |
| G12 | §64 | No project health score | `scripts/health_score.py` + `/api/system/health_score` |
| G13 | §40 | SSE has client-side reconnect but no server heartbeat | 15s heartbeat events |

## 3. Environment limitations (documented, graceful fallbacks — not placeholders)

- Linux sandbox: Windows-only tools (`windows.*`, UIA), WhatsApp Desktop, microphone
  capture, PyInstaller Windows exe cannot execute here. All degrade with actionable
  errors (established project pattern); packaging plan validated structurally.
- `OPENAI_API_KEY` absent → heuristic planner exercised (production planner covered
  by unit tests with stub providers).

## 4. Execution order

1. G1 state machine → integrate → test
2. G3 undo journal + filesystem recording + tool + test
3. G4 recovery + error analyzer → integrate → test
4. G2 queue/pause/resume → API → test
5. G5 session context + coreference → test
6. G6/G7/G8 security (auth, untrusted firewall, startup checks) → test
7. G9 introspection tools + planner branches → test
8. G10 change detector, G11 export/import, G12 health score, G13 heartbeat → test
9. Full regression: pytest + ruff + acceptance (extended) + live smoke
10. Packaging validation + final report
