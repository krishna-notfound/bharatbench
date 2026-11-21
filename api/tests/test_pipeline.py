import asyncio
from pathlib import Path

import httpx
import pytest

from app import pipeline
from app.events import EventBus
from app.models import (
    HarnessJob,
    HarnessProfileResult,
    HarnessResult,
    HarnessScreen,
)
from app.services import RunServiceImpl
from app.storage.sqlite import SqliteStorage
from tests.conftest import make_apk_bytes


class FakeHarness:
    def __init__(self, *, health_error: Exception | None = None, poll_error: Exception | None = None):
        self.health_error = health_error
        self.poll_error = poll_error
        self.polls = 0
        self.cancelled = False
        self.closed = False

    async def health(self):
        if self.health_error:
            raise self.health_error
        return {"adb": True}

    async def submit(self, apk_path, request):
        return HarnessJob(job_id="j1", run_id=request.run_id, status="queued")

    async def poll(self, job_id):
        self.polls += 1
        if self.poll_error:
            raise self.poll_error
        done = self.polls >= 2
        return HarnessJob(
            job_id=job_id, run_id="x", status="done" if done else "running",
            current_profile=None if done else "baseline",
            events=["line1"] if self.polls == 1 else ["line1", "line2"],
        )

    async def result(self, job_id):
        return HarnessResult(
            job_id=job_id, device="emu",
            profiles=[
                HarnessProfileResult(
                    profile_id="baseline", applied=True, launched=True,
                    screens=[HarnessScreen(index=0, screenshot="baseline/screens/0.png")],
                    logcat="baseline/logcat.txt",
                )
            ],
        )

    async def download_artifact(self, job_id, path, dest: Path):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"data")

    async def cancel(self, job_id):
        self.cancelled = True
        return HarnessJob(job_id=job_id, run_id="x", status="cancelled")

    async def aclose(self):
        self.closed = True


@pytest.fixture(autouse=True)
def fast_poll(monkeypatch):
    monkeypatch.setattr(pipeline, "POLL_INTERVAL_S", 0.01)


@pytest.fixture
async def make_service(tmp_path):
    made = []

    async def _make(harness):
        storage = SqliteStorage(tmp_path / "p.db")
        await storage.init()
        service = RunServiceImpl(storage, EventBus(storage), tmp_path / "data", lambda: harness)
        made.append(storage)
        return service

    yield _make
    for s in made:
        await s.close()


async def wait_terminal(service, run_id, timeout=5.0):
    async def _loop():
        while True:
            run = await service.get_run(run_id)
            events = await service.list_events(run_id)
            if run.status in ("done", "failed", "cancelled") and events[-1].type in ("done", "error"):
                return run
            await asyncio.sleep(0.01)

    return await asyncio.wait_for(_loop(), timeout)


def write_apk(tmp_path: Path, data: bytes | None = None) -> str:
    p = tmp_path / "up.apk"
    p.write_bytes(make_apk_bytes() if data is None else data)
    return str(p)


async def test_no_harness_skips_runtime_but_done(make_service, fake_analyzer, tmp_path):
    service = await make_service(None)
    run = await service.create_run(write_apk(tmp_path), "up.apk", ["baseline"])
    done = await wait_terminal(service, run.id)
    assert done.status == "done"
    assert done.summary.runtime_executed is False
    assert "not configured" in done.summary.runtime_skipped_reason
    findings = await service.list_findings(run.id)
    assert [f.id for f in findings] == ["s2", "s1"]  # sorted by impact desc
    events = await service.list_events(run.id)
    assert events[-1].type == "done"
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    statuses = [e.data["status"] for e in events if e.type == "status"]
    assert statuses == ["queued", "analyzing", "scoring", "done"]
    assert any("skipped" in e.message for e in events if e.type == "log")


