"""f18: a run always finishes with a human reason (stalled harness, dead harness, restart, disk guard)."""

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app import pipeline
from app.events import EventBus
from app.harness_client import HarnessClient
from app.models import HarnessJob, HarnessProfileResult, HarnessResult
from app.services import RunServiceImpl
from app.storage.sqlite import SqliteStorage
from tests.conftest import make_apk_bytes, make_run
from tests.test_pipeline import wait_terminal


class ScriptHarness:
    """Harness whose poll() follows a script; after the script ends the last job state repeats."""

    def __init__(self, states=None, *, health=None, result=None, poll_errors_after=None, cancel_ends=True):
        self.states = states or [HarnessJob(job_id="j1", run_id="x", status="running", current_profile="budget_2gb")]
        self.health_info = health or {"adb": True, "disk_free_mb": 5000}
        self._result = result
        self.polls = 0
        self.cancelled = False
        self.deleted: str | None = None
        self.poll_errors_after = poll_errors_after
        self.cancel_ends = cancel_ends
        self.closed = False

    async def health(self):
        return self.health_info

    async def submit(self, apk_path, request):
        return HarnessJob(job_id="j1", run_id=request.run_id, status="queued")

    async def poll(self, job_id):
        self.polls += 1
        if self.poll_errors_after is not None and self.polls > self.poll_errors_after:
            raise httpx.ConnectError("connection refused")
        if self.cancelled and self.cancel_ends:
            return HarnessJob(job_id=job_id, run_id="x", status="cancelled")
        return self.states[min(self.polls - 1, len(self.states) - 1)]

    async def result(self, job_id):
        if self._result is None:
            raise httpx.HTTPStatusError("409", request=httpx.Request("GET", "http://h"), response=httpx.Response(409))
        return self._result

    async def download_artifact(self, job_id, path, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"x")

    async def cancel(self, job_id):
        self.cancelled = True
        return HarnessJob(job_id=job_id, run_id="x", status="cancelled")

    async def delete(self, job_id):
        self.deleted = job_id

    async def aclose(self):
        self.closed = True


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(pipeline, "POLL_INTERVAL_S", 0.01)
    monkeypatch.setattr(pipeline, "UNREACHABLE_GRACE_S", 0.05)
    monkeypatch.setattr(pipeline, "SALVAGE_WAIT_S", 0.5)


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


def apk(tmp_path) -> str:
    p = tmp_path / "up.apk"
    p.write_bytes(make_apk_bytes())
    return str(p)


async def logs(service, run_id) -> list[str]:
    return [e.message for e in await service.list_events(run_id) if e.type == "log"]


async def test_stalled_harness_ends_done_with_human_reason(make_service, fake_analyzer, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "STALL_TIMEOUT_S", 0.15)
    h = ScriptHarness()
    service = await make_service(h)
    run = await service.create_run(apk(tmp_path), "up.apk", ["budget_2gb"])
    done = await wait_terminal(service, run.id)
    assert done.status == "done"
    assert done.summary.runtime_executed is False
    reason = done.summary.runtime_skipped_reason
    assert "stopped responding" in reason and "Budget phone, 2 Mbps" in reason and "static results" in reason
    assert h.cancelled and h.deleted == "j1" and h.closed
    assert len(await service.list_findings(run.id)) == 2  # static findings preserved
    msgs = await logs(service, run.id)
    assert any(m.startswith("Watchdog:") for m in msgs) and any(m.startswith("Recovery:") for m in msgs)


async def test_changing_events_keep_the_run_alive(make_service, fake_analyzer, tmp_path, monkeypatch):
    """Progress resets the stall clock: slow but moving is not stuck."""
    monkeypatch.setattr(pipeline, "STALL_TIMEOUT_S", 0.3)
    running = [
        HarnessJob(job_id="j1", run_id="x", status="running", current_profile="baseline", events=["e"] * n)
        for n in range(1, 40)
    ]
    h = ScriptHarness([*running, HarnessJob(job_id="j1", run_id="x", status="done")], result=HarnessResult(
        job_id="j1", device="d", profiles=[HarnessProfileResult(profile_id="baseline", applied=True, launched=True)]
    ))
    service = await make_service(h)
    run = await service.create_run(apk(tmp_path), "up.apk", ["baseline"])
    done = await wait_terminal(service, run.id, timeout=10)
    assert done.summary.runtime_executed is True and h.deleted == "j1"


