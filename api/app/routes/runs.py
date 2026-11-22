import asyncio
import json
import uuid
from pathlib import Path
from typing import get_args

import anyio
from fastapi import APIRouter, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse

from app.access import rate_limit, request_user_id, require_run_owner, visible_run_ids
from app.auth.supabase import bearer_token, verify_token
from app.conversations.store import get_conversation_store
from app.models import Finding, ProfileId, Run, RunEvent, TestCredentials
from app.profiles import PROFILE_BY_ID, PROFILES
from app.report import render_markdown
from app.services import get_run_service
from app.settings import Settings

router = APIRouter(prefix="/api/runs")

MAX_APK_BYTES = 200 * 1024 * 1024
DEFAULT_PROFILES = "baseline,budget_2gb,flaky_network"
CHUNK = 1024 * 1024
ARTIFACT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".txt": "text/plain; charset=utf-8",
    ".log": "text/plain; charset=utf-8",
    ".xml": "text/plain; charset=utf-8",
    ".json": "application/json",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}


def parse_profiles(raw: str) -> list[ProfileId]:
    ids = [p.strip() for p in raw.split(",") if p.strip()] or DEFAULT_PROFILES.split(",")
    valid = set(get_args(ProfileId))
    unknown = [p for p in ids if p not in valid]
    if unknown:
        raise HTTPException(422, f"Unknown profile id(s): {', '.join(unknown)}")
    return list(dict.fromkeys(ids))  # type: ignore[arg-type]


async def _require_run(run_id: str) -> Run:
    run = await get_run_service().get_run(run_id)
    if run is None:
        raise HTTPException(404, f"Run {run_id} not found")
    return run


def parse_credentials(raw: str) -> TestCredentials | None:
    """Optional `credentials` JSON form field; lengths validated, never echoed back or logged."""
    if not raw.strip():
        return None
    try:
        return TestCredentials.model_validate_json(raw)
    except ValueError:
        raise HTTPException(422, "Invalid test account (login/password up to 200 characters, note up to 300)") from None


@router.post("", status_code=201)
async def create_run(
    request: Request,
    apk: UploadFile,
    profiles: str = Form(DEFAULT_PROFILES),
    credentials: str = Form(""),
    authorization: str | None = Header(default=None),
) -> Run:
    settings: Settings = request.app.state.settings
    rate_limit(request, "create_run", 10)
    user = await verify_token(bearer_token(authorization), settings)
    if user is None and settings.auth_required:
        raise HTTPException(401, "Sign in required", headers={"WWW-Authenticate": "Bearer"})
    name = Path(apk.filename or "").name
    if not name.lower().endswith(".apk"):
        raise HTTPException(400, "Only .apk files are accepted")
    profile_ids = parse_profiles(profiles)
    creds = parse_credentials(credentials)

    tmp_dir = settings.data_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp = tmp_dir / f"{uuid.uuid4().hex}.apk"
    size = 0
    try:
        async with await anyio.open_file(tmp, "wb") as out:
            while chunk := await apk.read(CHUNK):
                if size == 0 and not chunk.startswith(b"PK"):
                    raise HTTPException(400, "Uploaded file is not a valid APK (not a ZIP archive)")
                size += len(chunk)
                if size > MAX_APK_BYTES:
                    raise HTTPException(413, "APK exceeds the 200 MB limit")
                await out.write(chunk)
        if size == 0:
            raise HTTPException(400, "Uploaded file is empty")
        run = await get_run_service().create_run(str(tmp), name, profile_ids, credentials=creds)
        if user is not None:
            await get_conversation_store().set_run_owner(run.id, user.id)
        return run
    finally:
        tmp.unlink(missing_ok=True)


@router.get("")
async def list_runs(request: Request, authorization: str | None = Header(default=None)) -> list[Run]:
    settings: Settings = request.app.state.settings
    runs = await get_run_service().list_runs()
    allowed = await visible_run_ids(await request_user_id(authorization, settings), settings)
    return runs if allowed is None else [r for r in runs if r.id in allowed]


@router.get("/{run_id}")
async def get_run(run_id: str) -> Run:
    return await _require_run(run_id)


@router.get("/{run_id}/agent-tests")
async def agent_tests(request: Request, run_id: str) -> list[dict]:  # type: ignore[type-arg]
    """Tests the agent wrote for this run, with outcomes once the run is done (f23)."""
    await _require_run(run_id)
    f = request.app.state.settings.data_dir / "runs" / run_id / "artifacts" / "agent_tests.json"
    if not await anyio.Path(f).is_file():
        return []
    try:
        return json.loads(await anyio.Path(f).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


@router.get("/{run_id}/findings")
async def list_findings(run_id: str) -> list[Finding]:
    await _require_run(run_id)
    return await get_run_service().list_findings(run_id)


@router.get("/{run_id}/events")
async def list_events(run_id: str, after_seq: int = 0) -> list[RunEvent]:
    await _require_run(run_id)
    return await get_run_service().list_events(run_id, after_seq)


_retry_lock = asyncio.Lock()


@router.post("/{run_id}/retry")
async def retry_run(request: Request, run_id: str, authorization: str | None = Header(default=None)) -> Run:
    """Idempotent: re-run a run that ended cancelled/failed; repeated calls return the same new run."""
    service = get_run_service()
    async with _retry_lock:
        source = await _require_run(run_id)
        await require_run_owner(source, authorization, request.app.state.settings)
        rate_limit(request, "retry", 10)
        for ev in reversed(await service.list_events(run_id)):
            existing = (ev.data or {}).get("retry_run_id")
            if existing:
                found = await service.get_run(str(existing))
                if found is not None:
                    return found
        if source.status not in ("cancelled", "failed"):
            return source
        try:
            new = await service.rerun(run_id, source.profile_ids)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        await service.bus.publish(
            run_id, "log", "Retrying this test automatically", {"retry_run_id": new.id}
        )
        return new


@router.post("/{run_id}/cancel")
async def cancel_run(request: Request, run_id: str, authorization: str | None = Header(default=None)) -> Run:
    await require_run_owner(await _require_run(run_id), authorization, request.app.state.settings)
    run = await get_run_service().cancel_run(run_id)
    if run is None:
        raise HTTPException(404, f"Run {run_id} not found")
    return run


@router.get("/{run_id}/report.md")
async def report(run_id: str) -> PlainTextResponse:
    run = await _require_run(run_id)
    findings = await get_run_service().list_findings(run_id)
    profiles = [PROFILE_BY_ID[p] for p in run.profile_ids if p in PROFILE_BY_ID] or PROFILES
    return PlainTextResponse(render_markdown(run, findings, profiles), media_type="text/markdown")


@router.get("/{run_id}/artifacts/{path:path}")
async def artifact(request: Request, run_id: str, path: str) -> FileResponse:
    settings: Settings = request.app.state.settings
    await _require_run(run_id)
    base = (settings.data_dir / "runs" / run_id / "artifacts").resolve()
    target = (base / path).resolve()
    if not target.is_relative_to(base):
        raise HTTPException(400, "Invalid artifact path")
    if not target.is_file():
        raise HTTPException(404, "Artifact not found")
    kind = ARTIFACT_TYPES.get(target.suffix.lower())
    if kind is None:
        raise HTTPException(404, "Artifact not found")
    # Files come from the device under test: never let a browser treat them as HTML or script.
    return FileResponse(
        target,
        media_type=kind,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Content-Disposition": "inline" if kind.startswith(("image/", "video/")) else "attachment",
        },
    )