async def test_full_flow_with_harness(make_service, fake_analyzer, tmp_path):
    harness = FakeHarness()
    service = await make_service(harness)
    run = await service.create_run(write_apk(tmp_path), "up.apk", ["baseline"])
    done = await wait_terminal(service, run.id)
    assert done.status == "done"
    assert done.summary.runtime_executed is True
    assert done.summary.total_findings == 3
    events = await service.list_events(run.id)
    statuses = [e.data["status"] for e in events if e.type == "status"]
    assert statuses == ["queued", "analyzing", "provisioning", "running", "scoring", "done"]
    logs = [e.message for e in events if e.type == "log"]
    assert "line1" in logs and "line2" in logs
    assert logs.count("line1") == 1
    assert any(e.type == "step" and e.data["profile_id"] == "baseline" for e in events)
    arts = [e.data["path"] for e in events if e.type == "artifact"]
    assert sorted(arts) == ["baseline/0.png", "baseline/logcat.txt"]
    assert (tmp_path / "data" / "runs" / run.id / "artifacts" / "baseline" / "0.png").read_bytes() == b"data"
    assert harness.closed


async def test_corrupt_apk_ends_failed_not_hung(make_service, fake_analyzer, tmp_path):
    """Review focus 1: corrupt bytes named .apk -> run ends failed with a clear error."""
    service = await make_service(None)
    run = await service.create_run(write_apk(tmp_path, b"this is not a zip"), "bad.apk", ["baseline"])
    done = await wait_terminal(service, run.id)
    assert done.status == "failed"
    assert "not a valid APK" in done.error
    assert (await service.list_events(run.id))[-1].type == "error"


async def test_analyzer_exception_fails_run(make_service, monkeypatch, tmp_path):
    def boom(apk_path, run_id):
        raise ValueError("androguard exploded")

    monkeypatch.setattr(pipeline, "load_analyzer", lambda: (boom, lambda *a: []))
    service = await make_service(None)
    run = await service.create_run(write_apk(tmp_path), "x.apk", ["baseline"])
    done = await wait_terminal(service, run.id)
    assert done.status == "failed" and "androguard exploded" in done.error


async def test_missing_analyzer_fails_run_clearly(make_service, monkeypatch, tmp_path):
    def missing():
        raise ImportError("No module named 'app.analyzer'")

    monkeypatch.setattr(pipeline, "load_analyzer", missing)
    service = await make_service(None)
    run = await service.create_run(write_apk(tmp_path), "x.apk", ["baseline"])
    done = await wait_terminal(service, run.id)
    assert done.status == "failed" and "analyzer" in done.error


@pytest.mark.parametrize("where", ["health", "poll"])
async def test_harness_unreachable_still_done_with_static(make_service, fake_analyzer, tmp_path, where):
    """Review focus 2: harness ConnectError (at start or mid-run) -> done + static findings + reason."""
    err = httpx.ConnectError("connection refused")
    harness = FakeHarness(health_error=err) if where == "health" else FakeHarness(poll_error=err)
    service = await make_service(harness)
    run = await service.create_run(write_apk(tmp_path), "up.apk", ["baseline"])
    done = await wait_terminal(service, run.id)
    assert done.status == "done"
    assert done.summary.runtime_executed is False
    assert "unreachable" in done.summary.runtime_skipped_reason
    assert len(await service.list_findings(run.id)) == 2
    assert harness.closed


async def test_cancel_cancels_harness_job(make_service, fake_analyzer, tmp_path, monkeypatch):
    harness = FakeHarness()
    harness.polls = -10_000  # stays "running" for a long time
    monkeypatch.setattr(pipeline, "POLL_INTERVAL_S", 0.05)
    service = await make_service(harness)
    run = await service.create_run(write_apk(tmp_path), "up.apk", ["baseline"])
    for _ in range(200):
        if (await service.get_run(run.id)).status == "running":
            break
        await asyncio.sleep(0.01)
    result = await service.cancel_run(run.id)
    assert result.status == "cancelled"
    assert harness.cancelled
    assert (await service.list_events(run.id))[-1].type == "error"


async def test_recover_orphans_marks_failed(make_service, tmp_path):
    service = await make_service(None)
    from tests.conftest import make_run

    await service.storage.create_run(make_run("old", "running"), "x")
    await service.recover_orphans()
    run = await service.get_run("old")
    assert run.status == "failed" and run.error == "API restarted"
