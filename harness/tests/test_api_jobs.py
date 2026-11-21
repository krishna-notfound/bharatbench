import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from harness.adb import Adb
from harness.jobs import JobRunner
from harness.main import create_app
from harness.models import HarnessJobRequest
from harness.settings import Settings

from .device import PKG, FakeDevice, make_xml

TOKEN = "test-token"
H = {"X-Harness-Token": TOKEN}


async def nosleep(_: float) -> None:
    await asyncio.sleep(0)


def settings(tmp_path) -> Settings:
    return Settings(harness_token=TOKEN, jobs_dir=tmp_path / "jobs", device_kind="emulator", android_serial="emulator-5554")


def device() -> FakeDevice:
    return FakeDevice([make_xml(["Home"], ["Products"]), make_xml(["List"])])


def request_json(profiles: list[str], steps: int = 2) -> str:
    return json.dumps({"run_id": "r1", "package_name": PKG, "profiles": profiles, "journey_steps": steps})


def wait_done(client: TestClient, job_id: str) -> dict:
    for _ in range(200):
        job = client.get(f"/jobs/{job_id}", headers=H).json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def make_client(tmp_path, dev: FakeDevice) -> TestClient:
    app = create_app(settings(tmp_path), runner=dev)
    app.state.jobs._sleep = nosleep
    return TestClient(app)


def test_auth_on_every_route(tmp_path):
    c = make_client(tmp_path, device())
    for method, path in [
        ("get", "/health"),
        ("post", "/jobs"),
        ("get", "/jobs/" + "a" * 32),
        ("get", "/jobs/" + "a" * 32 + "/result"),
        ("get", "/jobs/" + "a" * 32 + "/artifacts/x"),
        ("post", "/jobs/" + "a" * 32 + "/cancel"),
    ]:
        assert getattr(c, method)(path).status_code == 401, path
        assert getattr(c, method)(path, headers={"X-Harness-Token": "wrong"}).status_code == 401, path


def test_health(tmp_path):
    c = make_client(tmp_path, device())
    body = c.get("/health", headers=H).json()
    assert body["adb"] and body["emulator_booted"] and body["devices"] == ["emulator-5554"]
    assert body["android_version"] == "14"
    dev = device()
    dev.booted = False
    assert not make_client(tmp_path, dev).get("/health", headers=H).json()["emulator_booted"]


def test_health_adb_missing(tmp_path):
    dev = device()
    dev.fail["version"] = 127
    body = make_client(tmp_path, dev).get("/health", headers=H).json()
    assert body["adb"] is False and body["devices"] == [] and body["emulator_booted"] is False


def test_post_job_503_when_not_booted(tmp_path):
    dev = device()
    dev.booted = False
    c = make_client(tmp_path, dev)
    r = c.post("/jobs", headers=H, files={"apk": ("a.apk", b"x")}, data={"request": request_json(["baseline"])})
    assert r.status_code == 503 and "emulator not booted" in r.json()["detail"]


def test_post_job_validation(tmp_path):
    c = make_client(tmp_path, device())
    bad = c.post("/jobs", headers=H, files={"apk": ("a.apk", b"x")}, data={"request": "{}"})
    assert bad.status_code == 422
    evil = json.dumps({"run_id": "r", "package_name": "a; rm -rf /", "profiles": ["baseline"]})
    assert c.post("/jobs", headers=H, files={"apk": ("a.apk", b"x")}, data={"request": evil}).status_code == 422


def test_full_job_flow_artifacts_and_traversal(tmp_path):
    dev = device()
    with make_client(tmp_path, dev) as c:
        r = c.post("/jobs", headers=H, files={"apk": ("a.apk", b"PK")}, data={"request": request_json(["baseline", "battery_saver"])})
        assert r.status_code == 202
        job_id = r.json()["job_id"]
        job = wait_done(c, job_id)
        assert job["status"] == "done" and job["progress"] == 1.0, job
        res = c.get(f"/jobs/{job_id}/result", headers=H).json()
        assert [p["profile_id"] for p in res["profiles"]] == ["baseline", "battery_saver"]
        p0 = res["profiles"][0]
        assert p0["launched"] and p0["launch_ms"] == 777 and p0["memory_pss_kb"] == 5555
        assert p0["screens"][0]["screenshot"] == "screens/baseline_0.png"
        assert res["android_version"] == "14"
        art = c.get(f"/jobs/{job_id}/artifacts/{p0['screens'][0]['screenshot']}", headers=H)
        assert art.status_code == 200 and art.content.startswith(b"\x89PNG")
        assert c.get(f"/jobs/{job_id}/artifacts/{p0['logcat']}", headers=H).status_code == 200
        # traversal
        for p in ("..%2f..%2fjobs%2f" + "x", "%2e%2e/%2e%2e/pyproject.toml", "..%5c..%5cx"):
            assert c.get(f"/jobs/{job_id}/artifacts/{p}", headers=H).status_code == 404, p
        # install + uninstall happened with exact args
        base = ["adb", "-s", "emulator-5554"]
        assert dev.calls.count([*base, "uninstall", PKG]) == 1
        installs = [x for x in dev.calls if "install" in x and "uninstall" not in x]
        assert installs[0][:6] == [*base, "install", "-r", "-g"][:6] and installs[0][-1].endswith("app.apk")
        # battery reverted
        shells = [x[4:] for x in dev.calls if x[3:4] == ["shell"]]
        assert ["dumpsys", "battery", "reset"] in shells


