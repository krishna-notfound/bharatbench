"""Run pipeline: static analysis -> harness -> runtime rules -> scoring -> done.

Runtime testing is skipped (with a recorded reason), never faked, when the harness is missing or fails.
"""

import asyncio
import logging
import time
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import httpx

from app.analyzer.dedupe import dedupe_findings
from app.analyzer.explain import explain_findings
from app.events import EventBus
from app.models import (
    AppInfo,
    Finding,
    HarnessJob,
    HarnessJobRequest,
    HarnessResult,
    Run,
    RunStatus,
)
from app.scoring import score_findings, summarize
from app.storage.base import Storage

log = logging.getLogger(__name__)

POLL_INTERVAL_S = 2.0
HARNESS_TIMEOUT_S = 15 * 60
STATIC_TIMEOUT_S = 180.0


class HarnessLike(Protocol):
    async def health(self) -> dict[str, Any]: ...
    async def submit(self, apk_path: Path, request: HarnessJobRequest) -> HarnessJob: ...
    async def poll(self, job_id: str) -> HarnessJob: ...
    async def result(self, job_id: str) -> HarnessResult: ...
    async def download_artifact(self, job_id: str, path: str, dest: Path) -> None: ...
    async def cancel(self, job_id: str) -> HarnessJob: ...
    async def aclose(self) -> None: ...


HarnessFactory = Callable[[], HarnessLike | None]


def load_analyzer() -> tuple[Callable[..., Any], Callable[..., Any]]:
    """Import the f03 analyzer lazily so the API runs before it is merged."""
    from app.analyzer import analyze_apk, runtime_findings

    return analyze_apk, runtime_findings


class _Skip(Exception):
    """Runtime testing cannot proceed; carries the user-facing reason."""


async def _set_status(storage: Storage, bus: EventBus, run: Run, status: RunStatus, **changes: Any) -> Run:
    run = run.model_copy(update={"status": status, "updated_at": datetime.now(UTC), **changes})
    await storage.update_run(run)
    await bus.publish(run.id, "status", f"Status: {status}", {"status": status})
    return run


async def _store_findings(storage: Storage, bus: EventBus, run_id: str, scored: list[Finding]) -> None:
    await storage.add_findings(run_id, scored)
    for f in scored:
        await bus.publish(
            run_id, "finding", f.title, {"finding_id": f.id, "severity": f.severity, "title": f.title}
        )


def _artifact_refs(result: HarnessResult) -> list[tuple[str, str]]:
    """(profile_id, harness-relative path) for every artifact referenced by the result."""
    refs: list[tuple[str, str]] = []
    for p in result.profiles:
        if p.logcat:
            refs.append((p.profile_id, p.logcat))
        for s in p.screens:
            for path in (s.screenshot, s.ui_dump):
                if path:
                    refs.append((p.profile_id, path))
    return refs


async def _download_artifacts(
    client: HarnessLike, bus: EventBus, run_id: str, job_id: str, result: HarnessResult, art_dir: Path
) -> HarnessResult:
    """Download every artifact and rewrite refs to `{profile_id}/{file}`; undownloadable refs become None."""
    mapping: dict[tuple[str, str], str | None] = {}
    for profile_id, path in _artifact_refs(result):
        if (profile_id, path) in mapping:
            continue
        rel = f"{profile_id}/{Path(path).name}"
        try:
            await client.download_artifact(job_id, path, art_dir / profile_id / Path(path).name)
        except (httpx.HTTPError, OSError) as exc:
            await bus.publish(run_id, "log", f"Could not download artifact {path}: {exc}")
            mapping[(profile_id, path)] = None
            continue
        mapping[(profile_id, path)] = rel
        await bus.publish(run_id, "artifact", rel, {"path": rel, "kind": _kind(rel)})

    def remap(profile_id: str, path: str | None) -> str | None:
        return mapping.get((profile_id, path)) if path else None

    profiles = []
    for p in result.profiles:
        screens = [
            s.model_copy(
                update={
                    "screenshot": remap(p.profile_id, s.screenshot),
                    "ui_dump": remap(p.profile_id, s.ui_dump),
                }
            )
            for s in p.screens
        ]
        profiles.append(p.model_copy(update={"screens": screens, "logcat": remap(p.profile_id, p.logcat)}))
    return result.model_copy(update={"profiles": profiles})


def _kind(rel: str) -> str:
    suffix = Path(rel).suffix.lower()
    return {".png": "screenshot", ".xml": "ui_dump", ".txt": "logcat", ".yaml": "flow", ".yml": "flow"}.get(
        suffix, "file"
    )


