import time

import pytest
from fastapi.testclient import TestClient

from app import pipeline
from app.main import create_app
from tests.conftest import make_apk_bytes


@pytest.fixture
def client(settings, fake_analyzer):
    with TestClient(create_app(settings)) as c:
        yield c


def upload(client, data=None, name="app.apk", profiles=None):
    form = {"profiles": profiles} if profiles else None
    return client.post(
        "/api/runs", files={"apk": (name, make_apk_bytes() if data is None else data)}, data=form
    )


def wait_done(client, run_id, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in ("done", "failed", "cancelled"):
            return run
        time.sleep(0.02)
    raise AssertionError("run did not finish")


def test_health_unconfigured(client):
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["harness"]["configured"] is False
    assert body["harness"]["reachable"] is False
    assert body["sarvam_configured"] is False


def test_profiles(client):
    ids = [p["id"] for p in client.get("/api/profiles").json()]
    assert ids[0] == "baseline" and len(ids) == 6


def test_upload_rejects_non_apk(client):
    r = upload(client, name="app.zip")
    assert r.status_code == 400


def test_upload_unknown_profile_422(client):
    assert upload(client, profiles="baseline,nope").status_code == 422


def test_upload_too_large_413(client, monkeypatch):
    from app.routes import runs

    monkeypatch.setattr(runs, "MAX_APK_BYTES", 10)
    r = upload(client, data=b"PK" + b"x" * 100)
    assert r.status_code == 413


def test_upload_non_zip_400(client):
    r = upload(client, data=b"hello world, definitely not an apk")
    assert r.status_code == 400


def test_upload_creates_run_and_finishes(client):
    r = upload(client, profiles="baseline,budget_2gb")
    assert r.status_code == 201
    run = r.json()
    assert run["status"] == "queued" and run["profile_ids"] == ["baseline", "budget_2gb"]
    done = wait_done(client, run["id"])
    assert done["status"] == "done"
    assert done["summary"]["runtime_executed"] is False
    assert done["app"]["package_name"] == "com.example.app"
    assert client.get("/api/runs").json()[0]["id"] == run["id"]
    findings = client.get(f"/api/runs/{run['id']}/findings").json()
    scores = [f["impact"]["score"] for f in findings]
    assert scores == sorted(scores, reverse=True) and len(scores) == 2
    events = client.get(f"/api/runs/{run['id']}/events", params={"after_seq": 2}).json()
    assert events and all(e["seq"] > 2 for e in events)
    md = client.get(f"/api/runs/{run['id']}/report.md")
    assert md.status_code == 200 and "text/markdown" in md.headers["content-type"]
    assert "Finding s2" in md.text and "Assumptions" in md.text


def test_default_profiles(client):
    run = upload(client).json()
    assert run["profile_ids"] == ["baseline", "budget_2gb", "flaky_network"]


def test_unknown_run_404(client):
    for path in ("", "/findings", "/events", "/report.md"):
        assert client.get(f"/api/runs/missing{path}").status_code == 404
    assert client.post("/api/runs/missing/cancel").status_code == 404


def test_artifact_serving_and_traversal(client, settings):
    run = upload(client).json()
    wait_done(client, run["id"])
    art = settings.data_dir / "runs" / run["id"] / "artifacts"
    (art / "baseline").mkdir(parents=True)
    (art / "baseline" / "0.png").write_bytes(b"png")
    ok = client.get(f"/api/runs/{run['id']}/artifacts/baseline/0.png")
    assert ok.status_code == 200 and ok.content == b"png"
    assert client.get(f"/api/runs/{run['id']}/artifacts/%2e%2e/%2e%2e/app.apk").status_code == 400
    assert client.get(f"/api/runs/{run['id']}/artifacts/..%2f..%2fapp.apk").status_code == 400
    assert client.get(f"/api/runs/{run['id']}/artifacts/nope.png").status_code == 404


def test_corrupt_apk_run_failed(client):
    run = upload(client, data=b"PK\x03\x04garbage").json()
    done = wait_done(client, run["id"])
    assert done["status"] == "failed" and done["error"]


def test_ws_late_client_gets_history_then_done(client):
    """Review focus 4: connecting after the run finished yields full history ending in done."""
    run = upload(client).json()
    wait_done(client, run["id"])
    with client.websocket_connect(f"/ws/runs/{run['id']}") as ws:
        events = []
        while True:
            ev = ws.receive_json()
            events.append(ev)
            if ev["type"] in ("done", "error"):
                break
        assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
        assert events[0]["type"] == "status" and events[-1]["type"] == "done"
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


def test_ws_live_client_receives_until_done(client, monkeypatch):
    real = pipeline.load_analyzer()

    def slow_analyze(apk_path, run_id):
        time.sleep(0.3)
        return real[0](apk_path, run_id)

    monkeypatch.setattr(pipeline, "load_analyzer", lambda: (slow_analyze, real[1]))
    run = upload(client).json()
    with client.websocket_connect(f"/ws/runs/{run['id']}") as ws:
        seqs = []
        while True:
            ev = ws.receive_json()
            seqs.append(ev["seq"])
            if ev["type"] == "done":
                break
    assert seqs == list(range(1, len(seqs) + 1))


def test_ws_unknown_run_closes(client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws/runs/nope") as ws:
        ws.receive_json()


def test_rerun_copies_apk(client):
    run = upload(client).json()
    wait_done(client, run["id"])
    from app.services import get_run_service

    # exercised via the service in the app's own loop through the portal
    async def go():
        return await get_run_service().rerun(run["id"], ["baseline"])

    new = client.portal.call(go)
    assert new.id != run["id"] and new.apk_name == "app.apk"
    assert wait_done(client, new.id)["status"] == "done"
