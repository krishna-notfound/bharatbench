from typing import Any

from fastapi import APIRouter, HTTPException

from app.fix_prompt import finding_prompt, report_prompt
from app.models import Run
from app.services import get_run_service

router = APIRouter(prefix="/api/runs")


async def _finished(run_id: str) -> Run:
    run = await get_run_service().get_run(run_id)
    if run is None:
        raise HTTPException(404, f"Run {run_id} not found")
    if run.status != "done":
        raise HTTPException(409, "The run has not finished yet")
    return run


@router.get("/{run_id}/fix-prompt")
async def run_fix_prompt(run_id: str) -> dict[str, Any]:
    run = await _finished(run_id)
    findings = await get_run_service().list_findings(run_id)
    return {"prompt": report_prompt(run, findings), "findings": len(findings)}


@router.get("/{run_id}/findings/{finding_id}/fix-prompt")
async def finding_fix_prompt(run_id: str, finding_id: str) -> dict[str, str]:
    run = await _finished(run_id)
    finding = next((f for f in await get_run_service().list_findings(run_id) if f.id == finding_id), None)
    if finding is None:
        raise HTTPException(404, f"Finding {finding_id} not found")
    return {"prompt": finding_prompt(run, finding)}