async def test_total_runtime_cap(make_service, fake_analyzer, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "HARNESS_TIMEOUT_S", 0.2)
    monkeypatch.setattr(pipeline, "STALL_TIMEOUT_S", 100)
    moving = [
        HarnessJob(job_id="j1", run_id="x", status="running", current_profile="baseline", events=["e"] * n)
        for n in range(1, 2000)
    ]
    h = ScriptHarness(moving)
    service = await make_service(h)
    run = await service.create_run(apk(tmp_path), "up.apk", ["baseline"])
    done = await wait_terminal(service, run.id)
    assert done.status == "done" and not done.summary.runtime_executed
    assert "took longer than" in done.summary.runtime_skipped_reason and h.cancelled


async def test_partial_results_kept_for_completed_profiles(make_service, fake_analyzer, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "STALL_TIMEOUT_S", 0.1)
    partial = HarnessResult(
        job_id="j1", device="d",
        profiles=[
            HarnessProfileResult(profile_id="baseline", applied=True, launched=True),
            HarnessProfileResult(profile_id="budget_2gb", applied=False, launched=False, apply_note="phone stopped"),
        ],
    )  # fmt: skip
    seen = {}

    def runtime_findings(run_id, result, package="pkg"):
        seen["profiles"] = [p.profile_id for p in result.profiles]
        return []

    monkeypatch.setattr(pipeline, "load_analyzer", lambda: (_static, runtime_findings))
    h = ScriptHarness(result=partial)
    h.cancel_ends = True
    service = await make_service(h)
    run = await service.create_run(apk(tmp_path), "up.apk", ["baseline", "budget_2gb"])
    done = await wait_terminal(service, run.id)
    assert done.status == "done" and done.summary.runtime_executed is False
    assert seen["profiles"] == ["baseline"]  # only the profile that really ran
    assert any("partial results" in m for m in await logs(service, run.id))


def _static(apk_path, run_id):
    from app.models import AppInfo
    from tests.conftest import make_finding

    return AppInfo(package_name="com.example.app", main_activity=".Main", size_bytes=10), [make_finding("s1", run_id)]


async def test_harness_dies_mid_run(make_service, fake_analyzer, tmp_path):
    h = ScriptHarness(poll_errors_after=2)
    service = await make_service(h)
    run = await service.create_run(apk(tmp_path), "up.apk", ["baseline"])
    done = await wait_terminal(service, run.id)
    assert done.status == "done" and not done.summary.runtime_executed
    assert "stopped answering" in done.summary.runtime_skipped_reason
    assert len(await service.list_findings(run.id)) == 2


async def test_failed_harness_job_gives_human_reason(make_service, fake_analyzer, tmp_path):
    h = ScriptHarness([HarnessJob(job_id="j1", run_id="x", status="failed", error="phone offline")])
    service = await make_service(h)
    run = await service.create_run(apk(tmp_path), "up.apk", ["baseline"])
    done = await wait_terminal(service, run.id)
    assert done.status == "done" and "phone offline" in done.summary.runtime_skipped_reason
    assert h.deleted == "j1"


async def test_low_disk_skips_runtime_but_keeps_static(make_service, fake_analyzer, tmp_path):
    h = ScriptHarness(health={"adb": True, "disk_free_mb": 120})
    service = await make_service(h)
    run = await service.create_run(apk(tmp_path), "up.apk", ["baseline"])
    done = await wait_terminal(service, run.id)
    assert done.status == "done" and not done.summary.runtime_executed
    assert "test lab is cleaning up" in done.summary.runtime_skipped_reason
    assert h.polls == 0 and h.deleted is None
    assert len(await service.list_findings(run.id)) == 2


