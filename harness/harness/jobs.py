"""Single-job runner: install, per-profile prepare/apply/journey/evidence/revert, uninstall."""

import asyncio
import logging
import re
import shutil
import time
import uuid
from collections.abc import Callable
from pathlib import Path

import httpx

from . import evidence
from .adb import Adb
from .agent import drive, llm_ready
from .crawler import Crawler, Sleep
from .explorer import explore
from .heal import DeviceDoctor
from .inputs import InputBroker, run_unpaused
from .live import LiveState
from .models import (
    AgentTest,
    HarnessAgentTestResult,
    HarnessJob,
    HarnessJobRequest,
    HarnessProfileResult,
    HarnessResult,
    HarnessSecurityCheck,
    HarnessStep,
    ProfileId,
)
from .profiles import ProfileError, ProfileManager
from .secrets import Secrets
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

LOGIN_TEST = AgentTest(
    id="login_first", title="Log in with the test account", condition="baseline",
    goal="Log in with the test account (skip any onboarding or permission screens first).",
    success_check="A logged-in home screen is visible (no login form).",
)  # fmt: skip
OFFLINE_TEST = AgentTest(
    id="offline_after_login", title="Keep using the app on a bad network after logging in", condition="flaky_network",
    goal="The phone now has a very poor, dropping network. Keep using the app: open two or three screens and "
    "refresh or load content. Report what breaks (stuck spinner, blank screen, crash, no error message).",
    success_check="The app stays usable and shows clear errors or cached content; no crash or endless loading.",
)  # fmt: skip

