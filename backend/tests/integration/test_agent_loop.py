"""End-to-end agent loop tests (acceptance scenarios §61)."""
import asyncio

import pytest
from core.exceptions import EmergencyStop


@pytest.mark.asyncio
async def test_acceptance_open_application(allow_all):
    tid = await allow_all.execute("Open Chrome", mode="smart")
    rec = await allow_all.wait(tid, timeout=30)
    assert rec["status"] == "completed", rec.get("error")


@pytest.mark.asyncio
async def test_acceptance_create_folder(allow_all, tmp_path):
    target = tmp_path / "AI Projects"
    tid = await allow_all.execute(f"Create a folder called {target}", mode="smart")
    rec = await allow_all.wait(tid, timeout=30)
    assert rec["status"] == "completed"
    assert target.is_dir()


@pytest.mark.asyncio
async def test_acceptance_create_and_write_file(allow_all, tmp_path):
    f = tmp_path / "notes.txt"
    tid = await allow_all.execute(
        f"Create a file called {f} with content nova test", mode="smart")
    rec = await allow_all.wait(tid, timeout=30)
    assert rec["status"] == "completed"
    assert f.read_text() == "nova test"


@pytest.mark.asyncio
async def test_acceptance_run_command(allow_all):
    tid = await allow_all.execute('Run the command "echo abc123"', mode="smart")
    rec = await allow_all.wait(tid, timeout=30)
    assert rec["status"] == "completed"


@pytest.mark.asyncio
async def test_acceptance_locate_files(allow_all, tmp_path):
    (tmp_path / "resume.pdf").write_text("x")
    tid = await allow_all.execute("Find my resume file", mode="smart")
    rec = await allow_all.wait(tid, timeout=30)
    assert rec["status"] == "completed"


@pytest.mark.asyncio
async def test_acceptance_largest_files(allow_all, tmp_path):
    (tmp_path / "big.bin").write_bytes(b"x" * 5000)
    tid = await allow_all.execute(f"Find the largest files in {tmp_path}", mode="smart")
    rec = await allow_all.wait(tid, timeout=40)
    assert rec["status"] == "completed"


@pytest.mark.asyncio
async def test_acceptance_browser_navigation(allow_all):
    tid = await allow_all.execute("Open the website example.com", mode="browser")
    rec = await allow_all.wait(tid, timeout=30)
    assert rec["status"] == "completed"


@pytest.mark.asyncio
async def test_acceptance_screenshot(allow_all):
    tid = await allow_all.execute("Take a screenshot", mode="computer")
    rec = await allow_all.wait(tid, timeout=30)
    assert rec["status"] == "completed"


@pytest.mark.asyncio
async def test_confirmation_flow_delete(runtime, tmp_path):
    victim = tmp_path / "delete-me.txt"
    victim.write_text("bye")
    tid = await runtime.execute(f"Delete the file {victim}", mode="smart")
    # wait for confirmation
    for _ in range(100):
        await asyncio.sleep(0.05)
        confs = runtime.confirmation_store.all()
        if confs:
            assert confs[0].tool == "filesystem.delete"
            runtime.tasks.resolve_confirmation(tid, True)
            break
    rec = await runtime.wait(tid, timeout=40)
    assert rec["status"] == "completed"
    assert not victim.exists()


@pytest.mark.asyncio
async def test_confirmation_decline_prevents_delete(runtime, tmp_path):
    victim = tmp_path / "keep.txt"
    victim.write_text("keep")
    tid = await runtime.execute(f"Delete the file {victim}", mode="smart")
    for _ in range(100):
        await asyncio.sleep(0.05)
        confs = runtime.confirmation_store.all()
        if confs:
            runtime.tasks.resolve_confirmation(tid, False)
            break
    rec = await runtime.wait(tid, timeout=40)
    assert rec["status"] in ("cancelled", "failed")
    assert victim.exists()


@pytest.mark.asyncio
async def test_cancel_active_task(allow_all):
    tid = await allow_all.execute("Open Chrome", mode="smart")
    await asyncio.sleep(0.2)
    assert allow_all.tasks.cancel(tid)
    rec = await allow_all.wait(tid, timeout=30)
    assert rec["status"] == "cancelled"


@pytest.mark.asyncio
async def test_emergency_stop_task(allow_all):
    allow_all.tasks.emergency_stop()
    assert allow_all.emergency.active
    with pytest.raises(EmergencyStop):
        await allow_all.execute("Open Chrome", mode="smart")
    allow_all.tasks.release_emergency()
    assert not allow_all.emergency.active


@pytest.mark.asyncio
async def test_state_machine_sets_idle_after_task(allow_all):
    tid = await allow_all.execute("Open Chrome", mode="smart")
    await allow_all.wait(tid, timeout=30)
    assert allow_all.state == "IDLE"
    assert allow_all.tasks.active_task is None


@pytest.mark.asyncio
async def test_conversational_memory_followup(runtime, allow_all):
    # remember then recall
    runtime.memory.remember("college_projects", "/tmp/college-projects")
    val = runtime.memory.recall("college_projects")
    assert val == "/tmp/college-projects"
    # argument placeholder resolution
    resolved = runtime.memory.resolve({"path": "@college_projects"})
    assert resolved["path"] == "/tmp/college-projects"
