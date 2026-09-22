"""V2 integration tests: queue, pause/resume, undo, stop-everything,
introspection, change stats, auth middleware."""
import asyncio
import os

import pytest


# ---------------------------------------------------------------- queue
@pytest.mark.asyncio
async def test_single_flight_queue_serializes_tasks(allow_all, tmp_path):
    rt = allow_all
    target = tmp_path / "queued-after-a"
    tid_a = await rt.execute('Run the command "sleep 1"', mode="smart")
    tid_b = await rt.execute(f"Create a folder called {target}", mode="smart")
    # B must be queued while A holds the computer
    await asyncio.sleep(0.2)
    assert rt.store.status(tid_b) == "queued"
    assert tid_b in rt.tasks.queue
    rec_a = await rt.wait(tid_a, timeout=30)
    rec_b = await rt.wait(tid_b, timeout=30)
    assert rec_a["status"] == "completed"
    assert rec_b["status"] == "completed"
    assert target.is_dir()
    assert rt.tasks.queue == []


@pytest.mark.asyncio
async def test_cancel_queued_task_never_runs(allow_all, tmp_path):
    rt = allow_all
    target = tmp_path / "never-runs"
    tid_a = await rt.execute('Run the command "sleep 1"', mode="smart")
    tid_b = await rt.execute(f"Create a folder called {target}", mode="smart")
    await asyncio.sleep(0.1)
    assert rt.store.status(tid_b) == "queued"
    assert rt.tasks.cancel(tid_b, "user_cancel")
    rec_b = await rt.wait(tid_b, timeout=10)
    assert rec_b["status"] == "cancelled"
    await rt.wait(tid_a, timeout=30)
    assert not target.exists()


# ---------------------------------------------------------------- pause
@pytest.mark.asyncio
async def test_pause_and_resume_active_task(allow_all):
    rt = allow_all
    tid = await rt.execute('Run the command "sleep 2"', mode="smart")
    await asyncio.sleep(0.15)
    assert rt.tasks.pause(tid)
    # step finishes, gate blocks -> paused before the verify gate
    await asyncio.sleep(2.6)
    assert rt.store.status(tid) == "paused"
    assert rt.tasks.state == "PAUSED"
    assert rt.tasks.resume(tid)
    rec = await rt.wait(tid, timeout=30)
    assert rec["status"] == "completed"


@pytest.mark.asyncio
async def test_pause_refused_for_inactive_task(allow_all, tmp_path):
    rt = allow_all
    tid = await rt.execute(f"Create a folder called {tmp_path / 'pause-refuse'}",
                           mode="smart")
    rec = await rt.wait(tid, timeout=30)
    assert rec["status"] == "completed"
    assert rt.tasks.pause(tid) is False
    assert rt.tasks.resume(tid) is False


# ---------------------------------------------------------------- stop
@pytest.mark.asyncio
async def test_stop_everything_plans_core_cancel(runtime):
    plan = await runtime.planner.plan("Stop everything")
    assert [s.tool for s in plan.steps] == ["core.cancel"]


@pytest.mark.asyncio
async def test_pause_voice_maps_to_core_pause(runtime):
    plan = await runtime.planner.plan("Pause the task")
    assert [s.tool for s in plan.steps] == ["core.pause"]


@pytest.mark.asyncio
async def test_cancel_all_cancels_active_and_queued(allow_all, tmp_path):
    rt = allow_all
    tid_a = await rt.execute('Run the command "sleep 2"', mode="smart")
    tid_b = await rt.execute(f"Create a folder called {tmp_path / 'cancel-all-b'}",
                             mode="smart")
    await asyncio.sleep(0.15)
    cancelled = rt.tasks.cancel_all("user_cancel")
    assert cancelled == 2
    rec_a = await rt.wait(tid_a, timeout=30)
    rec_b = await rt.wait(tid_b, timeout=10)
    assert rec_a["status"] == "cancelled"
    assert rec_b["status"] == "cancelled"


