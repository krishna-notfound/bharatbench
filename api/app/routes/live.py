import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app.live import live_frame, live_state, read_replay
from app.models import Run
from app.services import get_run_service
from app.settings import Settings

router = APIRouter(prefix="/api/runs")


async def _require_run(run_id: str) -> Run:
    run = await get_run_service().get_run(run_id)
    if run is None:
        raise HTTPException(404, f"Run {run_id} not found")
    return run


@router.get("/{run_id}/live")
async def live(run_id: str) -> Response:
    run = await _require_run(run_id)
    data = await live_state(get_run_service(), run)
    return Response(json.dumps(data).encode(), media_type="application/json", headers={"Cache-Control": "no-store"})


@router.get("/{run_id}/live.png")
async def live_png(run_id: str) -> Response:
    run = await _require_run(run_id)
    frame = await live_frame(get_run_service(), run)
    if frame is None:
        raise HTTPException(404, "No live frame")
    return Response(frame, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.get("/{run_id}/replay")
async def replay(request: Request, run_id: str) -> dict[str, Any]:
    run = await _require_run(run_id)
    settings: Settings = request.app.state.settings
    return await read_replay(run, settings.data_dir / "runs" / run_id / "artifacts")

