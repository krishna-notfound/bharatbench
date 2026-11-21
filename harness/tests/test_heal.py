"""Health gate, self-repair, mid-job recovery and DELETE /jobs, all against a scripted fake phone."""

import asyncio
import os
import time

import pytest
from fastapi.testclient import TestClient

from harness.adb import Adb
from harness.jobs import JobRunner
from harness.main import create_app
from harness.models import HarnessJobRequest
from harness.settings import Settings

from .device import PKG, FakeDevice, make_xml
from .test_api_jobs import H, nosleep, request_json, wait_done

SERIAL = "127.0.0.1:5555"


class Phone(FakeDevice):
    """FakeDevice plus adb connection state, a docker container and a repair log."""

    def __init__(self) -> None:
        super().__init__([make_xml(["Home"], ["Products"]), make_xml(["List"])])
        self.adb_up = True
        self.container = True
        self.heals_on = "docker"  # which repair brings it back: "reconnect" | "docker" | "never"
        self.docker_calls: list[str] = []
        self.offline_during: str | None = None  # drop adb the first time this substring is seen
        self.data_free_kb = 5_000_000

    async def __call__(self, argv, timeout):
        joined = " ".join(argv)
        if argv[0] == "docker":
            self.docker_calls.append(argv[1])
            if argv[1] == "inspect":
                return 0, (b"true\n" if self.container else b"false\n"), b""
            if argv[1] == "restart":
                if self.heals_on == "docker":
                    self.container, self.adb_up, self.booted = True, True, True
                return 0, b"redroid\n", b""
        if self.offline_during and self.offline_during in joined and self.adb_up:
            self.adb_up, self.offline_during = False, None
        rest = argv[3:] if argv[1:2] == ["-s"] else argv[1:]
        if argv[1:2] == ["connect"] or rest[:1] == ["reconnect"]:
            if self.heals_on == "reconnect" and (self.container):
                self.adb_up, self.booted = True, True
            return 0, b"connected\n", b""
        if argv[1] == "devices":
            return 0, f"List of devices attached\n{SERIAL}\tdevice\n".encode(), b""
        if argv[0] == "adb" and not self.adb_up and argv[1] != "version":
            return 1, b"", b"error: device offline"
        if rest[:3] == ["shell", "df", "-k"] and "/data" in rest:
            return 0, f"Filesystem 1K-blocks Used Available\n/dev/x 9 9 {self.data_free_kb} 1% /data\n".encode(), b""
        return await super().__call__(argv, timeout)


def cfg(tmp_path, **kw) -> Settings:
    base = {
        "harness_token": "test-token", "jobs_dir": tmp_path / "jobs", "device_kind": "redroid",
        "android_serial": SERIAL, "boot_timeout_s": 1, "reconnect_wait_s": 1, "profile_timeout_s": 5,
    }  # fmt: skip
    return Settings(**{**base, **kw})


def runner(tmp_path, phone, free_mb=5000.0, **kw) -> JobRunner:
    return JobRunner(cfg(tmp_path, **kw), Adb("adb", SERIAL, phone), nosleep, disk_probe=lambda _p: free_mb)


async def run_job(jr: JobRunner, profiles=("baseline",)):
    req = HarnessJobRequest(run_id="r", package_name=PKG, profiles=list(profiles), journey_steps=1)
    job, _ = jr.start(req)
    jr.launch(job, req)
    while jr.busy:
        await asyncio.sleep(0.01)
    return job


async def test_healthy_gate_makes_no_repair(tmp_path):
    phone = Phone()
    jr = runner(tmp_path, phone)
    job = await run_job(jr)
    assert job.status == "done" and jr.doctor.last_repair is None
    assert "restart" not in phone.docker_calls
    assert not any(e.startswith("DEVICE:") for e in job.events)


async def test_adb_offline_reconnect_repairs_without_docker_restart(tmp_path):
    phone = Phone()
    phone.adb_up, phone.heals_on = False, "reconnect"
    jr = runner(tmp_path, phone)
    job = await run_job(jr)
    assert job.status == "done", job.error
    assert "restart" not in phone.docker_calls
    assert jr.doctor.last_repair["ok"] and "reconnected adb" in jr.doctor.last_repair["actions"]
    assert any(e.startswith("DEVICE:") and "reconnect" in e for e in job.events)


async def test_container_down_restarts_docker_and_waits_for_boot(tmp_path):
    phone = Phone()
    phone.container, phone.adb_up, phone.booted = False, False, False
    jr = runner(tmp_path, phone)
    job = await run_job(jr)
    assert job.status == "done", job.error
    assert "restart" in phone.docker_calls
    assert "restarted phone container" in jr.doctor.last_repair["actions"]
    assert any("restarting the phone" in e for e in job.events)


async def test_unrepairable_phone_fails_job_with_human_reason(tmp_path):
    phone = Phone()
    phone.adb_up, phone.booted, phone.heals_on = False, False, "never"
    jr = runner(tmp_path, phone)
    job = await run_job(jr)
    assert job.status == "failed" and "test phone is not responding" in (job.error or "")
    assert jr.doctor.last_repair["ok"] is False
    assert any(e.startswith("DEVICE: repair failed") for e in job.events)
    assert not jr.busy


async def test_low_disk_purges_old_jobs_keeps_newest_five_and_leftover_apps(tmp_path):
    phone = Phone()
    jr = runner(tmp_path, phone, free_mb=100.0, hard_min_free_mb=50)
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    for i in range(8):
        d = jobs / f"{i:032x}"
        d.mkdir()
        os.utime(d, (1000 + i, 1000 + i))
    (jobs / "notajob").mkdir()
    jr.doctor.installed.add("com.leftover.app")
    job = await run_job(jr)
    assert job.status == "done", job.error
    left = sorted(p.name for p in jobs.iterdir() if p.name != job.job_id)
    assert "notajob" in left and len([n for n in left if n != "notajob"]) == 5
    assert f"{0:032x}" not in left and f"{7:032x}" in left
    assert ["adb", "-s", SERIAL, "uninstall", "com.leftover.app"] in phone.calls
    assert jr.doctor.last_repair["actions"][0].startswith("freed space")


