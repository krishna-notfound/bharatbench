"""RunServiceImpl: the single service used by routes and the voice agent."""

import asyncio
import contextlib
import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app import pipeline as _pipeline
from app.events import EventBus, EventSubscription
from app.models import AgentTest, Finding, ProfileId, Run, RunEvent, TestCredentials
from app.pipeline import HarnessFactory, run_pipeline
from app.storage.base import Storage

TERMINAL = ("done", "failed", "cancelled")
STUCK_AFTER_S = 25 * 60  # no status change for this long: the pipeline is wedged
WATCHDOG_INTERVAL_S = 60.0
RESTART_REASON = "The server restarted while this run was in progress, so it was stopped. Please start it again."
MAX_RESUMES = 2
RESUME_NOTE = "The server was updated during this test — restarting it now so you get a full report"
STUCK_REASON = "This run stopped making progress and was ended automatically. Please start it again."


class RunServiceImpl:
    def __init__(
        self, storage: Storage, bus: EventBus, data_dir: Path, harness_factory: HarnessFactory
    ) -> None:
        self.storage = storage
        self.bus = bus
        self.data_dir = Path(data_dir)
        self._harness_factory = harness_factory
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._job_ids: dict[str, str] = {}
        self._stop_flags: set[str] = set()
        self._watchdog: asyncio.Task[None] | None = None

    async def recover_orphans(self) -> int:
        """Resume every run a previous process left non-terminal (max MAX_RESUMES times, then fail humanely)."""
        count = 0
        for run in await self.storage.list_runs():
            if run.status in TERMINAL:
                continue
            count += 1
            events = await self.storage.list_events(run.id)
            resumes = sum(1 for e in events if (e.data or {}).get("resumed"))
            apk = await self.storage.get_apk_path(run.id)
            if resumes >= MAX_RESUMES or apk is None or not Path(apk).exists():
                await self._force_finish(
                    run, RESTART_REASON, "Recovery: the server restarted while this run was in progress"
                )
                continue
            await self._stop_harness_job(run.id)
            await self.bus.publish(run.id, "log", RESUME_NOTE, {"resumed": resumes + 1})
            await self.storage.delete_findings(run.id)
            queued = run.model_copy(update={"status": "queued", "summary": None, "updated_at": datetime.now(UTC)})
            await self.storage.update_run(queued)
            await self.bus.publish(run.id, "status", "Status: queued", {"status": "queued"})
            self._launch(run.id, Path(apk))
        return count

    async def _force_finish(self, run: Run, reason: str, log_line: str) -> None:
        """Move a stuck run to `failed` with `reason`; also stops its harness job if we can find it."""
        await self.bus.publish(run.id, "log", log_line)
        await self._stop_harness_job(run.id)
        failed = run.model_copy(update={"status": "failed", "error": reason, "updated_at": datetime.now(UTC)})
        await self.storage.update_run(failed)
        await self.bus.publish(run.id, "status", "Status: failed", {"status": "failed"})
        await self.bus.publish(run.id, "error", reason, {"error": reason})

    async def _stop_harness_job(self, run_id: str) -> None:
        """Best effort: cancel + delete the harness job a dead pipeline left behind."""
        job_id = self._job_ids.get(run_id)
        if job_id is None:
            for ev in reversed(await self.storage.list_events(run_id)):
                if ev.data and ev.data.get("job_id"):
                    job_id = str(ev.data["job_id"])
                    break
        if job_id is None:
            return
        try:
            client = self._harness_factory()
        except Exception:  # noqa: BLE001
            return
        if client is None:
            return
        try:
            await self.bus.publish(run_id, "log", "Recovery: stopping the leftover test phone job")
            with contextlib.suppress(Exception):
                await client.cancel(job_id)
            with contextlib.suppress(Exception):
                await client.delete(job_id)
        finally:
            with contextlib.suppress(Exception):
                await client.aclose()

    async def sweep_stuck(self) -> int:
        """Watchdog: finish non-terminal runs unchanged for STUCK_AFTER_S (their task is stopped first)."""
        now = datetime.now(UTC)
        swept = 0
        for run in await self.storage.list_runs():
            if run.status in TERMINAL or (now - run.updated_at).total_seconds() < STUCK_AFTER_S:
                continue
            task = self._tasks.get(run.id)
            killed = task is not None and not task.done()
            if task is not None and killed:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            fresh = await self.storage.get_run(run.id)
            # a task we just killed leaves "cancelled"; replace that with the real reason
            if fresh is not None and (fresh.status not in TERMINAL or (killed and fresh.status == "cancelled")):
                await self._force_finish(fresh, STUCK_REASON, "Watchdog: this run stopped making progress")
                swept += 1
        return swept

    def start_watchdog(self, interval_s: float = WATCHDOG_INTERVAL_S) -> None:
        async def loop() -> None:
            while True:
                await asyncio.sleep(interval_s)
                with contextlib.suppress(Exception):
                    await self.sweep_stuck()

        self._watchdog = asyncio.create_task(loop())

    async def create_run(
        self,
        apk_path: str,
        apk_name: str,
        profile_ids: list[ProfileId],
        journey_steps: int | None = None,
        agent_tests: list[AgentTest] | None = None,
        credentials: TestCredentials | None = None,
    ) -> Run:
        run_id = uuid.uuid4().hex[:12]
        if credentials is not None and credentials.present:  # memory only, keyed by run id; dropped at the end
            _pipeline.CREDENTIALS[run_id] = credentials
        dest = self.data_dir / "runs" / run_id / "app.apk"
        dest.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copyfile, apk_path, dest)
        if agent_tests:  # read back by the pipeline (also after a restart-resume)
            (dest.parent / "agent_tests_in.json").write_text(
                json.dumps([t.model_dump() for t in agent_tests]), encoding="utf-8"
            )
        return await self._start(run_id, apk_name, profile_ids, dest, journey_steps)

    async def rerun(
        self,
        source_run_id: str,
        profile_ids: list[ProfileId],
        journey_steps: int | None = None,
        agent_tests: list[AgentTest] | None = None,
    ) -> Run:
        source = await self.storage.get_run(source_run_id)
        source_apk = await self.storage.get_apk_path(source_run_id)
        if source is None or source_apk is None:
            raise LookupError(f"Run {source_run_id} not found")
        return await self.create_run(source_apk, source.apk_name, profile_ids, journey_steps, agent_tests)

    async def _start(
        self, run_id: str, apk_name: str, profile_ids: list[ProfileId], apk: Path, journey_steps: int | None = None
    ) -> Run:
        now = datetime.now(UTC)
        run = Run(
            id=run_id, apk_name=apk_name, status="queued", profile_ids=profile_ids, created_at=now, updated_at=now
        )
        await self.storage.create_run(run, str(apk))
        await self.bus.publish(run_id, "status", "Status: queued", {"status": "queued"})
        self._launch(run_id, apk, journey_steps)
        return run

    def _launch(self, run_id: str, apk: Path, journey_steps: int | None = None) -> None:
        task = asyncio.create_task(
            run_pipeline(
                run_id,
                storage=self.storage,
                bus=self.bus,
                data_dir=self.data_dir,
                harness_factory=self._harness_factory,
                job_ids=self._job_ids,
                stop_flags=self._stop_flags,
                journey_steps=journey_steps,
            )
        )
        self._tasks[run_id] = task
        task.add_done_callback(lambda _t: (self._tasks.pop(run_id, None), _pipeline.CREDENTIALS.pop(run_id, None)))

    async def get_run(self, run_id: str) -> Run | None:
        return await self.storage.get_run(run_id)

    async def list_runs(self) -> list[Run]:
        return await self.storage.list_runs()

    async def list_findings(self, run_id: str) -> list[Finding]:
        findings = await self.storage.list_findings(run_id)
        return sorted(findings, key=lambda f: f.impact.score if f.impact else 0.0, reverse=True)

    async def list_events(self, run_id: str, after_seq: int = 0) -> list[RunEvent]:
        return await self.storage.list_events(run_id, after_seq)

    async def cancel_run(self, run_id: str) -> Run | None:
        """Graceful stop: flag the pipeline so it wraps up with the results collected so far."""
        run = await self.storage.get_run(run_id)
        if run is None or run.status in TERMINAL:
            return run
        task = self._tasks.get(run_id)
        if task is not None and not task.done() and run_id not in self._stop_flags:
            self._stop_flags.add(run_id)
            await self.bus.publish(
                run_id, "log", "Stop requested — finishing with the results collected so far"
            )
        return run

    def subscribe(self, run_id: str) -> EventSubscription:
        return self.bus.subscribe(run_id)

    async def shutdown(self) -> None:
        if self._watchdog is not None:
            self._watchdog.cancel()
        for task in list(self._tasks.values()):
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)


_service: RunServiceImpl | None = None


def set_run_service(service: RunServiceImpl | None) -> None:
    global _service
    _service = service


def get_run_service() -> RunServiceImpl:
    if _service is None:
        raise RuntimeError("RunService is not initialised (app lifespan not started)")
    return _service
