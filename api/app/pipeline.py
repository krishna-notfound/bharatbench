"""Run pipeline: static analysis -> harness -> runtime rules -> scoring -> done.

Runtime testing is skipped (with a recorded reason), never faked, when the harness is missing or fails.
"""

import asyncio
import contextlib
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
from app.live import write_steps
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
HARNESS_TIMEOUT_S = 15 * 60  # total runtime phase budget
STALL_TIMEOUT_S = 4 * 60  # no change in harness progress/events for this long = the test phone is stuck
UNREACHABLE_GRACE_S = 60.0  # consecutive failed polls tolerated before the harness counts as unreachable
SALVAGE_WAIT_S = 30.0  # after cancelling, how long to wait for the harness to settle before reading partial results
MIN_DISK_MB = 400  # harness reports less free disk than this: skip runtime, keep static
STATIC_TIMEOUT_S = 180.0


class HarnessLike(Protocol):
    async def health(self) -> dict[str, Any]: ...
    async def submit(self, apk_path: Path, request: HarnessJobRequest) -> HarnessJob: ...
    async def poll(self, job_id: str) -> HarnessJob: ...
    async def result(self, job_id: str) -> HarnessResult: ...
    async def download_artifact(self, job_id: str, path: str, dest: Path) -> None: ...
    async def cancel(self, job_id: str) -> HarnessJob: ...
    async def delete(self, job_id: str) -> None: ...
    async def aclose(self) -> None: ...


HarnessFactory = Callable[[], HarnessLike | None]


def load_analyzer() -> tuple[Callable[..., Any], Callable[..., Any]]:
    """Import the f03 analyzer lazily so the API runs before it is merged."""
    from app.analyzer import analyze_apk, runtime_findings

    return analyze_apk, runtime_findings


class _Skip(Exception):
    """Runtime testing cannot proceed; carries the user-facing reason and any partial harness result."""

    def __init__(self, reason: str, partial: HarnessResult | None = None) -> None:
        super().__init__(reason)
        self.partial = partial


def _profile_label(profile_id: str | None) -> str:
    if not profile_id:
        return "the test"
    try:
        from app.profiles import PROFILE_BY_ID

        return f"'{PROFILE_BY_ID[profile_id].name}'"
    except Exception:  # noqa: BLE001 - label lookup must never break recovery
        return f"'{profile_id}'"


STOP_BEFORE_DEVICE = "Stopped before the device test. Static results are below."


def _stop_note(profile_ids: list[str], partial: HarnessResult | None) -> str:
    """Human note for a user stop: what finished and what was not tested."""
    done = [p.profile_id for p in (partial.profiles if partial else []) if p.applied]
    total = len(profile_ids)
    remaining = [pid for pid in profile_ids if pid not in done]

    def names(ids: list[str]) -> str:
        return ", ".join(_profile_label(i).strip("'") for i in ids)

    if not done:
        return (
            f"Stopped early before any of the {total} conditions finished. Not tested: {names(remaining)}. "
            "Static results are below."
        )
    note = f"Stopped early after {len(done)} of {total} conditions ({names(done)})."
    if remaining:
        note += f" Not tested: {names(remaining)}."
    return note


def _stall_reason(profile_id: str | None) -> str:
    return (
        f"The test phone stopped responding during {_profile_label(profile_id)} and we stopped that test. "
        "It resets itself before the next run; static results are below. Try again in a minute."
    )


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
    out = result.model_copy(update={"profiles": profiles})
    try:
        write_steps(out, art_dir)
    except (OSError, ValueError) as exc:
        log.warning("Could not write step replay for run %s: %s", run_id, exc)
    return out


def _kind(rel: str) -> str:
    suffix = Path(rel).suffix.lower()
    return {".png": "screenshot", ".xml": "ui_dump", ".txt": "logcat", ".yaml": "flow", ".yml": "flow"}.get(
        suffix, "file"
    )


async def _salvage(
    client: HarnessLike, bus: EventBus, run_id: str, job_id: str, art_dir: Path
) -> HarnessResult | None:
    """Cancel a stuck/failed harness job and recover whatever profiles completed. Never raises."""
    try:
        await bus.publish(run_id, "log", "Recovery: stopping the test phone job")
        with contextlib.suppress(Exception):
            await client.cancel(job_id)
        deadline = time.monotonic() + SALVAGE_WAIT_S
        while time.monotonic() < deadline:
            job = await client.poll(job_id)
            if job.status not in ("queued", "running"):
                break
            await asyncio.sleep(POLL_INTERVAL_S)
        result = await client.result(job_id)
        done = [p for p in result.profiles if p.applied]
        if not done:
            return None
        result = result.model_copy(update={"profiles": done, "security": []})
        await bus.publish(run_id, "log", f"Recovery: kept partial results for {len(done)} completed condition(s)")
        return await _download_artifacts(client, bus, run_id, job_id, result, art_dir)
    except Exception as exc:  # noqa: BLE001 - salvage is best effort
        await bus.publish(run_id, "log", f"Recovery: no partial results ({type(exc).__name__})")
        return None


async def _cleanup_job(client: HarnessLike, bus: EventBus, run_id: str, job_id: str) -> None:
    """Free the harness disk once artifacts are downloaded (or abandoned). Never raises."""
    try:
        await client.delete(job_id)
        await bus.publish(run_id, "log", "Test lab cleaned up")
    except Exception as exc:  # noqa: BLE001
        log.warning("Harness cleanup of job %s failed: %s", job_id, exc)