_PKG_OK = re.compile(r"^[A-Za-z][\w]*(\.[A-Za-z][\w]*)+$")


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
        disk_probe: Callable[[Path], float] | None = None,
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
        self.doctor = DeviceDoctor(settings, adb, sleep, clock, disk_probe)
        self.live: dict[str, LiveState] = {}
        self._secrets: dict[str, Secrets] = {}  # per job, memory only (f23/f24)
        self._cleartext: dict[str, tuple[list[tuple[str, str, str]] | None, str | None]] = {}

    # ---- health ----
    async def health(self, maestro_found: bool) -> dict[str, object]:
        if not self.busy and self.doctor.host_free_mb() < self.settings.min_free_mb:
            # idle and short on disk: free old job folders now so the API's disk guard can recover on its own
            self.doctor.purge_jobs(set())
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
            **self.doctor.snapshot(adb_ok, booted),
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
        self.live[job.job_id] = LiveState()
        d = self.job_dir(job.job_id)
        d.mkdir(parents=True, exist_ok=True)
        return job, d

    def launch(self, job: HarnessJob, req: HarnessJobRequest) -> None:
        task = asyncio.create_task(self._execute(job, req))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def abort_start(self, job: HarnessJob) -> None:
        self.jobs.pop(job.job_id, None)
        self.live.pop(job.job_id, None)
        self._active = None

    def cancel(self, job_id: str) -> HarnessJob | None:
        job = self.jobs.get(job_id)
        if job and job.status in ("queued", "running"):
            self._cancel.add(job_id)
            self._event(job, "cancel requested")
        return job

    def delete(self, job_id: str) -> bool:
        """Remove a finished job's artifacts and bookkeeping. False if it is still active."""
        job = self.jobs.get(job_id)
        if job is None:
            return True
        if job.status in ("queued", "running") or job_id == self._active:
            return False
        shutil.rmtree(self.job_dir(job_id), ignore_errors=True)
        self.jobs.pop(job_id, None)
        self.results.pop(job_id, None)
        self._cancel.discard(job_id)
        self.live.pop(job_id, None)
        return True

    def _sec(self, job: HarnessJob, req: HarnessJobRequest) -> Secrets:
        """One Secrets per job so values the user types live (f24) stay masked and are reused by later profiles."""
        sec = self._secrets.get(job.job_id)
        if sec is None:
            sec = self._secrets[job.job_id] = Secrets(req.credentials)
        return sec

    def _broker(self, job: HarnessJob) -> InputBroker:
        return self.live.setdefault(job.job_id, LiveState()).broker

    def submit_input(self, job_id: str, request_id: str, values: dict[str, str] | None, skip: bool) -> bool:
        state = self.live.get(job_id)
        return bool(state and state.broker.submit(request_id, values, skip))

    def _event(self, job: HarnessJob, msg: str) -> None:
        job.events.append(msg)
        log.info("[%s] %s", job.job_id[:8], msg)

    # ---- execution ----
    async def _execute(self, job: HarnessJob, req: HarnessJobRequest) -> None:
        job.status = "running"
        live = self.live.setdefault(job.job_id, LiveState())
        live.broker.enabled = req.interactive
        live.broker.on_event = lambda m: self._event(job, m)
        if self.settings.live_enabled:
            live.start(self.adb)
        profiles: list[HarnessProfileResult] = []
        security: list[HarnessSecurityCheck] = []
        agent: list[HarnessAgentTestResult] = []
        try:
            await run_unpaused(self._run(job, req, profiles, security, agent), self.settings.job_timeout_s, live.broker)
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
            await live.stop()
            await self._uninstall(job, req.package_name)
            job.current_profile = None
            version = await self._android_version()
            result = HarnessResult(
                job_id=job.job_id, device=self.settings.android_serial, android_version=version, profiles=profiles,
                security=security, agent_tests=agent,
            )  # fmt: skip
            self.results[job.job_id] = result
            d = self.job_dir(job.job_id)
            (d / "result.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
            self._cleartext.pop(job.job_id, None)
            self._secrets.pop(job.job_id, None)
            self._active = None

    async def _uninstall(self, job: HarnessJob, package: str) -> None:
        rc, _, err = await self.adb.run(["uninstall", package], timeout=60)
        if rc == 0:
            self.doctor.installed.discard(package)
        self._event(job, f"uninstalled {package}" if rc == 0 else f"uninstall failed: {err.strip()[:100]}")

    async def _remove_other_apps(self, job: HarnessJob, package: str) -> None:
        """Only the app under test may exist on the phone: uninstall every other user-installed app."""
        rc, out, _ = await self.adb.shell("pm", "list", "packages", "-3", timeout=30)
        if rc != 0:
            return
        others = [ln.split(":", 1)[1].strip() for ln in out.splitlines() if ln.startswith("package:")]
        for pkg in others:
            if pkg and pkg != package and _PKG_OK.match(pkg):
                await self.adb.shell("pm", "uninstall", pkg, timeout=60)
                self._event(job, f"removed other app {pkg} so only the app under test is on the phone")

    async def _run(
        self, job: HarnessJob, req: HarnessJobRequest, out: list[HarnessProfileResult],
        security: list[HarnessSecurityCheck], agent: list[HarnessAgentTestResult] | None = None,
    ) -> None:  # fmt: skip
        agent = agent if agent is not None else []
        apk = self.job_dir(job.job_id) / "app.apk"
        ready = await self.doctor.ensure_ready(
            lambda m: self._event(job, m), protect_jobs={job.job_id}, keep_pkgs={req.package_name}
        )
        if not ready:
            raise RuntimeError(
                "The test phone is not responding and could not be restarted automatically. Try again in a minute."
            )
        await self._remove_other_apps(job, req.package_name)
        rc, stdout, stderr = await self.adb.run(["install", "-r", "-g", str(apk)], timeout=180)
        if rc != 0 or "Success" not in stdout:
            raise RuntimeError(f"adb install failed: {(stderr or stdout).strip()[:200]}")
        self.doctor.installed.add(req.package_name)
        self._event(job, f"installed {req.package_name}")
        total = len(req.profiles)
        for n, pid in enumerate(req.profiles):
            if job.job_id in self._cancel:
                break
            job.current_profile = pid
            self.live.setdefault(job.job_id, LiveState()).set_profile(pid)
            self._event(job, f"profile {pid}: start")
            out.append(await self._profile_with_recovery(job, req, pid))
            job.progress = (n + 1) / total
            self._event(job, f"profile {pid}: done")
        if job.job_id not in self._cancel and (req.agent_tests or self._offline_wanted(req)):
            await self._agent_tests(job, req, agent)
        if job.job_id not in self._cancel and out:
            await self._security(job, req, security)

    async def _profile_with_recovery(self, job: HarnessJob, req: HarnessJobRequest, pid: ProfileId) -> HarnessProfileResult:
        """Run one profile; if the phone drops off adb or a step hangs, reconnect and retry once, else report honestly."""
        problem = "unknown"
        for attempt in (1, 2):
            if not await self.doctor.adb_alive():
                self._event(job, f"DEVICE: phone offline before profile {pid}; reconnecting")
                if not await self.doctor.reconnect():
                    problem = "the phone is offline and did not reconnect"
                    break
            try:
                res = await run_unpaused(self._run_profile(job, req, pid), self.settings.profile_timeout_s, self._broker(job))
            except TimeoutError:
                problem = f"a step hung for over {self.settings.profile_timeout_s}s"
            except Exception as exc:  # noqa: BLE001 - classify below
                if await self.doctor.adb_alive():
                    self._event(job, f"profile {pid}: error: {exc}")
                    return HarnessProfileResult(
                        profile_id=pid, applied=False, launched=False, apply_note=f"profile errored: {str(exc)[:150]}"
                    )
                problem = f"{type(exc).__name__}: {str(exc)[:80]}"
            else:
                if await self.doctor.adb_alive():
                    return res
                problem = "the phone went offline during the test"
            self._event(job, f"DEVICE: {problem} (profile {pid}, attempt {attempt})")
            if attempt == 1 and await self.doctor.reconnect():
                self._event(job, f"DEVICE: reconnected; retrying profile {pid} once")
                continue
            break
        note = f"The test phone stopped responding ({problem}); this condition was not tested."
        self._event(job, f"DEVICE: profile {pid} skipped: {problem}")
        return HarnessProfileResult(profile_id=pid, applied=False, launched=False, apply_note=note)

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
                on_step=self.live.setdefault(job.job_id, LiveState()).note_step, secrets=self._sec(job, req),
                broker=self._broker(job),
            )  # fmt: skip
            try:
                if cfg.explorer_enabled and llm_ready(cfg):
                    live_state = self.live.setdefault(job.job_id, LiveState())
                    async with httpx.AsyncClient() as llm_client:

                        async def brain(c: Crawler, n: int) -> None:
                            await explore(c, n, cfg, llm_client, live_state.set_caption, c.secrets)

                        crawler.explorer = brain
                        j = await crawler.run(req.journey_steps)
                else:
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


    # ---- agent-written tests (f23) ----
    @staticmethod
    def _offline_wanted(req: HarnessJobRequest) -> bool:
        sec = Secrets(req.credentials)
        return sec.available and sec.offline_after_login

    async def _agent_tests(self, job: HarnessJob, req: HarnessJobRequest, out: list[HarnessAgentTestResult]) -> None:
        cfg = self.settings
        if not llm_ready(cfg):
            self._event(job, "agent tests skipped: no LLM key configured on the test phone host")
            skipped = "Skipped: the test phone host has no LLM key (set LLM_API_KEY in harness/.env)."
            out.extend(
                HarnessAgentTestResult(id=t.id, title=t.title, condition=t.condition, reason=skipped)
                for t in req.agent_tests
            )
            if self._offline_wanted(req):
                out.append(
                    HarnessAgentTestResult(
                        id=OFFLINE_TEST.id, title=OFFLINE_TEST.title, condition="flaky_network", reason=skipped
                    )
                )
            return
        live = self.live.setdefault(job.job_id, LiveState())
        async with httpx.AsyncClient() as client:
            for t in req.agent_tests:
                if job.job_id in self._cancel:
                    break
                job.current_profile = t.condition
                live.set_profile(f"agent_{t.id}")
                self._event(job, f"agent test '{t.title}': start")
                try:
                    res = await run_unpaused(self._agent_one(job, req, t, client, live), cfg.agent_test_timeout_s, live.broker)
                except TimeoutError:
                    res = HarnessAgentTestResult(
                        id=t.id, title=t.title, condition=t.condition, reason="This test took too long and was stopped."
                    )
                except Exception as exc:  # noqa: BLE001 - one broken test must not drop the others
                    res = HarnessAgentTestResult(
                        id=t.id, title=t.title, condition=t.condition, reason=f"Could not run ({type(exc).__name__})."
                    )
                out.append(res)
                self._event(job, f"agent test '{t.title}': {'passed' if res.passed else 'failed' if res.passed is False else 'not judged'}")
            if self._offline_wanted(req) and job.job_id not in self._cancel:
                out.append(await self._offline_after_login(job, req, client, live))

    async def _offline_after_login(
        self, job: HarnessJob, req: HarnessJobRequest, client: httpx.AsyncClient, live: LiveState
    ) -> HarnessAgentTestResult:
        """Log in on baseline, then drop to a flaky network and keep using the app, recording what breaks."""
        cfg = self.settings
        sec = self._sec(job, req)
        pm = ProfileManager(self.adb, self._sleep, cfg.device_kind, tc=cfg.tc_path, ip=cfg.ip_path, sudo=cfg.sudo_path)
        pkg = req.package_name
        live.set_profile(f"agent_{OFFLINE_TEST.id}")
        self._event(job, "offline-after-login phase: logging in on baseline")
        failed = HarnessAgentTestResult(id=OFFLINE_TEST.id, title=OFFLINE_TEST.title, condition="flaky_network")
        applied = False
        try:
            await self.adb.shell("am", "force-stop", pkg, timeout=20)
            await self.adb.shell("pm", "clear", pkg, timeout=30)
            crawler = Crawler(
                self.adb, pkg, req.main_activity, self.job_dir(job.job_id), f"agent_{OFFLINE_TEST.id}",  # type: ignore[arg-type]
                cancelled=lambda: job.job_id in self._cancel, sleep=self._sleep, clock=self._clock,
                on_step=live.note_step, secrets=sec, broker=live.broker,
            )  # fmt: skip
            login = await run_unpaused(
                drive(crawler, LOGIN_TEST, cfg, client, live.set_caption, secrets=sec, broker=live.broker),
                cfg.agent_test_timeout_s, live.broker,
            )
            if login.passed is not True:
                failed.steps, failed.screens = login.steps, login.screens
                failed.reason = f"Could not log in with the test account, so the offline phase did not run. {login.reason}"
                return failed
            self._event(job, "offline-after-login phase: logged in; dropping to a flaky network")
            await pm.apply("flaky_network")
            applied = True
            return await run_unpaused(
                drive(crawler, OFFLINE_TEST, cfg, client, live.set_caption, secrets=sec, launch=False, broker=live.broker),
                cfg.agent_test_timeout_s, live.broker,
            )
        except TimeoutError:
            failed.reason = "The offline phase took too long and was stopped; no verdict."
            return failed
        except Exception as exc:  # noqa: BLE001
            failed.reason = f"The offline phase could not run ({type(exc).__name__})."
            return failed
        finally:
            if applied:
                try:
                    await pm.revert("flaky_network")
                except Exception as exc:  # noqa: BLE001
                    self._event(job, f"offline phase: REVERT FAILED: {exc}")

    async def _agent_one(
        self, job: HarnessJob, req: HarnessJobRequest, t: AgentTest, client: httpx.AsyncClient, live: LiveState
    ) -> HarnessAgentTestResult:
        cfg = self.settings
        pm = ProfileManager(self.adb, self._sleep, cfg.device_kind, tc=cfg.tc_path, ip=cfg.ip_path, sudo=cfg.sudo_path)
        pkg = req.package_name
        try:
            await self.adb.shell("am", "force-stop", pkg, timeout=20)
            await self.adb.shell("pm", "clear", pkg, timeout=30)
            try:
                await pm.apply(t.condition)
            except ProfileError as exc:
                return HarnessAgentTestResult(
                    id=t.id, title=t.title, condition=t.condition, reason=f"Condition could not be applied: {exc}"
                )
            crawler = Crawler(
                self.adb, pkg, req.main_activity, self.job_dir(job.job_id), f"agent_{t.id}",  # type: ignore[arg-type]
                cancelled=lambda: job.job_id in self._cancel, sleep=self._sleep, clock=self._clock,
                on_step=live.note_step, secrets=self._sec(job, req), broker=live.broker,
            )  # fmt: skip
            return await drive(crawler, t, cfg, client, live.set_caption, secrets=self._sec(job, req), broker=live.broker)
        finally:
            try:
                await pm.revert(t.condition)
            except Exception as exc:  # noqa: BLE001
                self._event(job, f"agent test {t.id}: REVERT FAILED: {exc}")

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
