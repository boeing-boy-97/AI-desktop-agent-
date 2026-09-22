"""FastAPI application factory and route wiring.

The API is the single integration point for the desktop UI, the dashboard and
external callers. It exposes every endpoint required by spec §31 plus the
real-time event stream (§32).
"""
from __future__ import annotations

import asyncio
import base64
import json
import time

from core.exceptions import NovaError
from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from runtime import Runtime
from schemas.api_models import (
    CancelRequest,
    ConfirmRequest,
    ExecuteRequest,
    MemoryCreateRequest,
    PlanRequest,
    SettingsUpdateRequest,
    TaskCreateRequest,
    TranscribeRequest,
    WorkflowCreateRequest,
)


def _runtime(request) -> Runtime:
    return request.app.state.runtime


def error_response(exc: NovaError, status: int):
    return JSONResponse(status_code=status, content=exc.to_dict())


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(NovaError)
    async def _nova(request, exc: NovaError):
        status = 400
        if exc.code == "PERMISSION_DENIED":
            status = 403
        elif exc.code == "CONFIRMATION_REQUIRED":
            status = 409
        elif exc.code == "TOOL_NOT_FOUND":
            status = 404
        elif exc.code == "EMERGENCY_STOP":
            status = 423
        return error_response(exc, status)

    @app.exception_handler(HTTPException)
    async def _http(request, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code,
                            content={"code": "HTTP_ERROR", "message": str(exc.detail)})