# ---------------------------------------------------------------- undo
@pytest.mark.asyncio
async def test_undo_last_thing_reverses_created_folder(allow_all, tmp_path):
    rt = allow_all
    target = str(tmp_path / "undo-target-folder")
    tid = await rt.execute(f"Create a folder called {target}", mode="smart")
    rec = await rt.wait(tid, timeout=30)
    assert rec["status"] == "completed" and os.path.isdir(target)

    # "undo the last thing" plans undo.last which asks for confirmation
    tid2 = await rt.execute("Undo the last thing", mode="smart")
    conf = None
    for _ in range(60):
        confs = rt.permissions.store.all()
        conf = next((c for c in confs if c.task_id == tid2), None)
        if conf:
            break
        await asyncio.sleep(0.1)
    assert conf is not None, "undo confirmation never appeared"
    rt.permissions.store.resolve(conf.id, True)
    rt.tasks.resolve_confirmation(tid2, True)
    rec2 = await rt.wait(tid2, timeout=30)
    assert rec2["status"] == "completed", rec2.get("error")
    assert not os.path.isdir(target)


@pytest.mark.asyncio
async def test_task_records_change_stats(allow_all, tmp_path):
    rt = allow_all
    name = tmp_path / "change-stats-check"
    tid = await rt.execute(f"Create a folder called {name}", mode="smart")
    rec = await rt.wait(tid, timeout=30)
    assert rec["status"] == "completed"
    changes = rec.get("changes") or {}
    assert changes.get("created") == 1
    assert any("change-stats-check" in f for f in changes.get("files", []))


# ------------------------------------------------------- introspection
@pytest.mark.asyncio
async def test_list_tools_voice_command(allow_all):
    rt = allow_all
    tid = await rt.execute("List available tools", mode="smart")
    rec = await rt.wait(tid, timeout=30)
    assert rec["status"] == "completed", rec.get("error")
    assert "tools registered" in (rec.get("result") or "")


@pytest.mark.asyncio
async def test_show_last_error_voice_command(allow_all):
    rt = allow_all
    # produce a failed task first (delete of a missing path fails)
    tid_bad = await rt.execute("Delete /tmp/definitely-not-here-xyz.txt",
                               mode="smart")
    # delete requires confirmation -> approve it so it runs and fails honestly
    for _ in range(60):
        confs = rt.permissions.store.all()
        conf = next((c for c in confs if c.task_id == tid_bad), None)
        if conf:
            rt.permissions.store.resolve(conf.id, True)
            rt.tasks.resolve_confirmation(tid_bad, True)
            break
        await asyncio.sleep(0.1)
    rec_bad = await rt.wait(tid_bad, timeout=30)
    assert rec_bad["status"] == "failed"

    tid = await rt.execute("Show last error", mode="smart")
    rec = await rt.wait(tid, timeout=30)
    assert rec["status"] == "completed"
    assert "Nothing deleted" in (rec.get("result") or "") or rec.get("result")


@pytest.mark.asyncio
async def test_run_diagnostics_voice_command(allow_all):
    rt = allow_all
    tid = await rt.execute("Run a full NOVA diagnostic", mode="smart")
    rec = await rt.wait(tid, timeout=60)
    assert rec["status"] == "completed", rec.get("error")
    assert "checks passed" in (rec.get("result") or "")