async def test_disk_below_hard_floor_refuses(tmp_path):
    jr = runner(tmp_path, Phone(), free_mb=100.0)
    job = await run_job(jr)
    assert job.status == "failed" and "not responding" in (job.error or "")


async def test_data_partition_low_triggers_repair(tmp_path):
    phone = Phone()
    phone.data_free_kb = 100 * 1024
    jr = runner(tmp_path, phone)
    job = await run_job(jr)
    assert jr.doctor.last_repair and "data_disk" in jr.doctor.last_repair["problems"]
    assert job.status == "done"  # still above the hard floor on the host disk


async def test_mid_job_adb_drop_reconnects_and_retries_profile_once(tmp_path):
    phone = Phone()
    phone.heals_on = "reconnect"
    phone.offline_during = "am start -W"
    jr = runner(tmp_path, phone)
    job = await run_job(jr, ["baseline", "battery_saver"])
    assert job.status == "done", job.error
    res = jr.results[job.job_id].profiles
    assert [p.profile_id for p in res] == ["baseline", "battery_saver"]
    assert res[0].applied and res[0].launched  # retried and succeeded
    assert any("retrying profile baseline once" in e for e in job.events)


async def test_mid_job_unrecoverable_marks_profile_unapplied_and_continues(tmp_path):
    phone = Phone()
    phone.heals_on = "never"
    phone.offline_during = "am start -W"
    jr = runner(tmp_path, phone)
    job = await run_job(jr, ["baseline", "battery_saver"])
    assert job.status == "done", job.error
    res = jr.results[job.job_id].profiles
    assert len(res) == 2 and not res[0].applied and not res[1].applied
    assert "stopped responding" in (res[0].apply_note or "")
    assert any(e.startswith("DEVICE:") for e in job.events)


async def test_hung_step_times_out_the_profile(tmp_path):
    phone = Phone()
    jr = runner(tmp_path, phone, profile_timeout_s=1)
    orig = jr._run_profile
    calls = {"n": 0}

    async def slow(job, req, pid):
        calls["n"] += 1
        await asyncio.sleep(30)
        return await orig(job, req, pid)

    jr._run_profile = slow  # type: ignore[method-assign]
    job = await run_job(jr)
    res = jr.results[job.job_id].profiles[0]
    assert job.status == "done" and not res.applied and "hung" in (res.apply_note or "")
    assert calls["n"] == 2  # one retry, then honest give-up


def client(tmp_path, phone: Phone) -> TestClient:
    app = create_app(cfg(tmp_path), runner=phone)
    app.state.jobs._sleep = nosleep
    app.state.jobs.doctor._sleep = nosleep
    return TestClient(app)


def test_health_reports_device_status_last_repair_disk(tmp_path):
    phone = Phone()
    c = client(tmp_path, phone)
    body = c.get("/health", headers=H).json()
    assert body["device_status"] == "ok" and body["last_repair"] is None and body["disk_free_mb"] > 0
    phone.adb_up, phone.booted = False, False
    assert c.get("/health", headers=H).json()["device_status"] == "down"


def test_delete_job_removes_artifacts_and_is_404_after(tmp_path):
    with client(tmp_path, Phone()) as c:
        r = c.post("/jobs", headers=H, files={"apk": ("a.apk", b"PK")}, data={"request": request_json(["baseline"])})
        jid = r.json()["job_id"]
        assert wait_done(c, jid)["status"] == "done"
        d = tmp_path / "jobs" / jid
        assert d.is_dir()
        assert c.delete(f"/jobs/{jid}", headers=H).json() == {"deleted": True, "job_id": jid}
        assert not d.exists()
        assert c.get(f"/jobs/{jid}", headers=H).status_code == 404
        assert c.delete(f"/jobs/{jid}", headers=H).status_code == 200  # idempotent
        assert c.delete("/jobs/not-hex", headers=H).status_code == 404


def test_delete_running_job_is_409(tmp_path):
    app = create_app(cfg(tmp_path), runner=Phone())
    jr = app.state.jobs
    job, _ = jr.start(HarnessJobRequest(run_id="r", package_name=PKG, profiles=["baseline"]))
    job.status = "running"
    c = TestClient(app)
    assert c.delete(f"/jobs/{job.job_id}", headers=H).status_code == 409
    assert (tmp_path / "jobs" / job.job_id).is_dir()


def test_failed_job_still_serves_partial_result(tmp_path):
    phone = Phone()
    phone.adb_up, phone.booted, phone.heals_on = False, False, "never"
    with client(tmp_path, phone) as c:
        # POST pre-check needs adb binary only (`version`), so the job is accepted and then fails at the gate
        jid = c.post(
            "/jobs", headers=H, files={"apk": ("a.apk", b"PK")}, data={"request": request_json(["baseline"])}
        ).json()["job_id"]
        job = wait_done(c, jid)
        assert job["status"] == "failed" and any(e.startswith("DEVICE:") for e in job["events"])
        time.sleep(0.05)
        assert c.get(f"/jobs/{jid}/result", headers=H).json()["profiles"] == []


@pytest.mark.parametrize("kind", ["emulator"])
async def test_non_redroid_never_touches_docker(tmp_path, kind):
    phone = Phone()
    jr = runner(tmp_path, phone, device_kind=kind)
    await run_job(jr)
    assert phone.docker_calls == []
