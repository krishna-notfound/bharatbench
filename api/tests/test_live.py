"""f20: live phone proxy + step replay (harness mocked)."""

import struct
from types import SimpleNamespace
from typing import ClassVar

import httpx
import pytest
from fastapi.testclient import TestClient

from app import pipeline
from app.live import write_steps
from app.main import create_app
from app.models import HarnessProfileResult, HarnessResult, HarnessScreen, HarnessStep
from tests.conftest import make_run

PNG = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 720, 1280) + b"\x08\x06\x00\x00\x00"


class FakeLive:
    def __init__(self, fail: bool = False, frame: bytes | None = PNG) -> None:
        self.fail, self.frame, self.closed = fail, frame, 0

    async def live(self, job_id):
        if self.fail:
            raise httpx.ConnectError("down")
        return {"seq": 3, "running": True, "profile_id": "baseline", "step_index": 1, "action": "tap",
                "target": "Login", "tap": {"x": 10, "y": 20}, "screen": {"w": 720, "h": 1280}, "job": job_id}  # fmt: skip

    async def live_png(self, job_id):
        if self.fail:
            raise httpx.ConnectError("down")
        return self.frame

    async def aclose(self):
        self.closed += 1


@pytest.fixture
def stub(settings, fake_analyzer, monkeypatch):
    runs = {"r1": make_run("r1", "running"), "r2": make_run("r2", "done")}
    live = FakeLive()
    svc = SimpleNamespace(_job_ids={"r1": "job1", "r2": "job2"}, _harness_factory=lambda: live)

    async def get_run(rid):
        return runs.get(rid)

    svc.get_run = get_run
    monkeypatch.setattr("app.routes.live.get_run_service", lambda: svc)
    with TestClient(create_app(settings)) as c:
        yield c, svc, runs, live


def test_live_proxies_active_run(stub):
    c, _, _, live = stub
    body = c.get("/api/runs/r1/live").json()
    assert body["running"] is True and body["job"] == "job1" and body["tap"] == {"x": 10, "y": 20}
    assert live.closed == 1
    r = c.get("/api/runs/r1/live.png")
    assert r.content == PNG and r.headers["cache-control"] == "no-store"


def test_live_not_running_when_done_or_no_job(stub):
    c, svc, _runs, _ = stub
    body = c.get("/api/runs/r2/live").json()
    assert body["running"] is False and body["reason"]
    assert c.get("/api/runs/r2/live.png").status_code == 404
    svc._job_ids.clear()
    assert c.get("/api/runs/r1/live").json()["running"] is False
    assert c.get("/api/runs/nope/live").status_code == 404


def test_live_harness_down_is_not_running(stub):
    c, svc, _, _ = stub
    svc._harness_factory = lambda: FakeLive(fail=True)
    body = c.get("/api/runs/r1/live").json()
    assert body["running"] is False and "not answering" in body["reason"]
    assert c.get("/api/runs/r1/live.png").status_code == 404


def test_live_no_frame_404(stub):
    c, svc, _, _ = stub
    svc._harness_factory = lambda: FakeLive(frame=None)
    assert c.get("/api/runs/r1/live.png").status_code == 404


def _result() -> HarnessResult:
    prof = HarnessProfileResult(
        profile_id="baseline", applied=True, launched=True,
        screens=[HarnessScreen(index=0, screenshot="baseline/baseline_0.png"),
                 HarnessScreen(index=1, screenshot="baseline/baseline_1.png")],
        steps=[HarnessStep(index=0, action="launch", ok=True, screen=0),
               HarnessStep(index=1, action="tap", target="Login", ok=True, x=100, y=200, screen=1)],
    )  # fmt: skip
    return HarnessResult(job_id="j", device="d", profiles=[prof])


def test_write_steps_and_replay_route(stub, settings):
    c, _, _runs, _ = stub
    art = settings.data_dir / "runs" / "r2" / "artifacts"
    (art / "baseline").mkdir(parents=True)
    (art / "baseline" / "baseline_0.png").write_bytes(PNG)
    write_steps(_result(), art)
    body = c.get("/api/runs/r2/replay").json()
    prof = body["profiles"][0]
    assert prof["profile_id"] == "baseline" and prof["screen"] == {"w": 720, "h": 1280}
    tap = prof["steps"][1]
    assert (tap["action"], tap["target"], tap["x"], tap["y"]) == ("tap", "Login", 100, 200)
    assert tap["screenshot"] == "baseline/baseline_1.png" and prof["steps"][0]["screenshot"] == "baseline/baseline_0.png"
    assert c.get("/api/runs/r1/replay").json()["profiles"] == []


async def test_pipeline_download_writes_steps(tmp_path):
    class _Bus:
        async def publish(self, *a, **k):
            return None

    class H:
        async def download_artifact(self, job_id, path, dest):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(PNG)

    raw = _result()
    for p in raw.profiles:
        for s in p.screens:
            s.screenshot = f"screens/{s.screenshot.split('/')[-1]}"
    out = await pipeline._download_artifacts(H(), _Bus(), "r2", "j", raw, tmp_path)
    assert (tmp_path / "baseline" / "steps.json").is_file()
    assert out.profiles[0].steps[1].screen == 1



# ---- f24: human-in-the-loop input ----
class FakeInput(FakeLive):
    sent: ClassVar[list] = []

    async def live(self, job_id):
        d = await super().live(job_id)
        d.update(waiting_for_input=True, input_request={"request_id": "q1", "fields": [{"key": "email", "label": "Email", "kind": "email", "secret": False}]})
        return d

    async def send_input(self, job_id, request_id, values, skip):
        FakeInput.sent.append((job_id, request_id, values, skip))
        return request_id == "q1"


def test_live_passes_input_request_through(stub):
    c, svc, _, _ = stub
    svc._harness_factory = lambda: FakeInput()
    body = c.get("/api/runs/r1/live").json()
    assert body["waiting_for_input"] and body["input_request"]["request_id"] == "q1"


def test_input_forwarded_validated_and_never_stored(stub):
    c, svc, _, _ = stub
    FakeInput.sent = []
    svc._harness_factory = lambda: FakeInput()
    published = []

    async def publish(run_id, kind, msg, data=None):
        published.append(msg)

    svc.bus = SimpleNamespace(publish=publish)
    pw = "Sup3rSecret!"
    r = c.post("/api/runs/r1/input", json={"request_id": "q1", "values": {"password": pw}})
    assert r.status_code == 200 and FakeInput.sent == [("job1", "q1", {"password": pw}, False)]
    assert published == ["You filled 1 field (hidden)"] and pw not in "".join(published)
    assert c.post("/api/runs/r1/input", json={"request_id": "q1", "skip": True}).status_code == 200
    assert published[-1] == "Skipped"
    assert c.post("/api/runs/r1/input", json={"request_id": "old", "values": {"a": "b"}}).status_code == 409
    big = c.post("/api/runs/r1/input", json={"request_id": "q1", "values": {"a": "x" * 500 + pw}})
    assert big.status_code == 422 and pw not in big.text
    assert c.post("/api/runs/r1/input", json={"request_id": "q1", "values": {}}).status_code == 422
    assert c.post("/api/runs/r2/input", json={"request_id": "q1", "values": {"a": "b"}}).status_code == 503
    assert c.post("/api/runs/nope/input", json={"request_id": "q1", "skip": True}).status_code == 404
