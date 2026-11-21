"""Single-job runner: install, per-profile prepare/apply/journey/evidence/revert, uninstall."""

import asyncio
import logging
import re
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from . import evidence
from .adb import Adb
from .crawler import Crawler, Sleep
from .models import (
    HarnessJob,
    HarnessJobRequest,
    HarnessProfileResult,
    HarnessResult,
    HarnessSecurityCheck,
    HarnessStep,
    ProfileId,
)
from .profiles import ProfileError, ProfileManager
from .security import (
    CleartextCapture,
    DeviceAudit,
    cleartext_check,
    not_run,
    parse_tcpdump,
    scan_logcat_leaks,
)
from .settings import Settings

log = logging.getLogger("harness.jobs")


class Busy(Exception):
    pass


class NotBooted(Exception):
    pass


class JobRunner:
    def __init__(
        self,
        settings: Settings,
        adb: Adb,
        sleep: Sleep = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self.adb = adb
        self._sleep = sleep
        self._clock = clock
        self.jobs: dict[str, HarnessJob] = {}
        self.results: dict[str, HarnessResult] = {}
        self._cancel: set[str] = set()
        self._active: str | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._cleartext: dict[str, tuple[list[tuple[str, str, str]] | None, str | None]] = {}

    # ---- health ----
    async def health(self, maestro_found: bool) -> dict[str, object]:
        rc, _, _ = await self.adb.global_run(["version"])
        adb_ok = rc == 0
        devices: list[str] = []
        booted, version = False, None
        if adb_ok:
            _, out, _ = await self.adb.global_run(["devices"])
            for line in out.splitlines()[1:]:
                parts = line.split()
                if len(parts) == 2 and parts[1] == "device":
                    devices.append(parts[0])
            if self.adb.serial in devices:
                _, boot, _ = await self.adb.shell("getprop", "sys.boot_completed", timeout=10)
                booted = boot.strip() == "1"
                if booted:
                    version = await self._android_version()
        return {
            "adb": adb_ok,
            "devices": devices,
            "emulator_booted": booted,
            "maestro": maestro_found,
            "android_version": version,
        }

    async def _android_version(self) -> str | None:
        rc, out, _ = await self.adb.shell("getprop", "ro.build.version.release", timeout=10)
        return out.strip() or None if rc == 0 else None

    # ---- lifecycle ----
    @property
    def busy(self) -> bool:
        return self._active is not None

    def job_dir(self, job_id: str) -> Path:
        return self.settings.jobs_dir / job_id

    def start(self, req: HarnessJobRequest) -> tuple[HarnessJob, Path]:
        """Register a job (synchronous so the busy check cannot race). Caller saves the APK, then calls launch()."""
        if self.busy:
            raise Busy(self._active)
        job = HarnessJob(job_id=uuid.uuid4().hex, run_id=req.run_id, status="queued")
        self._active = job.job_id
        self.jobs[job.job_id] = job
        d = self.job_dir(job.job_id)
        d.mkdir(parents=True, exist_ok=True)
        return job, d

    def launch(self, job: HarnessJob, req: HarnessJobRequest) -> None:
        task = asyncio.create_task(self._execute(job, req))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def abort_start(self, job: HarnessJob) -> None:
        self.jobs.pop(job.job_id, None)
        self._active = None

    def cancel(self, job_id: str) -> HarnessJob | None:
        job = self.jobs.get(job_id)
        if job and job.status in ("queued", "running"):
            self._cancel.add(job_id)
            self._event(job, "cancel requested")
        return job

    def _event(self, job: HarnessJob, msg: str) -> None:
        job.events.append(msg)
        log.info("[%s] %s", job.job_id[:8], msg)

    # ---- execution ----
    async def _execute(self, job: HarnessJob, req: HarnessJobRequest) -> None:
        job.status = "running"
        profiles: list[HarnessProfileResult] = []
        security: list[HarnessSecurityCheck] = []
        try:
            await asyncio.wait_for(self._run(job, req, profiles, security), self.settings.job_timeout_s)
            if job.job_id in self._cancel:
                job.status = "cancelled"
            else:
                job.status = "done"
        except TimeoutError:
            job.status, job.error = "failed", f"job exceeded {self.settings.job_timeout_s}s"
        except Exception as exc:
            log.exception("job failed")
            job.status, job.error = "failed", str(exc)[:300]
        finally:
            await self._uninstall(job, req.package_name)
            job.current_profile = None
            version = await self._android_version()
            result = HarnessResult(
                job_id=job.job_id, device=self.settings.android_serial, android_version=version, profiles=profiles,
                security=security,
            )  # fmt: skip
            self.results[job.job_id] = result
            d = self.job_dir(job.job_id)
            (d / "result.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
            self._cleartext.pop(job.job_id, None)
            self._active = None

    async def _uninstall(self, job: HarnessJob, package: str) -> None:
        rc, _, err = await self.adb.run(["uninstall", package], timeout=60)
        self._event(job, f"uninstalled {package}" if rc == 0 else f"uninstall failed: {err.strip()[:100]}")

    async def _run(
        self, job: HarnessJob, req: HarnessJobRequest, out: list[HarnessProfileResult],
        security: list[HarnessSecurityCheck],
    ) -> None:  # fmt: skip
        apk = self.job_dir(job.job_id) / "app.apk"
        rc, stdout, stderr = await self.adb.run(["install", "-r", "-g", str(apk)], timeout=180)
        if rc != 0 or "Success" not in stdout:
            raise RuntimeError(f"adb install failed: {(stderr or stdout).strip()[:200]}")
        self._event(job, f"installed {req.package_name}")
        total = len(req.profiles)
        for n, pid in enumerate(req.profiles):
            if job.job_id in self._cancel:
                break
            job.current_profile = pid
            self._event(job, f"profile {pid}: start")
            out.append(await self._run_profile(job, req, pid))
            job.progress = (n + 1) / total
            self._event(job, f"profile {pid}: done")
        if job.job_id not in self._cancel and out:
            await self._security(job, req, security)

    async def _run_profile(self, job: HarnessJob, req: HarnessJobRequest, pid: ProfileId) -> HarnessProfileResult:
        res = HarnessProfileResult(profile_id=pid, applied=False, launched=False)
        cfg = self.settings
        pm = ProfileManager(
            self.adb, self._sleep, cfg.device_kind, tc=cfg.tc_path, ip=cfg.ip_path, sudo=cfg.sudo_path
        )
        d = self.job_dir(job.job_id)
        pkg = req.package_name
        try:
            await self.adb.shell("am", "force-stop", pkg, timeout=20)
            await self.adb.shell("pm", "clear", pkg, timeout=30)
            await self.adb.run(["logcat", "-c"], timeout=20)
            try:
                res.apply_note = await pm.apply(pid)
                res.applied = True
            except ProfileError as exc:
                res.apply_note = f"could not apply: {exc}"
                self._event(job, f"profile {pid}: {res.apply_note}")
                return res
            capture: CleartextCapture | None = None
            if pid == "baseline" and cfg.security_enabled:
                capture = CleartextCapture(cfg.sudo_path, cfg.tcpdump_path, cfg.timeout_path, d / "security" / "tcpdump.raw")
                await capture.start()
            crawler = Crawler(
                self.adb, pkg, req.main_activity, d, pid,
                cancelled=lambda: job.job_id in self._cancel, sleep=self._sleep, clock=self._clock,
            )  # fmt: skip
            try:
                j = await crawler.run(req.journey_steps)
            except Exception as exc:  # noqa: BLE001 - a broken journey is evidence, not a job failure
                j = crawler.j
                self._event(job, f"profile {pid}: journey error: {exc}")
            if capture is not None:
                await self._finish_capture(job, capture)
            res.launched, res.launch_ms = j.launched, j.launch_ms
            res.screens, res.steps = j.screens, j.steps
            res.stuck_loading, res.state_lost_after_restore = j.stuck_loading, j.state_lost_after_restore
            if pid == "flaky_network":
                res.steps.append(
                    HarnessStep(
                        index=len(res.steps),
                        action="toggle_network",
                        ok=pm.toggles > 0,
                        note=f"{pm.toggles} network blackout/restore cycles completed",
                    )
                )
            ev = await evidence.collect(self.adb, pkg, pid, d)
            res.logcat, res.crashes = ev.logcat, ev.crashes
            res.network_errors, res.memory_pss_kb = ev.network_errors, ev.memory_pss_kb
            return res
        finally:
            try:
                await pm.revert(pid)
            except Exception as exc:  # noqa: BLE001 - revert failures are recorded, never raised
                self._event(job, f"profile {pid}: REVERT FAILED: {exc}")
                log.warning("revert failed for %s: %s", pid, exc)


    # ---- dynamic security checks ----
    async def _finish_capture(self, job: HarnessJob, capture: CleartextCapture) -> None:
        text = await capture.stop()
        if text is None:
            self._cleartext[job.job_id] = (None, capture.error or "tcpdump did not start")
            self._event(job, f"cleartext capture unavailable: {capture.error}")
            return
        _, ipout, _ = await self.adb.shell("ip", "-4", "-o", "addr", "show", "eth0", timeout=15)
        m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)/", ipout)
        self._cleartext[job.job_id] = (parse_tcpdump(text, m.group(1) if m else None), None)

    async def _security(self, job: HarnessJob, req: HarnessJobRequest, out: list[HarnessSecurityCheck]) -> None:
        if not self.settings.security_enabled:
            return
        self._event(job, "security checks: start")
        d = self.job_dir(job.job_id)
        audit = DeviceAudit(self.adb, req.package_name, d, d / "app.apk", self._sleep)
        logs: dict[str, str] = {}
        for p in sorted((d / "logcat").glob("*.txt")) if (d / "logcat").is_dir() else []:
            logs[f"logcat/{p.name}"] = p.read_text("utf-8", "replace")
        hits, why = self._cleartext.get(job.job_id, (None, "the baseline profile was not part of this run"))
        steps = (
            ("storage", audit.storage),
            ("debuggable", audit.debuggable),
            ("exported components", audit.exported),
        )
        out.append(scan_logcat_leaks(logs, req.package_name))
        out.append(cleartext_check(hits, why))
        try:
            await asyncio.wait_for(self._device_checks(audit, steps, out), self.settings.security_timeout_s)
        except TimeoutError:
            out.append(not_run("sec.timeout", "Remaining security checks", "the security phase timed out"))
        self._event(job, f"security checks: done ({sum(1 for c in out if c.ran and not c.passed)} failed)")

    async def _device_checks(self, audit: DeviceAudit, steps: tuple, out: list[HarnessSecurityCheck]) -> None:  # type: ignore[type-arg]
        for name, fn in steps:
            try:
                res = await fn()
            except Exception as exc:  # noqa: BLE001 - one broken check must not drop the others
                log.warning("security check %s failed: %s", name, exc)
                out.append(not_run(f"sec.{name.replace(' ', '_')}", name, f"{type(exc).__name__}: {str(exc)[:120]}"))
                continue
            out.extend(res if isinstance(res, list) else [res])
