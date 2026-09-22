"""Tests for the update system (§54) and workflow variables (§34-35)."""
from __future__ import annotations

import asyncio

import pytest

from core.updater import UpdateChecker, is_newer, parse_version
from workflows.engine import (MissingWorkflowVariable, Workflow, WorkflowEngine,
                              WorkflowStep, render_variables, required_variables)


# ---------------------------------------------------------------------------
# §54 — update checker
# ---------------------------------------------------------------------------

def test_parse_version():
    assert parse_version("2.1.0") == (2, 1, 0)
    assert parse_version("v2.10.3") == (2, 10, 3)
    assert parse_version("2") == (2,)


def test_is_newer():
    assert is_newer("2.1.0", "2.0.0")
    assert is_newer("2.10.0", "2.9.9")
    assert not is_newer("2.0.0", "2.0.0")
    assert not is_newer("1.9.9", "2.0.0")


class _Settings:
    def __init__(self, enabled=True, url="https://example.com/manifest.json"):
        self._d = {"updates.enabled": enabled, "updates.manifest_url": url}

    def get_bool(self, k, default=False):
        return bool(self._d.get(k, default))

    def get_str(self, k, default=""):
        return str(self._d.get(k, default))


def _fetcher(payload: str | Exception):
    async def fetch(url):
        if isinstance(payload, Exception):
            raise payload
        return payload
    return fetch


def _check(checker):
    return asyncio.run(checker.check())


def test_update_disabled():
    c = UpdateChecker(_Settings(enabled=False), fetcher=_fetcher("{}"))
    r = _check(c)
    assert r["status"] == "disabled"


def test_update_not_configured():
    c = UpdateChecker(_Settings(url=""), fetcher=_fetcher("{}"))
    assert _check(c)["status"] == "not_configured"


def test_update_available():
    manifest = '{"version": "2.1.0", "url": "https://x/nova.exe", "notes": "n"}'
    c = UpdateChecker(_Settings(), fetcher=_fetcher(manifest),
                      current_version="2.0.0")
    r = _check(c)
    assert r["status"] == "available"
    assert r["update"]["latest_version"] == "2.1.0"
    assert "never installs" in r["message"].lower()


def test_update_up_to_date():
    manifest = '{"version": "2.0.0"}'
    c = UpdateChecker(_Settings(), fetcher=_fetcher(manifest),
                      current_version="2.0.0")
    assert _check(c)["status"] == "up_to_date"


def test_update_bad_json_degrades():
    c = UpdateChecker(_Settings(), fetcher=_fetcher("not json"))
    assert _check(c)["status"] == "unavailable"


def test_update_network_error_degrades():
    c = UpdateChecker(_Settings(), fetcher=_fetcher(OSError("offline")))
    r = _check(c)
    assert r["status"] == "unavailable"
    assert "offline" in r["message"]


def test_update_install_never_automatic():
    manifest = '{"version": "9.9.9", "url": "https://x/nova.exe"}'
    c = UpdateChecker(_Settings(), fetcher=_fetcher(manifest),
                      current_version="2.0.0")
    r = asyncio.run(c.request_install())
    assert r["started"] is False
    assert r["manual"] is True
    assert r["download_url"] == "https://x/nova.exe"


# ---------------------------------------------------------------------------
# §35 — workflow variables
# ---------------------------------------------------------------------------

def test_render_variables_recursive():
    obj = {"path": "/data/{folder}/{name}.txt",
           "list": ["{contact}", "static"], "n": 5}
    out = render_variables(obj, {"folder": "docs", "name": "a",
                                 "contact": "Rahul"})
    assert out["path"] == "/data/docs/a.txt"
    assert out["list"] == ["Rahul", "static"]
    assert out["n"] == 5


def test_required_variables_detects_gaps():
    rendered = render_variables({"a": "{x} and {y}"}, {"x": "1"})
    assert required_variables(rendered) == {"y"}


def _ok_result():
    from tools.base import ToolResult
    return ToolResult.ok({"done": True})


def test_engine_runs_with_variables():
    seen = []

    async def run_fn(step, ctx):
        seen.append(step.arguments)
        return _ok_result()

    wf = Workflow(name="wf", steps=[WorkflowStep(
        tool="filesystem.write_file",
        arguments={"path": "/tmp/{name}.txt", "content": "hi"})])
    out = asyncio.run(WorkflowEngine(None).run(
        wf, variables={"name": "report"}, run_fn=run_fn))
    assert out["success"] is True
    assert seen[0]["path"] == "/tmp/report.txt"


def test_engine_refuses_missing_variables():
    wf = Workflow(name="wf", steps=[WorkflowStep(
        tool="filesystem.write_file",
        arguments={"path": "/tmp/{name}.txt"})])
    with pytest.raises(MissingWorkflowVariable):
        asyncio.run(WorkflowEngine(None).run(wf, variables={}))


def test_engine_condition_skips_step():
    ran = []

    async def run_fn(step, ctx):
        ran.append(step.tool)
        return _ok_result()

    wf = Workflow(name="wf", steps=[
        WorkflowStep(tool="a.ok", arguments={}),
        WorkflowStep(tool="a.only_on_failure", arguments={}, condition="failed"),
    ])
    out = asyncio.run(WorkflowEngine(None).run(wf, run_fn=run_fn))
    assert out["success"] is True
    assert ran == ["a.ok"]  # second step skipped (previous succeeded)


# ---------------------------------------------------------------------------
# §35 — planner end-to-end (saved workflow + spoken variables)
# ---------------------------------------------------------------------------

def test_planner_resolves_workflow_variables(runtime):
    from database.service import save_workflow
    with runtime.database.session() as s:
        save_workflow(s, "Photo Mover",
                      [{"tool": "whatsapp.download_media",
                        "arguments": {"contact": "{contact}",
                                      "destination": "{destination}"}}],
                      triggers=["photo routine"])
    plan = asyncio.run(runtime.planner.plan(
        "Run my photo routine from Rahul to Desktop", mode="smart"))
    args = plan.steps[0].arguments
    assert args["contact"] == "Rahul"
    assert args["destination"] == "Desktop"


def test_planner_missing_workflow_variables_fails_clearly(runtime):
    from core.exceptions import NovaError
    from database.service import save_workflow
    with runtime.database.session() as s:
        save_workflow(s, "Needy Flow",
                      [{"tool": "filesystem.write_file",
                        "arguments": {"path": "{target}/x.txt"}}],
                      triggers=["needy flow"])
    with pytest.raises(NovaError) as exc:
        asyncio.run(runtime.planner.plan("start needy flow", mode="smart"))
    assert "target" in str(exc.value)
