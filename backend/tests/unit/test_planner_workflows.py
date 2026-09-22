"""Tests for planner, workflows, voice pipeline and self-repair."""
import pytest
from planner import TaskPlan, create_planner
from planner.heuristic import HeuristicPlanner as HP


def test_heuristic_vs_code_intent(runtime):
    planner = runtime.planner
    import asyncio
    plan = asyncio.run(planner.plan("Open VS Code", mode="smart"))
    assert isinstance(plan, TaskPlan)
    assert plan.steps[0].tool in ("vscode.open", "computer.launch_app")


def test_heuristic_screenshot_intent(runtime):
    import asyncio
    plan = asyncio.run(runtime.planner.plan("Take a screenshot", mode="computer"))
    assert plan.steps[0].tool == "computer.screenshot"


def test_heuristic_whatsapp_download(runtime):
    import asyncio
    plan = asyncio.run(runtime.planner.plan(
        "Go to WhatsApp and get Rahul's latest photo", mode="smart"))
    tools = [s.tool for s in plan.steps]
    assert any("whatsapp" in t for t in tools)


def test_heuristic_build_project(runtime):
    import asyncio
    plan = asyncio.run(runtime.planner.plan(
        "Build a complete React portfolio", mode="build"))
    tools = [s.tool for s in plan.steps]
    assert "filesystem.create_folder" in tools
    assert "filesystem.write_file" in tools
    assert any(s.tool == "shell.run" for s in plan.steps)


def test_heuristic_search_web(runtime):
    import asyncio
    plan = asyncio.run(runtime.planner.plan(
        "Search the web for latest AI news", mode="smart"))
    assert plan.steps[0].tool == "web.search"


def test_heuristic_stop_everything(runtime):
    import asyncio
    plan = asyncio.run(runtime.planner.plan("Stop everything", mode="smart"))
    assert plan.steps[0].tool == "core.cancel"


def test_create_planner_selects_heuristic_for_mock():
    from core.config import Settings
    from tools import ToolRegistry, build_tool_context
    s = Settings({"ai.provider": "mock"})
    ctx = build_tool_context(s)
    reg = ToolRegistry(ctx)
    p = create_planner(s, reg, None, None)
    assert isinstance(p, HP)


# ---------------------------------------------------------------------------
# workflows
# ---------------------------------------------------------------------------
def test_workflow_parse_and_run_schema():
    from workflows import Workflow
    from workflows.engine import WorkflowStep
    wf = Workflow(name="test", steps=[
        WorkflowStep("computer.launch_app", {"command": "code"}),
        WorkflowStep("computer.launch_app", {"command": "chrome"}, parallel=True),
    ])
    d = wf.as_dict()
    assert d["steps"][1]["parallel"] is True


@pytest.mark.asyncio
async def test_workflow_engine_sequential(runtime):
    from workflows import Workflow, WorkflowEngine, WorkflowStep
    engine = WorkflowEngine(runtime.registry, runtime.executor)
    order = []

    async def run_fn(step, ctx):
        order.append(step.tool)
        from tools.base import ToolResult
        return ToolResult.ok({"tool": step.tool})

    wf = Workflow("seq", steps=[
        WorkflowStep("computer.launch_app", {"command": "a"}),
        WorkflowStep("computer.launch_app", {"command": "b"}),
    ])
    res = await engine.run(wf, run_fn=run_fn)
    assert order == ["computer.launch_app", "computer.launch_app"]
    assert res["success"] is True


@pytest.mark.asyncio
async def test_workflow_engine_parallel(runtime):
    from workflows import Workflow, WorkflowEngine, WorkflowStep
    engine = WorkflowEngine(runtime.registry, runtime.executor)

    async def run_fn(step, ctx):
        import asyncio
        await asyncio.sleep(0.05)
        from tools.base import ToolResult
        return ToolResult.ok({"tool": step.tool})

    wf = Workflow("par", steps=[
        WorkflowStep("computer.launch_app", {"command": "x"}, parallel=True),
        WorkflowStep("computer.launch_app", {"command": "y"}, parallel=True),
    ])
    res = await engine.run(wf, run_fn=run_fn)
    assert len(res["results"]) == 2


# ---------------------------------------------------------------------------
# voice pipeline (mock providers)
# ---------------------------------------------------------------------------
def test_voice_pipeline_mock_transcription(runtime):
    from voice import VoicePipeline
    vp = VoicePipeline(runtime.stt, runtime.tts, runtime.settings)
    t = vp.transcribe_audio(b"RIFFfake")
    assert t.text == "Open Chrome"  # MockSTT fixture


def test_vad_detects_speech():
    import array

    from voice import VoiceActivityDetector
    vad = VoiceActivityDetector(threshold=300.0)
    silence = array.array("h", [0] * 16000).tobytes()
    assert vad.speech_windows(silence) == []
    loud = array.array("h", [8000] * 16000).tobytes()
    assert vad.speech_windows(loud), "loud audio should produce a speech window"


# ---------------------------------------------------------------------------
# self-repair
# ---------------------------------------------------------------------------
def test_self_repair_loop_converges(runtime):
    report = runtime.self_repair()
    assert isinstance(report["summary"], dict)
    assert "rounds" in report


# ---------------------------------------------------------------------------
# observer
# ---------------------------------------------------------------------------
def test_observer_screenshot_and_compare(runtime):
    snap1 = runtime.observer.screenshot()
    assert snap1.id
    assert snap1.source in ("synthetic", "os", "disabled")
    snap2 = runtime.observer.screenshot()
    comp = runtime.observer.compare(snap1, snap2)
    assert "changed" in comp


def test_explicit_path_delete_not_hijacked_by_memory_shortcut(runtime):
    """'delete <explicit path containing "college project">' must plan a delete,
    not a memory.recall + list of @college_projects."""
    import asyncio
    plan = asyncio.run(runtime.planner.plan(
        "delete the file /tmp/nova-demo/College Projects/report.txt"))
    tools = [s.tool for s in plan.steps]
    assert "filesystem.delete" in tools, f"expected delete, got {tools}"
    assert "memory.recall" not in tools, f"memory shortcut hijacked the command: {tools}"
    delete_step = next(s for s in plan.steps if s.tool == "filesystem.delete")
    assert delete_step.arguments["paths"] == ["/tmp/nova-demo/College Projects/report.txt"]


def test_open_college_project_still_uses_memory(runtime):
    """The memory shortcut must still work for genuine 'open my college projects'."""
    import asyncio
    plan = asyncio.run(runtime.planner.plan("open my college projects"))
    tools = [s.tool for s in plan.steps]
    assert tools[0] == "memory.recall"


def test_failed_step_marks_task_failed(runtime, tmp_path):
    """A step that fails must mark the whole task failed, not completed."""
    import asyncio

    async def flow():
        tid = await runtime.tasks.execute(
            f"delete the file {tmp_path}/does-not-exist-xyz.txt", mode="smart")
        # auto-allow so it proceeds without confirmation
        runtime.permissions.set_session_rule("filesystem.delete", "allow")
        rec = await runtime.tasks.wait(tid, timeout=15)
        return rec

    rec = asyncio.run(flow())
    assert rec.get("status") == "failed", f"expected failed, got {rec.get('status')}"
    assert rec.get("error")
