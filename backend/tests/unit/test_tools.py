"""Tool registry + tool execution + permission integration tests."""

import pytest
from tools import ToolRegistry


def test_registry_discovers_all_categories(runtime):
    names = runtime.registry.names()
    assert len(names) >= 80
    for tool in ("computer.click", "computer.type", "filesystem.write_file",
                 "filesystem.delete", "shell.run", "browser.open",
                 "whatsapp.open", "vscode.open", "system.shutdown",
                 "process.stop", "memory.remember"):
        assert tool in names, f"missing {tool}"


def test_registry_catalog_schema(runtime):
    catalog = runtime.registry.as_catalog()
    assert catalog, "catalog empty"
    for entry in catalog[:5]:
        assert {"name", "description", "permission_level", "category",
                "input_schema"} <= set(entry.keys())


def test_tool_definition_metadata(runtime):
    d = runtime.registry.definition("filesystem.delete")
    assert d.permission_level == "high"
    assert d.requires_confirmation is True


def test_unknown_tool_raises(runtime):
    from core.exceptions import ToolNotFound
    with pytest.raises(ToolNotFound):
        registry = ToolRegistry(runtime.tool_context)
        _ = registry
        from tools import ToolRegistry as TR
        reg = TR(runtime.tool_context)
        reg.register_module("tools.filesystem")
        reg.get("does.not.exist")


# ---------------------------------------------------------------------------
# async tool execution tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_filesystem_roundtrip(runtime, tmp_path):
    from tests.helpers import invoke
    res = await invoke(runtime, "filesystem.write_file",
                       {"path": str(tmp_path / "a.txt"), "content": "hi"})
    assert res.success
    assert (tmp_path / "a.txt").read_text() == "hi"

    res2 = await invoke(runtime, "filesystem.read_file", {"path": str(tmp_path / "a.txt")})
    assert res2.success
    assert res2.data["content"] == "hi"


@pytest.mark.asyncio
async def test_shell_run_safe_command(runtime):
    from tests.helpers import invoke
    res = await invoke(runtime, "shell.run", {"command": "echo nova-ok"})
    assert res.success
    assert "nova-ok" in res.data.get("stdout", "")


@pytest.mark.asyncio
async def test_shell_run_dangerous_blocked(runtime):
    from tests.helpers import invoke
    res = await invoke(runtime, "shell.run", {"command": "rm -rf /"})
    assert not res.success
    assert res.error_code == "EXECUTION_BLOCKED" or res.error_code == "SAFETY"


@pytest.mark.asyncio
async def test_computer_tools_memory_backend(runtime):
    from tests.helpers import invoke
    res = await invoke(runtime, "computer.active_window")
    assert res.success
    res2 = await invoke(runtime, "computer.move", {"x": 100, "y": 200})
    assert res2.success


@pytest.mark.asyncio
async def test_process_list_detect(runtime):
    from tests.helpers import invoke
    res = await invoke(runtime, "process.list")
    assert res.success
    res2 = await invoke(runtime, "process.detect", {"name": "python"})
    assert res2.success
    assert res2.data["running"] is True  # our own interpreter is running


@pytest.mark.asyncio
async def test_browser_in_memory(runtime):
    from tests.helpers import invoke
    res = await invoke(runtime, "browser.open", {"url": "https://example.com"})
    assert res.success
    res2 = await invoke(runtime, "browser.read_text")
    assert res2.success
    assert "Example Domain" in res2.data.get("text", "")


@pytest.mark.asyncio
async def test_web_search_offline_tolerant(runtime):
    from tests.helpers import invoke
    res = await invoke(runtime, "web.search", {"query": "python"})
    assert res.success  # structured either online or offline


@pytest.mark.asyncio
async def test_vscode_detect_on_this_platform(runtime):
    from tests.helpers import invoke
    res = await invoke(runtime, "vscode.detect")
    assert res.success
    assert "installed" in res.data


@pytest.mark.asyncio
async def test_whatsapp_open_web_fallback(runtime):
    from tests.helpers import invoke
    res = await invoke(runtime, "whatsapp.open")
    assert res.success


def test_delete_confirmation_is_enriched(runtime, tmp_path):
    """filesystem.delete must show *what & how much* in the confirmation prompt."""
    target = tmp_path / "victim.txt"
    target.write_text("nova" * 10)

    tool = runtime.registry.get("filesystem.delete")
    detail = tool.summarize_confirmation(
        {"paths": [str(target)], "use_recycle_bin": True})
    assert detail is not None
    assert "1 item" in detail
    assert "victim.txt" in detail
    assert "recycle bin" in detail


def test_delete_confirmation_routed_into_store(runtime, tmp_path):
    """The enriched detail must land in the stored confirmation question."""
    target = tmp_path / "doomed.txt"
    target.write_text("x")

    definition = runtime.registry.definition("filesystem.delete")
    tool = runtime.registry.get("filesystem.delete")
    detail = tool.summarize_confirmation({"paths": [str(target)],
                                          "use_recycle_bin": False})
    conf = runtime.permissions.request_confirmation(
        definition, {"paths": [str(target)], "use_recycle_bin": False},
        task_id="t-enrich", detail=detail)
    assert "doomed.txt" in conf.question
    assert "permanent" in conf.question


def test_confirmation_consumed_after_decision(runtime, tmp_path):
    """Approved/declined confirmations must disappear from the store (no stale prompts)."""
    import asyncio

    target = tmp_path / "stale-check"
    runtime.settings.load({"permissions.default_medium": "ask"})

    async def flow():
        tid = await runtime.tasks.execute(f"create a folder called {target}", mode="smart")
        # wait until the confirmation appears
        for _ in range(50):
            if runtime.confirmation_store.all():
                break
            await asyncio.sleep(0.05)
        confs = runtime.confirmation_store.all()
        assert confs, "confirmation was never created"
        runtime.tasks.resolve_confirmation(confs[0].task_id, True)
        await runtime.tasks.wait(tid, timeout=15)
        # after the decision, the store must be empty again
        assert runtime.confirmation_store.all() == [], \
            "stale confirmation left in the store after resolution"

    asyncio.run(flow())


def test_reap_interrupted_tasks(tmp_path):
    """Tasks left in-flight by a crash/restart are marked failed, not phantom-executing."""
    from database.service import create_task_with_id, reap_interrupted_tasks, update_task
    from database.session import Database

    db = Database(f"sqlite:///{tmp_path / 'reap.db'}")
    db.create_all()
    with db.session_factory() as s:
        create_task_with_id(s, "task-alive1", "do a thing", "smart")
        update_task(s, "task-alive1", status="executing")
        create_task_with_id(s, "task-done1", "done thing", "smart")
        update_task(s, "task-done1", status="completed")

    with db.session_factory() as s:
        n = reap_interrupted_tasks(s)
    assert n == 1
    with db.session_factory() as s:
        from database.service import get_task
        assert get_task(s, "task-alive1").status == "failed"
        assert "restart" in (get_task(s, "task-alive1").error or "")
        assert get_task(s, "task-done1").status == "completed"
