"""API surface tests (FastAPI TestClient) — spec §31."""
import pytest
from api.app import build_app
from fastapi.testclient import TestClient
from runtime import Runtime


@pytest.fixture()
def client(tmp_path):
    # file-backed SQLite so the TestClient thread shares the DB with the runtime
    db_url = f"sqlite:///{tmp_path / 'api-test.db'}"
    rt = Runtime(for_testing=True, force_heuristic=True, db_url=db_url)
    rt.settings.load({"storage.data_dir": str(tmp_path)})
    app = build_app(rt)
    with TestClient(app) as c:
        c.app.state.runtime = rt
        yield c
    rt.shutdown()


def test_status_endpoint(client):
    r = client.get("/api/system/status")
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "IDLE"
    assert body["platform"] in ("Windows", "Linux", "Darwin")


def test_apps_catalog(client):
    r = client.get("/api/apps")
    assert r.status_code == 200
    assert len(r.json()["catalog"]) >= 80


def test_settings_roundtrip(client):
    r = client.put("/api/settings", json={"updates": {"desktop.theme": "light"}})
    assert r.status_code == 200
    r = client.get("/api/settings")
    assert r.json()["settings"]["desktop.theme"] == "light"


def test_plan_endpoint(client):
    r = client.post("/api/agent/plan", json={"command": "Open Chrome"})
    assert r.status_code == 200
    plan = r.json()["plan"]
    assert plan["steps"][0]["tool"] == "computer.launch_app"


def test_execute_and_wait(client):
    r = client.post("/api/agent/execute", json={"command": "Take a screenshot",
                                                "mode": "computer"})
    assert r.status_code == 200
    tid = r.json()["task_id"]
    r = client.get(f"/api/tasks/{tid}/wait", params={"timeout": 30})
    assert r.json()["task"]["status"] == "completed"


def test_tasks_history(client):
    r = client.get("/api/tasks")
    assert r.status_code == 200
    assert isinstance(r.json()["tasks"], list)


def test_memory_crud(client):
    client.post("/api/memory", json={"key": "resume", "value": "C:/resume.pdf"})
    r = client.get("/api/memory")
    assert r.json()["memories"]["facts"]["resume"] == "C:/resume.pdf"
    r = client.delete("/api/memory/resume")
    assert r.json()["deleted"] is True


def test_workflow_crud(client):
    client.post("/api/workflows", json={
        "name": "Start College Mode",
        "triggers": ["start college mode"],
        "steps": [{"tool": "computer.launch_app", "arguments": {"command": "code"}}]})
    r = client.get("/api/workflows")
    assert any(w["name"] == "Start College Mode" for w in r.json()["workflows"])


def test_direct_actions_locked_by_default(client):
    # V2 §56: direct tool invocation is disabled unless explicitly enabled
    r = client.post("/api/actions/not.a.tool", json={})
    assert r.status_code == 403


def test_direct_actions_unknown_tool_404(client):
    client.put("/api/settings",
               json={"updates": {"developer.direct_actions": True}})
    r = client.post("/api/actions/not.a.tool", json={})
    assert r.status_code == 404


def test_direct_actions_cannot_skip_confirmation(client):
    client.put("/api/settings",
               json={"updates": {"developer.direct_actions": True}})
    # a confirmation-required tool must NOT be fireable without a task
    r = client.post("/api/actions/filesystem.delete",
                    json={"arguments": {"paths": ["/tmp/nope.txt"]}})
    assert r.status_code == 409


def test_diagnostics_endpoint(client):
    r = client.get("/api/diagnostics")
    assert r.status_code == 200
    assert r.json()["summary"]["healthy"] is True


def test_events_history(client):
    r = client.get("/api/events")
    assert r.status_code == 200
    assert isinstance(r.json()["events"], list)


def test_health_endpoint(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["version"] == "2.0.0"
    assert body["uptime_seconds"] >= 0


def test_tasks_filter_by_status(client):
    # run one task that completes and one that fails
    c1 = client.post("/api/agent/execute", json={"command": "take a screenshot"})
    tid1 = c1.json()["task_id"]
    client.get(f"/api/tasks/{tid1}/wait?timeout=30")
    # filter returns only matching rows
    r = client.get("/api/tasks?limit=50&status=completed")
    assert r.status_code == 200
    for t in r.json()["tasks"]:
        assert t["status"] == "completed"


def test_dashboard_serves_shell(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "NOVA" in r.text
    # SPA boot script + stylesheet are served from /static
    assert "/static/app/main.js" in r.text
    assert "/static/app/styles.css" in r.text


def test_static_assets_served(client):
    for path, marker in (
        ("/static/app/main.js", "Control Center"),
        ("/static/app/styles.css", "--accent"),
        ("/static/app/api.js", "NOVA API client"),
        ("/static/app/views/command.js", "Command Console"),
    ):
        r = client.get(path)
        assert r.status_code == 200, path
        assert marker in r.text, path


def test_openapi_routes_are_tagged(client):
    spec = client.get("/openapi.json").json()
    assert spec["info"]["title"] == "NOVA Agent API"
    tagged = {p for p, ms in spec["paths"].items()
              for m in ms.values() if m.get("tags")}
    assert "/api/health" in tagged
    assert "/api/tasks" in tagged


def test_task_reports_waiting_confirmation_status(client):
    r = client.post("/api/agent/execute",
                    json={"command": "create a folder called conf-status-check"})
    tid = r.json()["task_id"]
    # wait until the confirmation prompt is registered
    conf = None
    for _ in range(40):
        confs = client.get("/api/confirmations").json()["confirmations"]
        conf = next((c for c in confs if c["task_id"] == tid), None)
        if conf:
            break
        import time as _t
        _t.sleep(0.25)
    assert conf is not None, "confirmation prompt never appeared"
    # the task record itself must advertise the waiting state
    task = client.get(f"/api/tasks/{tid}").json()["task"]
    assert task["status"] == "waiting_confirmation"
    # approving flips it back to executing then completes
    client.post(f"/api/confirmations/{conf['id']}", json={"approve": True})
    final = client.get(f"/api/tasks/{tid}/wait?timeout=30").json()["task"]
    assert final["status"] == "completed"
    import shutil
    shutil.rmtree("conf-status-check", ignore_errors=True)
