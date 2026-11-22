from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from app import insights
from app.access import rate_limit, require_run_owner
from app.models import Run, RunService
from app.services import get_run_service
from app.settings import get_settings
from app.voice.languages import SESSION_LANGUAGES
from app.voice.sarvam_stt import SarvamError

router = APIRouter(prefix="/api/runs")


class BriefRequest(BaseModel):
    language: str = "auto"


async def _load(run_id: str) -> tuple[RunService, Run]:
    service = get_run_service()
    run = await service.get_run(run_id)
    if run is None:
        raise HTTPException(404, f"Run {run_id} not found")
    return service, run


@router.get("/{run_id}/play-risk")
async def play_risk(run_id: str) -> dict[str, Any]:
    service, run = await _load(run_id)
    on_play = await insights.play_listing(run.app.package_name if run.app else None)
    return insights.assess_play_risk(run, await service.list_findings(run_id), on_play)


@router.get("/{run_id}/compare")
async def compare(run_id: str) -> dict[str, Any]:
    service, run = await _load(run_id)
    result = await insights.compare_with_previous(service, run)
    if result is None:
        raise HTTPException(404, "No earlier finished run of this app to compare with")
    return result


@router.post("/{run_id}/brief")
async def brief(
    request: Request, run_id: str, body: BriefRequest, authorization: str | None = Header(default=None)
) -> dict[str, Any]:
    if body.language not in SESSION_LANGUAGES:
        raise HTTPException(422, f"Unsupported language {body.language}")
    service, run = await _load(run_id)
    await require_run_owner(run, authorization, getattr(request.app.state, "settings", None) or get_settings())
    rate_limit(request, "brief", 20)
    if run.status != "done":
        raise HTTPException(409, "The run has not finished yet")
    try:
        return await insights.build_brief(service, run, await service.list_findings(run_id), body.language)
    except SarvamError as exc:
        raise HTTPException(502, f"Could not write the brief: {exc}") from exc