def build_app(runtime: Runtime) -> FastAPI:
    app = FastAPI(
        title="NOVA Agent API",
        version="2.0.0",
        description=(
            "Local control-plane API for the NOVA desktop voice agent.\n\n"
            "Every natural-language command flows through the same pipeline: "
            "**planner → permission gate → executor → observer → verifier**, with "
            "real-time events published on `/api/events/stream` (SSE). The model "
            "is treated as an untrusted planner — all side effects pass through "
            "the tool/permission layer."),
        contact={"name": "NOVA Project"},
        license_info={"name": "MIT"},
    )
    app.state.runtime = runtime
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # local loopback + desktop widget origins
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)

    api = APIRouter(prefix="/api")

    # --------------------------------------------------------------
    # system
    # --------------------------------------------------------------
    @api.get("/health", tags=["system"],
             summary="Liveness probe",
             description="Returns immediately when the backend is up. Used by the "
                         "frontend, tray and diagnostics watchdogs.")
    async def health():
        return {"ok": True, "version": "2.0.0", "uptime_seconds": round(runtime.uptime(), 1)}

    @api.get("/system/status", tags=["system"], summary="Agent + provider status")
    async def system_status():
        return runtime.status()

    @api.get("/system/state_history", tags=["system"],
             summary="Recent agent state transitions (guarded state machine)")
    async def state_history(limit: int = Query(50, ge=1, le=200)):
        return {"state": runtime.state,
                "history": runtime.tasks.state_history(limit)}

    @api.get("/system/updates", tags=["system"],
             summary="Update availability check (§54 — report only)")
    async def updates_status():
        return await runtime.updater.check()

    @api.post("/system/updates/install", tags=["system"],
              summary="Request an update install (§54 — never silent)")
    async def updates_install():
        return await runtime.updater.request_install()

    @api.get("/system/session", tags=["system"],
             summary="Current conversational session context (V2 §17)")
    async def session_context():
        return runtime.session.describe()

    @api.get("/system/startup_checks", tags=["system"],
             summary="Startup configuration validation results (V2 §66)")
    async def startup_checks():
        return {"summary": runtime.startup_summary,
                "checks": runtime.startup_checks}

    @api.get("/system/health_score", tags=["system"],
             summary="Internal engineering health score (V2 §64)")
    async def health_score():
        import scripts_lib
        return scripts_lib.compute(runtime)

    # --------------------------------------------------------------
    # backup / restore (V2 §68)
    # --------------------------------------------------------------
    @api.get("/export", tags=["system"],
             summary="Export settings, workflows, memory and task history")
    async def export_bundle():
        from database.service import list_memory, list_workflows
        bundle = {"exported_at": time.time(), "version": "2.0.0"}
        if runtime.database.session_factory is not None:
            with runtime.database.session_factory() as s:
                bundle["memory"] = [{"key": m.key, "value": m.value,
                                     "category": m.category}
                                    for m in list_memory(s)]
                bundle["workflows"] = [{"name": w.name, "triggers": w.triggers,
                                        "steps": w.steps}
                                       for w in list_workflows(s)]
        # snapshot() masks secrets — exports never leak API keys (§33/§43)
        bundle["settings"] = runtime.settings.snapshot(include_secrets=False)
        bundle["tasks"] = runtime.store.list(limit=200)
        return bundle

    @api.post("/import", tags=["system"],
              summary="Restore memory/workflows/settings from an export bundle")
    async def import_bundle(body: dict):
        from database.service import save_workflow, set_memory
        restored = {"memory": 0, "workflows": 0, "settings": 0}
        if runtime.database.session_factory is not None:
            with runtime.database.session_factory() as s:
                for m in body.get("memory") or []:
                    if m.get("key"):
                        set_memory(s, str(m["key"]), str(m.get("value", "")),
                                   m.get("category") or "general")
                        restored["memory"] += 1
                for w in body.get("workflows") or []:
                    if w.get("name"):
                        save_workflow(s, w["name"], w.get("steps") or [],
                                      w.get("triggers") or [])
                        restored["workflows"] += 1
        if isinstance(body.get("settings"), dict):
            runtime.settings.load(body["settings"], include_secrets=False)
            runtime.settings_service.persist()
            restored["settings"] = len(body["settings"])
        return {"restored": restored}

    @api.get("/apps", tags=["system"])
    async def apps_list():
        return {"apps": runtime.registry.by_category(),
                "catalog": runtime.registry.as_catalog()}

    # --------------------------------------------------------------
    # agent
    # --------------------------------------------------------------
    @api.post("/agent/plan", response_model=dict, tags=["agent"])
    async def agent_plan(req: PlanRequest):
        plan = await runtime.planner.plan(req.command, mode=req.mode)
        return {"plan": plan.as_dict()}

    @api.post("/agent/execute", tags=["agent"])
    async def agent_execute(req: ExecuteRequest):
        if runtime.emergency.active:
            raise NovaError("Emergency stop active — release before new tasks.",
                            code="EMERGENCY_STOP")
        task_id = await runtime.tasks.execute(req.command, mode=req.mode,
                                              session_id=req.session_id)
        return {"task_id": task_id, "status": "queued"}

    @api.get("/agent/catalog", tags=["agent"])
    async def agent_catalog():
        return {"tools": runtime.registry.as_catalog()}

    # --------------------------------------------------------------
    # voice
    # --------------------------------------------------------------
    @api.post("/voice/transcribe", tags=["voice"])
    async def voice_transcribe(req: TranscribeRequest):
        from voice.pipeline import VoicePipeline
        pipeline = VoicePipeline(runtime.stt, runtime.tts, runtime.settings)
        if req.audio_base64:
            try:
                audio = base64.b64decode(req.audio_base64)
            except Exception as exc:
                raise NovaError("Invalid base64 audio", code="VOICE_ERROR") from exc
            t = pipeline.transcribe_audio(audio, language=req.language)
        elif req.audio_path:
            t = pipeline.transcribe_file(req.audio_path, language=req.language)
        else:
            # live mic capture (works only when an audio backend exists)
            t = pipeline.listen(6.0)
        return {"text": t.text, "confidence": t.confidence, "language": t.language,
                "provider": runtime.settings.get_str("voice.stt_provider", "mock")}

    # --------------------------------------------------------------
    # tasks
    # --------------------------------------------------------------
    @api.post("/tasks", status_code=201, tags=["tasks"])
    async def tasks_create(req: TaskCreateRequest):
        task_id = await runtime.tasks.execute(req.command, mode=req.mode)
        return {"task_id": task_id, "status": "queued"}

    @api.get("/tasks", tags=["tasks"], summary="Task history",
             description="Most recent tasks first. Filter by status: "
                         "queued|planning|executing|waiting_confirmation|verifying|"
                         "recovering|speaking|completed|failed|cancelled.")
    async def tasks_list(limit: int = Query(100, ge=1, le=500),
                         status: str | None = Query(None)):
        rows = runtime.store.list(limit)
        if status:
            rows = [r for r in rows if r.get("status") == status]
        return {"tasks": rows}

    @api.get("/tasks/{task_id}", tags=["tasks"])
    async def tasks_get(task_id: str):
        rec = runtime.store.get(task_id)
        if not rec:
            raise NovaError(f"Task not found: {task_id}", code="NOT_FOUND")
        return {"task": rec}

    @api.post("/tasks/{task_id}/cancel", tags=["tasks"])
    async def tasks_cancel(task_id: str, req: CancelRequest):
        ok = runtime.tasks.cancel(task_id, reason=req.reason)
        if not ok:
            raise NovaError(f"Task not found or not cancellable: {task_id}",
                            code="NOT_FOUND")
        return {"cancelled": True, "task_id": task_id}

    @api.post("/tasks/{task_id}/pause", tags=["tasks"],
              summary="Pause the active task before its next step")
    async def tasks_pause(task_id: str):
        if not runtime.tasks.pause(task_id):
            raise NovaError(
                f"Task {task_id} cannot be paused (only the active task can be).",
                code="PAUSE_REFUSED")
        return {"paused": True, "task_id": task_id}

    @api.post("/tasks/{task_id}/resume", tags=["tasks"],
              summary="Resume a paused task")
    async def tasks_resume(task_id: str):
        if not runtime.tasks.resume(task_id):
            raise NovaError(
                f"Task {task_id} is not paused (or is not the active task).",
                code="NOT_PAUSED")
        return {"resumed": True, "task_id": task_id}

    @api.get("/tasks/{task_id}/wait", tags=["tasks"])
    async def tasks_wait(task_id: str, timeout: float = Query(120.0, le=300.0)):
        rec = await runtime.tasks.wait(task_id, timeout)
        return {"task": rec}

    # --------------------------------------------------------------
    # confirmations
    # --------------------------------------------------------------
    @api.get("/confirmations", tags=["confirmations"])
    async def confirmations_list():
        return {"confirmations": [c.as_dict() for c in runtime.confirmation_store.all()]}

    @api.post("/confirmations/{conf_id}", tags=["confirmations"])
    async def confirmation_resolve(conf_id: str, req: ConfirmRequest):
        conf = runtime.confirmation_store.get(conf_id)
        if not conf:
            raise NovaError("Confirmation not found", code="NOT_FOUND")
        runtime.tasks.resolve_confirmation(conf.task_id, req.approve)
        return {"resolved": True, "approved": req.approve}

    # --------------------------------------------------------------
    # memory
    # --------------------------------------------------------------
    @api.get("/memory", tags=["memory"])
    async def memory_get():
        return {"memories": runtime.memory.describe()}

    @api.post("/memory")
    async def memory_create(req: MemoryCreateRequest):
        runtime.memory.remember(req.key, req.value, req.category)
        return {"remembered": req.key}

    @api.delete("/memory/{key}", tags=["memory"])
    async def memory_delete(key: str):
        return {"deleted": runtime.memory.forget(key)}

    # --------------------------------------------------------------
    # workflows (aliases / macros)
    # --------------------------------------------------------------
    @api.get("/workflows", tags=["workflows"])
    async def workflows_get():
        from database.service import list_workflows
        with runtime.database.session() as s:
            rows = list_workflows(s)
        return {"workflows": [{"name": r.name, "triggers": r.triggers or [],
                               "steps": r.steps, "enabled": r.enabled} for r in rows]}

    @api.post("/workflows")
    async def workflows_create(req: WorkflowCreateRequest):
        from database.service import save_workflow
        with runtime.database.session() as s:
            save_workflow(s, req.name, req.steps, req.triggers)
        return {"created": req.name}

    @api.delete("/workflows/{name}", tags=["workflows"])
    async def workflows_delete(name: str):
        from database.service import delete_workflow
        with runtime.database.session() as s:
            ok = delete_workflow(s, name)
        return {"deleted": ok}

    # --------------------------------------------------------------
    # settings
    # --------------------------------------------------------------
    @api.get("/settings", tags=["settings"])
    async def settings_get():
        return {"settings": runtime.settings.snapshot(include_secrets=False)}

    @api.put("/settings")
    async def settings_put(req: SettingsUpdateRequest):
        updated = runtime.settings_service.update(req.updates)
        return {"settings": updated}

    @api.get("/settings/defaults", tags=["settings"])
    async def settings_defaults():
        return {"defaults": runtime.settings.snapshot(include_secrets=False)}

    # --------------------------------------------------------------
    # diagnostics / observability
    # --------------------------------------------------------------
    @api.get("/diagnostics", tags=["diagnostics"])
    async def diagnostics():
        return runtime.diagnostics()

    @api.post("/diagnostics/repair", tags=["diagnostics"])
    async def diagnostics_repair():
        return runtime.self_repair()

    @api.post("/emergency_stop", tags=["safety"])
    async def emergency_stop():
        runtime.tasks.emergency_stop()
        return {"stopped": True}

    @api.post("/emergency_stop/release", tags=["safety"])
    async def emergency_release():
        runtime.tasks.release_emergency()
        return {"released": True}

    @api.get("/events", tags=["events"])
    async def events_history(limit: int = Query(100, le=500)):
        return {"events": [e.as_dict() for e in runtime.event_bus.history(limit)]}

    @api.get("/events/stream", tags=["events"])
    async def events_stream():
        queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        sid = runtime.event_bus.publisher(queue)
        for e in runtime.event_bus.history(20):
            queue.put_nowait(e)

        async def gen():
            try:
                yield "retry: 1500\n\n"
                while True:
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        # heartbeat keeps proxies/UI watchdogs confident (§40)
                        yield ": heartbeat\n\n"
                        continue
                    yield f"data: {json.dumps(item.as_dict())}\n\n"
            except asyncio.CancelledError:
                pass
            finally:
                runtime.event_bus.unpublish(sid)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    # --------------------------------------------------------------
    # browser-extension companion bridge (spec §48)
    # --------------------------------------------------------------
    @api.post("/companion/register", tags=["companion"])
    async def companion_register(body: dict):
        cid = body.get("connection_id") or f"browser-{int(time.time())}"
        runtime._companion_registry = getattr(runtime, "_companion_registry", {})
        runtime._companion_registry[cid] = {"last_seen": time.time()}
        runtime._companion_commands = getattr(runtime, "_companion_commands", {})
        runtime._companion_commands.setdefault(cid, [])
        return {"connection_id": cid}

    @api.post("/companion/event", tags=["companion"])
    async def companion_event(body: dict):
        cid = body.get("connection_id", "unknown")
        payload = body.get("payload", {})
        runtime.event_bus.emit("companion.event",
                               {"connection_id": cid, **payload})
        runtime._companion_last_event = getattr(runtime, "_companion_last_event", None) or \
            {}
        runtime._companion_last_event = {"connection_id": cid, "payload": payload,
                                         "at": time.time()}
        return {"received": True}

    @api.get("/companion/{cid}/commands", tags=["companion"])
    async def companion_commands(cid: str):
        runtime._companion_commands = getattr(runtime, "_companion_commands", {})
        cmds = runtime._companion_commands.pop(cid, [])
        return {"commands": cmds}

    @api.post("/companion/command-panel", tags=["companion"])
    async def companion_panel():
        runtime.event_bus.emit("ui.show_panel", {})
        return {"ok": True}

    # --------------------------------------------------------------
    # frontend (modular SPA served same-origin; assets under /static)
    # --------------------------------------------------------------
    import os as _os_

    from fastapi.responses import HTMLResponse, Response
    from fastapi.staticfiles import StaticFiles

    _dash_dir = _os_.path.join(_os_.path.dirname(_os_.path.dirname(_os_.path.abspath(__file__))),
                               "dashboard")
    _index = _os_.path.join(_dash_dir, "index.html")

    app.mount("/static", StaticFiles(directory=_dash_dir), name="dashboard-static")

    def _read_index() -> str:
        with open(_index, encoding="utf-8") as fh:
            return fh.read()

    @app.get("/", include_in_schema=False)
    @app.get("/dashboard", include_in_schema=False)
    @app.get("/dev", include_in_schema=False)
    async def dashboard():
        if _os_.path.exists(_index):
            # read off the event loop; no-cache so frontend updates appear instantly
            html = await asyncio.to_thread(_read_index)
            return Response(content=html, media_type="text/html",
                            headers={"Cache-Control": "no-cache"})
        return HTMLResponse("<h3>Dashboard missing — run dev_setup.py</h3>", status_code=404)

    # --------------------------------------------------------------
    # actions (direct tool invocation — developer mode, locked down §56)
    # --------------------------------------------------------------
    @api.post("/actions/{tool_name}", tags=["developer"])
    async def action_invoke(tool_name: str, body: dict):
        if not runtime.settings.get_bool("developer.direct_actions", False):
            raise NovaError(
                "Direct tool invocation is disabled. Enable "
                "'developer.direct_actions' in settings to use it.",
                code="PERMISSION_DENIED")
        try:
            tool = runtime.registry.get(tool_name)
        except NovaError as exc:
            raise HTTPException(404, f"Unknown tool: {tool_name}") from exc
        # even in developer mode the permission engine is authoritative:
        # tools that would normally confirm cannot be fired without a task
        definition = tool.to_definition()
        decision = runtime.permissions.check(definition, body.get("arguments", {}) or {},
                                             task_id="developer-action")
        if decision != "allow":
            raise NovaError(
                f"'{tool_name}' requires user confirmation and cannot run "
                "through the direct-action endpoint.",
                code="CONFIRMATION_REQUIRED")
        result = await tool.execute(body.get("arguments", {}) or {})
        return result.as_dict()

    app.include_router(api)

    # --------------------------------------------------------------
    # API security (V2 §56): bearer-token auth when configured
    # --------------------------------------------------------------
    from api.auth import load_or_create_token, wrap_app
    token = None
    if runtime.settings.get_bool("api.auth_enabled", False):
        token = load_or_create_token(runtime.settings.data_dir)
        if token:
            runtime.api_token_hint = token[:4] + "…"  # for diagnostics only
    return wrap_app(app, token,
                    log=lambda msg: runtime.event_bus.emit("api.denied", {"detail": msg}))
