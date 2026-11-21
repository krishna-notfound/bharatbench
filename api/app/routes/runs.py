import uuid
from pathlib import Path
from typing import get_args

import anyio
from fastapi import APIRouter, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse

from app.auth.supabase import bearer_token, verify_token
from app.conversations.store import get_conversation_store
from app.models import Finding, ProfileId, Run, RunEvent
from app.profiles import PROFILE_BY_ID, PROFILES
from app.report import render_markdown
from app.services import get_run_service
from app.settings import Settings

router = APIRouter(prefix="/api/runs")

MAX_APK_BYTES = 200 * 1024 * 1024
DEFAULT_PROFILES = "baseline,budget_2gb,flaky_network"
CHUNK = 1024 * 1024


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


@router.post("", status_code=201)
async def create_run(
    request: Request,
    apk: UploadFile,
    profiles: str = Form(DEFAULT_PROFILES),
    authorization: str | None = Header(default=None),
) -> Run:
    settings: Settings = request.app.state.settings
    user = await verify_token(bearer_token(authorization), settings)
    if user is None and settings.auth_required:
        raise HTTPException(401, "Sign in required", headers={"WWW-Authenticate": "Bearer"})
    name = Path(apk.filename or "").name
    if not name.lower().endswith(".apk"):
        raise HTTPException(400, "Only .apk files are accepted")
    profile_ids = parse_profiles(profiles)

    tmp_dir = settings.data_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp = tmp_dir / f"{uuid.uuid4().hex}.apk"
    size = 0
    try:
        async with await anyio.open_file(tmp, "wb") as out:
            while chunk := await apk.read(CHUNK):
                size += len(chunk)
                if size > MAX_APK_BYTES:
                    raise HTTPException(413, "APK exceeds the 200 MB limit")
                await out.write(chunk)
        if size == 0:
            raise HTTPException(400, "Uploaded file is empty")
        run = await get_run_service().create_run(str(tmp), name, profile_ids)
        if user is not None:
            await get_conversation_store().set_run_owner(run.id, user.id)
        return run
    finally:
        tmp.unlink(missing_ok=True)


@router.get("")
async def list_runs(authorization: str | None = Header(default=None)) -> list[Run]:
    runs = await get_run_service().list_runs()
    user = await verify_token(bearer_token(authorization))
    if user is None:
        return runs
    owned = await get_conversation_store().run_ids_for_user(user.id)
    return [r for r in runs if r.id in owned]


@router.get("/{run_id}")
async def get_run(run_id: str) -> Run:
    return await _require_run(run_id)


@router.get("/{run_id}/findings")
async def list_findings(run_id: str) -> list[Finding]:
    await _require_run(run_id)
    return await get_run_service().list_findings(run_id)


@router.get("/{run_id}/events")
async def list_events(run_id: str, after_seq: int = 0) -> list[RunEvent]:
    await _require_run(run_id)
    return await get_run_service().list_events(run_id, after_seq)


@router.post("/{run_id}/cancel")
async def cancel_run(run_id: str) -> Run:
    await _require_run(run_id)
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
    return FileResponse(target)