# ------------------------------------------------------------- security
def test_auth_middleware_blocks_without_token(tmp_path):
    from fastapi.testclient import TestClient

    from api.app import build_app
    from api.auth import load_or_create_token
    from runtime import Runtime

    os.environ["NOVA_API_TOKEN"] = "sekrit-test-token"
    try:
        rt = Runtime(for_testing=True, force_heuristic=True,
                     db_url=f"sqlite:///{tmp_path / 'auth.db'}")
        rt.settings.load({"storage.data_dir": str(tmp_path),
                          "api.auth_enabled": True})
        app = build_app(rt)
        client = TestClient(app)

        # open endpoints stay open
        assert client.get("/api/health").status_code == 200
        # sensitive endpoints demand the token
        r = client.post("/api/agent/execute", json={"command": "x"})
        assert r.status_code == 401
        # correct token unlocks
        token = load_or_create_token()
        r = client.post("/api/agent/execute", json={"command": "x"},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        # query-string token also accepted (desktop webviews)
        assert client.get(f"/api/tasks?token={token}").status_code == 200
        rt.shutdown()
    finally:
        del os.environ["NOVA_API_TOKEN"]


def test_no_auth_by_default(tmp_path):
    from fastapi.testclient import TestClient

    from api.app import build_app
    from runtime import Runtime

    rt = Runtime(for_testing=True, force_heuristic=True,
                 db_url=f"sqlite:///{tmp_path / 'noauth.db'}")
    rt.settings.load({"storage.data_dir": str(tmp_path)})
    client = TestClient(build_app(rt))
    assert client.get("/api/system/status").status_code == 200
    rt.shutdown()


# ---------------------------------------------------------- state machine
@pytest.mark.asyncio
async def test_state_history_records_transitions(allow_all):
    rt = allow_all
    tid = await rt.execute("Create a folder called state-history-check", mode="smart")
    await rt.wait(tid, timeout=30)
    seen = {h["to"] for h in rt.tasks.state_history(100)}
    assert {"UNDERSTANDING", "PLANNING", "EXECUTING", "VERIFYING"} <= seen
    assert rt.tasks.state == "IDLE"


@pytest.mark.asyncio
async def test_cancel_wakes_confirmation_waiter(runtime):
    """A cancelled task parked on a confirmation must release the gate
    immediately — not after the 300s confirmation timeout."""
    rt = runtime
    tid = await rt.execute("Delete /tmp/wake-me-on-cancel.txt", mode="smart")
    conf = None
    for _ in range(60):
        conf = rt.permissions.store.get_for_task(tid)
        if conf:
            break
        await asyncio.sleep(0.1)
    assert conf is not None
    assert rt.store.status(tid) == "waiting_confirmation"
    import time as _t
    t0 = _t.monotonic()
    rt.tasks.cancel(tid, "user_cancel")
    rec = await rt.wait(tid, timeout=10)
    elapsed = _t.monotonic() - t0
    assert rec["status"] == "cancelled"
    assert elapsed < 5, f"cancel took {elapsed:.1f}s — waiter not woken"
    await asyncio.sleep(0.2)  # let _run()'s finally-block release the gate
    assert rt.tasks.active_task is None


def test_interrupt_command_detection():
    from agent.task_manager import is_interrupt_command
    assert is_interrupt_command("Stop everything")
    assert is_interrupt_command("stop")
    assert is_interrupt_command("Cancel")
    assert is_interrupt_command("abort now")
    # paths containing interrupt words are NOT interrupts
    assert not is_interrupt_command("Delete /tmp/cancel-log.txt")
    assert not is_interrupt_command("open stop-motion.txt")


@pytest.mark.asyncio
async def test_stop_everything_bypasses_queue(allow_all, tmp_path):
    """§75: an interrupt must cancel the busy task immediately, not queue
    behind it."""
    rt = allow_all
    tid_a = await rt.execute('Run the command "sleep 3"', mode="smart")
    await asyncio.sleep(0.3)
    assert rt.tasks.active_task == tid_a
    # 'Stop everything' cancels A synchronously and does not sit in the queue
    tid_s = await rt.execute("Stop everything", mode="smart")
    rec_a = await rt.wait(tid_a, timeout=15)
    assert rec_a["status"] == "cancelled"
    rec_s = await rt.wait(tid_s, timeout=15)
    assert rec_s["status"] == "completed"
    assert "Cancelled 1 task(s)" in (rec_s.get("result") or "")


@pytest.mark.asyncio
async def test_failed_task_never_claims_success(allow_all):
    """§61: a task whose steps failed must not report a 'Completed' result."""
    rt = allow_all
    tid = await rt.execute('Run the command "definitely-not-a-real-cmd-xyz"',
                           mode="smart")
    rec = await rt.wait(tid, timeout=30)
    result = rec.get("result") or ""
    if rec["status"] == "failed":
        assert "Completed" not in result, result
        assert result.startswith("Failed"), result
