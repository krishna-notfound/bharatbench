"""RunServiceImpl: the single service used by routes and the voice agent."""

import asyncio
import contextlib
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.events import EventBus, EventSubscription
from app.models import Finding, ProfileId, Run, RunEvent
from app.pipeline import HarnessFactory, run_pipeline
from app.storage.base import Storage

TERMINAL = ("done", "failed", "cancelled")


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

    async def recover_orphans(self) -> None:
        """Mark runs left non-terminal by a previous process as failed."""
        for run in await self.storage.list_runs():
            if run.status not in TERMINAL:
                failed = run.model_copy(
                    update={"status": "failed", "error": "API restarted", "updated_at": datetime.now(UTC)}
                )
                await self.storage.update_run(failed)
                await self.bus.publish(run.id, "error", "API restarted", {"error": "API restarted"})

    async def create_run(self, apk_path: str, apk_name: str, profile_ids: list[ProfileId]) -> Run:
        run_id = uuid.uuid4().hex[:12]
        dest = self.data_dir / "runs" / run_id / "app.apk"
        dest.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copyfile, apk_path, dest)
        return await self._start(run_id, apk_name, profile_ids, dest)

    async def rerun(self, source_run_id: str, profile_ids: list[ProfileId]) -> Run:
        source = await self.storage.get_run(source_run_id)
        source_apk = await self.storage.get_apk_path(source_run_id)
        if source is None or source_apk is None:
            raise LookupError(f"Run {source_run_id} not found")
        return await self.create_run(source_apk, source.apk_name, profile_ids)

    async def _start(self, run_id: str, apk_name: str, profile_ids: list[ProfileId], apk: Path) -> Run:
        now = datetime.now(UTC)
        run = Run(
            id=run_id, apk_name=apk_name, status="queued", profile_ids=profile_ids, created_at=now, updated_at=now
        )
        await self.storage.create_run(run, str(apk))
        await self.bus.publish(run_id, "status", "Status: queued", {"status": "queued"})
        task = asyncio.create_task(
            run_pipeline(
                run_id,
                storage=self.storage,
                bus=self.bus,
                data_dir=self.data_dir,
                harness_factory=self._harness_factory,
                job_ids=self._job_ids,
            )
        )
        self._tasks[run_id] = task
        task.add_done_callback(lambda _t: self._tasks.pop(run_id, None))
        return run

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
        task = self._tasks.get(run_id)
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        run = await self.storage.get_run(run_id)
        if run is not None and task is not None and run.status not in TERMINAL:
            # cancelled before the pipeline body started: record the terminal state here
            run = run.model_copy(update={"status": "cancelled", "updated_at": datetime.now(UTC)})
            await self.storage.update_run(run)
            await self.bus.publish(run_id, "status", "Status: cancelled", {"status": "cancelled"})
            await self.bus.publish(run_id, "error", "Run cancelled", {"error": "cancelled"})
        return run

    def subscribe(self, run_id: str) -> EventSubscription:
        return self.bus.subscribe(run_id)

    async def shutdown(self) -> None:
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