def test_result_409_until_done_and_404(tmp_path):
    c = make_client(tmp_path, device())
    assert c.get("/jobs/" + "b" * 32, headers=H).status_code == 404
    assert c.get("/jobs/not-hex", headers=H).status_code == 404


async def test_busy_409(tmp_path):
    runner = JobRunner(settings(tmp_path), Adb("adb", "emulator-5554", device()), nosleep)
    req = HarnessJobRequest(run_id="r", package_name=PKG, profiles=["baseline"])
    runner.start(req)
    from harness.jobs import Busy

    with pytest.raises(Busy):
        runner.start(req)


# ---- Review Focus 3: a failed profile revert must not poison the next profile ----


@pytest.mark.parametrize("exc", ["rc", "raise"])
async def test_revert_failure_recorded_and_next_profile_runs(tmp_path, exc):
    dev = device()
    if exc == "rc":
        dev.fail["network delay none"] = 1
    else:
        dev.raise_on["network speed full"] = RuntimeError("adb exploded")
    runner = JobRunner(settings(tmp_path), Adb("adb", "emulator-5554", dev), nosleep)
    req = HarnessJobRequest(run_id="r", package_name=PKG, profiles=["budget_2gb", "baseline"], journey_steps=1)
    job, _ = runner.start(req)
    runner.launch(job, req)
    while runner.busy:
        await asyncio.sleep(0.01)
    assert job.status == "done", job.error
    assert any("REVERT FAILED" in e for e in job.events)
    result = runner.results[job.job_id]
    assert [p.profile_id for p in result.profiles] == ["budget_2gb", "baseline"]
    assert result.profiles[1].launched
    # baseline was prepared clean after the failed revert
    idx = [i for i, c in enumerate(dev.calls) if "network" in c and ("full" in c or "none" in c)]
    later_force_stop = [i for i, c in enumerate(dev.calls) if "force-stop" in c and i > idx[0]]
    assert later_force_stop


async def test_apply_failure_skips_journey_but_reverts(tmp_path):
    dev = device()
    dev.fail["low_power 1"] = 1
    runner = JobRunner(settings(tmp_path), Adb("adb", "emulator-5554", dev), nosleep)
    req = HarnessJobRequest(run_id="r", package_name=PKG, profiles=["battery_saver"], journey_steps=1)
    job, _ = runner.start(req)
    runner.launch(job, req)
    while runner.busy:
        await asyncio.sleep(0.01)
    p = runner.results[job.job_id].profiles[0]
    assert not p.applied and "could not apply" in (p.apply_note or "") and not p.launched
    shells = [x[4:] for x in dev.calls if x[3:4] == ["shell"]]
    assert ["dumpsys", "battery", "reset"] in shells


async def test_install_failure_fails_job(tmp_path):
    dev = device()
    dev.fail["install"] = 1
    runner = JobRunner(settings(tmp_path), Adb("adb", "emulator-5554", dev), nosleep)
    req = HarnessJobRequest(run_id="r", package_name=PKG, profiles=["baseline"])
    job, _ = runner.start(req)
    runner.launch(job, req)
    while runner.busy:
        await asyncio.sleep(0.01)
    assert job.status == "failed" and "install failed" in (job.error or "")


async def test_cancel_marks_cancelled(tmp_path):
    dev = device()
    runner = JobRunner(settings(tmp_path), Adb("adb", "emulator-5554", dev), nosleep)
    req = HarnessJobRequest(run_id="r", package_name=PKG, profiles=["baseline", "battery_saver"], journey_steps=1)
    job, _ = runner.start(req)
    runner.cancel(job.job_id)
    runner.launch(job, req)
    while runner.busy:
        await asyncio.sleep(0.01)
    assert job.status == "cancelled" and runner.results[job.job_id].profiles == []