async def _run_harness(
    client: HarnessLike | None,
    storage: Storage,
    bus: EventBus,
    run: Run,
    apk_path: Path,
    art_dir: Path,
    job_ids: dict[str, str],
    journey_steps: int | None = None,
    stop_flags: set[str] | None = None,
) -> tuple[Run, HarnessResult]:
    stop_flags = stop_flags if stop_flags is not None else set()
    if client is None:
        raise _Skip("Harness not configured (HARNESS_URL unset); runtime testing skipped.")
    job_id: str | None = None
    try:
        info = await client.health()
        free = info.get("disk_free_mb") if isinstance(info, dict) else None
        if isinstance(free, int | float) and free < MIN_DISK_MB:
            await bus.publish(run.id, "log", f"Test lab disk is low ({free:.0f} MB free)")
            raise _Skip("The test lab is cleaning up, try again shortly. Static results are below.")
        if run.id in stop_flags:
            raise _Skip(STOP_BEFORE_DEVICE)
        run = await _set_status(storage, bus, run, "provisioning")
        assert run.app is not None
        try:
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
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 409:
                raise _Skip("The test phone is busy with another run. Try again in a few minutes.") from exc
            raise
        job_id = job.job_id
        job_ids[run.id] = job_id
        await bus.publish(run.id, "log", "Test phone job started", {"job_id": job_id})
        run = await _set_status(storage, bus, run, "running")
        seen_events = 0
        last_profile = None
        started = last_change = last_ok = time.monotonic()
        signature: tuple[Any, ...] = ()
        while True:
            try:
                job = await client.poll(job_id)
            except (httpx.HTTPError, OSError) as exc:
                if time.monotonic() - last_ok > UNREACHABLE_GRACE_S:
                    raise _Skip(
                        "The test lab stopped answering mid-run (harness unreachable). "
                        f"Static results are below. Try again in a minute. ({type(exc).__name__})"
                    ) from exc
                await asyncio.sleep(POLL_INTERVAL_S)
                continue
            last_ok = time.monotonic()
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
            if run.id in stop_flags:
                partial = await _salvage(client, bus, run.id, job_id, art_dir)
                raise _Skip(_stop_note(run.profile_ids, partial), partial)
            if job.status in ("failed", "cancelled"):
                detail = job.error or "no detail"
                raise _Skip(
                    f"The test lab could not finish this run ({detail}). Static results are below.",
                    await _salvage(client, bus, run.id, job_id, art_dir),
                )
            now = time.monotonic()
            sig = (job.progress, len(job.events), job.current_profile, job.status)
            if sig != signature:
                signature, last_change = sig, now
            if now - last_change > STALL_TIMEOUT_S:
                where = _profile_label(job.current_profile)
                await bus.publish(
                    run.id, "log", f"Watchdog: no progress for {STALL_TIMEOUT_S / 60:g} minutes during {where}"
                )
                raise _Skip(
                    _stall_reason(job.current_profile), await _salvage(client, bus, run.id, job_id, art_dir)
                )
            if now - started > HARNESS_TIMEOUT_S:
                await bus.publish(
                    run.id, "log", f"Watchdog: runtime testing exceeded {HARNESS_TIMEOUT_S / 60:g} minutes"
                )
                raise _Skip(
                    f"Runtime testing took longer than {HARNESS_TIMEOUT_S / 60:g} minutes and was stopped. "
                    "Static results are below; try again in a minute.",
                    await _salvage(client, bus, run.id, job_id, art_dir),
                )
            await asyncio.sleep(POLL_INTERVAL_S)
        result = await client.result(job_id)
        result = await _download_artifacts(client, bus, run.id, job_id, result, art_dir)
    except (httpx.HTTPError, OSError) as exc:
        if job_id is not None:
            await bus.publish(run.id, "log", f"Recovery: test lab error ({type(exc).__name__}: {exc})")
        raise _Skip(
            f"The test lab is unreachable or errored ({type(exc).__name__}). "
            "Static results are below. Try again in a minute."
        ) from exc
    finally:
        if job_id is not None:
            await asyncio.shield(_cleanup_job(client, bus, run.id, job_id))
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
    stop_flags: set[str] | None = None,
) -> None:
    job_ids = job_ids if job_ids is not None else {}
    stop_flags = stop_flags if stop_flags is not None else set()
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
            if run_id in stop_flags:
                raise _Skip(STOP_BEFORE_DEVICE)
            client = harness_factory()
            run, result = await _run_harness(
                client, storage, bus, run, apk_path, data_dir / "runs" / run_id / "artifacts", job_ids,
                journey_steps, stop_flags,
            )
            collected.extend(runtime_findings(run_id, result, package=app_info.package_name))
            runtime_executed = True
        except _Skip as skip:
            skipped_reason = str(skip)
            if run_id in stop_flags:
                await bus.publish(run_id, "log", skipped_reason)
            else:
                await bus.publish(run_id, "log", f"Runtime testing skipped: {skipped_reason}")
            if skip.partial is not None and skip.partial.profiles:
                with contextlib.suppress(Exception):
                    collected.extend(runtime_findings(run_id, skip.partial, package=app_info.package_name))
                runtime_executed = run_id in stop_flags  # a user stop that kept finished conditions did run

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
        # server shutdown / watchdog: leave the run exactly as it is; startup recovery resumes it
        raise
    except Exception as exc:  # any failure must leave the run terminal
        log.exception("Pipeline failed for run %s", run_id)
        message = str(exc) or type(exc).__name__
        run = await _set_status(storage, bus, run, "failed", error=message)
        await bus.publish(run_id, "error", message, {"error": message})
    finally:
        stop_flags.discard(run_id)
        if client is not None:
            await client.aclose()