async def test_busy_harness_409_has_friendly_reason(make_service, fake_analyzer, tmp_path):
    h = ScriptHarness()

    async def busy(apk_path, request):
        raise httpx.HTTPStatusError("409", request=httpx.Request("POST", "http://h"), response=httpx.Response(409))

    h.submit = busy
    service = await make_service(h)
    run = await service.create_run(apk(tmp_path), "up.apk", ["baseline"])
    done = await wait_terminal(service, run.id)
    assert "busy with another run" in done.summary.runtime_skipped_reason


# ---- startup recovery + watchdog ----


async def test_startup_recovery_finishes_orphans_with_reason_and_stops_harness_job(make_service):
    h = ScriptHarness()
    service = await make_service(h)
    await service.storage.create_run(make_run("old", "running"), "x")
    await service.storage.create_run(make_run("fine", "done"), "x")
    await service.bus.publish("old", "log", "Test phone job started", {"job_id": "jobX"})
    assert await service.recover_orphans() == 1
    run = await service.get_run("old")
    assert run.status == "failed" and "server restarted" in run.error and "start it again" in run.error
    events = await service.list_events("old")
    assert any(e.type == "status" and e.data["status"] == "failed" for e in events)
    assert any(e.type == "log" and e.message.startswith("Recovery:") for e in events)
    assert h.cancelled and h.deleted == "jobX" and h.closed
    assert (await service.get_run("fine")).status == "done"


async def test_watchdog_sweeps_wedged_run(make_service, monkeypatch):
    service = await make_service(None)
    stale = make_run("wedged", "running").model_copy(update={"updated_at": datetime.now(UTC) - timedelta(hours=1)})
    await service.storage.create_run(stale, "x")
    await service.storage.create_run(make_run("active", "running"), "x")
    assert await service.sweep_stuck() == 1
    run = await service.get_run("wedged")
    assert run.status == "failed" and "stopped making progress" in run.error
    assert (await service.get_run("active")).status == "running"


async def test_watchdog_kills_hung_task_and_replaces_cancelled_with_reason(make_service, tmp_path):
    service = await make_service(None)
    stale = make_run("hung", "analyzing").model_copy(update={"updated_at": datetime.now(UTC) - timedelta(hours=1)})
    await service.storage.create_run(stale, "x")

    async def hang():
        try:
            await asyncio.sleep(1000)
        except asyncio.CancelledError:
            await service.storage.update_run((await service.get_run("hung")).model_copy(update={"status": "cancelled"}))
            raise

    service._tasks["hung"] = asyncio.create_task(hang())
    await asyncio.sleep(0)
    await service.sweep_stuck()
    run = await service.get_run("hung")
    assert run.status == "failed" and "stopped making progress" in run.error


# ---- client ----


async def test_client_delete_tolerates_404_and_raises_others():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE" and request.headers["x-harness-token"] == "tok"
        return httpx.Response({"gone": 404, "busy": 409}.get(request.url.path.rsplit("/", 1)[1], 200))

    c = HarnessClient("http://h", "tok")
    c._client = httpx.AsyncClient(
        base_url="http://h", headers={"X-Harness-Token": "tok"}, transport=httpx.MockTransport(handler)
    )
    await c.delete("ok")
    await c.delete("gone")
    with pytest.raises(httpx.HTTPStatusError):
        await c.delete("busy")
    await c.aclose()


async def test_stop_keeps_completed_conditions(make_service, fake_analyzer, tmp_path):
    result = HarnessResult(
        job_id="j1", device="d",
        profiles=[HarnessProfileResult(profile_id="baseline", applied=True, launched=True)],
    )
    h = ScriptHarness(result=result)
    service = await make_service(h)
    run = await service.create_run(apk(tmp_path), "up.apk", ["baseline", "budget_2gb", "flaky_network"])
    for _ in range(300):
        if (await service.get_run(run.id)).status == "running":
            break
        await asyncio.sleep(0.01)
    await service.cancel_run(run.id)
    done = await wait_terminal(service, run.id)
    assert done.status == "done" and done.summary.runtime_executed is True
    reason = done.summary.runtime_skipped_reason
    assert reason.startswith("Stopped early after 1 of 3 conditions (")
    assert "Not tested:" in reason and h.cancelled and h.deleted == "j1"