async def _run_harness(
    client: HarnessLike | None,
    storage: Storage,
    bus: EventBus,
    run: Run,
    apk_path: Path,
    art_dir: Path,
    job_ids: dict[str, str],
    journey_steps: int | None = None,
) -> tuple[Run, HarnessResult]:
    if client is None:
        raise _Skip("Harness not configured (HARNESS_URL unset); runtime testing skipped.")
    try:
        await client.health()
        run = await _set_status(storage, bus, run, "provisioning")
        assert run.app is not None
        job = await client.submit(
            apk_path,
            HarnessJobRequest(
                run_id=run.id,
                package_name=run.app.package_name,
                main_activity=run.app.main_activity,
                profiles=run.profile_ids,
                **({"journey_steps": min(journey_steps, 20)} if journey_steps else {}),
            ),
        )
        job_ids[run.id] = job.job_id
        run = await _set_status(storage, bus, run, "running")
        seen_events = 0
        last_profile = None
        deadline = time.monotonic() + HARNESS_TIMEOUT_S
        while True:
            job = await client.poll(job.job_id)
            for line in job.events[seen_events:]:
                await bus.publish(run.id, "log", line)
            seen_events = len(job.events)
            if job.current_profile and job.current_profile != last_profile:
                last_profile = job.current_profile
                step = run.profile_ids.index(last_profile) + 1 if last_profile in run.profile_ids else 0
                await bus.publish(
                    run.id,
                    "step",
                    f"Profile {last_profile} ({step}/{len(run.profile_ids)})",
                    {"profile_id": last_profile, "step": step},
                )
            if job.status == "done":
                break
            if job.status in ("failed", "cancelled"):
                raise _Skip(f"Harness job {job.status}: {job.error or 'no detail'}")
            if time.monotonic() > deadline:
                await client.cancel(job.job_id)
                raise _Skip(f"Harness timed out after {HARNESS_TIMEOUT_S // 60} minutes.")
            await asyncio.sleep(POLL_INTERVAL_S)
        result = await client.result(job.job_id)
        result = await _download_artifacts(client, bus, run.id, job.job_id, result, art_dir)
    except (httpx.HTTPError, OSError) as exc:
        raise _Skip(f"Harness unreachable or errored: {exc}") from exc
    return run, result


async def run_pipeline(
    run_id: str,
    *,
    storage: Storage,
    bus: EventBus,
    data_dir: Path,
    harness_factory: HarnessFactory,
    job_ids: dict[str, str] | None = None,
    journey_steps: int | None = None,
) -> None:
    job_ids = job_ids if job_ids is not None else {}
    client: HarnessLike | None = None
    run = await storage.get_run(run_id)
    apk_path_str = await storage.get_apk_path(run_id)
    if run is None or apk_path_str is None:
        return
    apk_path = Path(apk_path_str)
    try:
        run = await _set_status(storage, bus, run, "analyzing")
        if not zipfile.is_zipfile(apk_path):
            raise ValueError("Uploaded file is not a valid APK (not a ZIP archive).")
        analyze_apk, runtime_findings = load_analyzer()
        app_info, static = await asyncio.wait_for(
            asyncio.to_thread(analyze_apk, apk_path, run_id), timeout=STATIC_TIMEOUT_S
        )
        app_info = AppInfo.model_validate(app_info)
        run = run.model_copy(update={"app": app_info, "updated_at": datetime.now(UTC)})
        await storage.update_run(run)
        await bus.publish(run_id, "log", f"Static analysis found {len(static)} findings.")
        collected: list[Finding] = list(static)

        runtime_executed = False
        skipped_reason: str | None = None
        try:
            client = harness_factory()
            run, result = await _run_harness(
                client, storage, bus, run, apk_path, data_dir / "runs" / run_id / "artifacts", job_ids,
                journey_steps,
            )
            collected.extend(runtime_findings(run_id, result, package=app_info.package_name))
            runtime_executed = True
        except _Skip as skip:
            skipped_reason = str(skip)
            await bus.publish(run_id, "log", f"Runtime testing skipped: {skipped_reason}")

        run = await _set_status(storage, bus, run, "scoring")
        baseline_ran = runtime_executed and "baseline" in run.profile_ids
        scored = score_findings(dedupe_findings(collected, baseline_ran=baseline_ran))
        await bus.publish(run_id, "log", f"Explaining top findings\u2026 ({len(scored)} findings after dedupe)")
        scored, explained = await explain_findings(scored)
        await bus.publish(run_id, "log", f"Explanations done: {explained} finding(s) explained.")
        await _store_findings(storage, bus, run_id, scored)
        all_findings = await storage.list_findings(run_id)
        summary = summarize(all_findings, runtime_executed, skipped_reason)
        run = await _set_status(storage, bus, run, "done", summary=summary)
        await bus.publish(run_id, "done", "Run complete", {"summary": summary.model_dump(mode="json")})
    except asyncio.CancelledError:
        await asyncio.shield(_on_cancel(storage, bus, run, client, job_ids.get(run_id)))
        raise
    except Exception as exc:  # any failure must leave the run terminal
        log.exception("Pipeline failed for run %s", run_id)
        message = str(exc) or type(exc).__name__
        run = await _set_status(storage, bus, run, "failed", error=message)
        await bus.publish(run_id, "error", message, {"error": message})
    finally:
        if client is not None:
            await client.aclose()


async def _on_cancel(
    storage: Storage, bus: EventBus, run: Run, client: HarnessLike | None, job_id: str | None
) -> None:
    if client is not None and job_id:
        try:
            await client.cancel(job_id)
        except (httpx.HTTPError, OSError) as exc:
            log.warning("Harness cancel failed: %s", exc)
    await _set_status(storage, bus, run, "cancelled")
    await bus.publish(run.id, "error", "Run cancelled", {"error": "cancelled"})
