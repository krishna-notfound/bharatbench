"""Tool registry: reuses api/app/voice/tools.py (7 tools) and adds friendly labels for tool.started."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.models import RunService
from app.voice import tools as voice_tools

TOOL_TIMEOUT_S = 20.0
MAX_TOOL_ROUNDS = 4

LABELS = {
    "list_profiles": "Checking available test conditions",
    "list_runs": "Looking at recent tests",
    "start_test": "Starting a test",
    "get_run_status": "Checking test status",
    "list_findings": "Reading findings",
    "explain_finding": "Reading finding details",
    "cancel_run": "Cancelling the test",
    "get_report": "Reading the full report",
    "suggest_improvements": "Working out what to improve",
    "run_deeper_tests": "Starting deeper tests",
    "get_finding_evidence": "Looking at the evidence",
    "compare_runs": "Comparing the two runs",
}

TOOL_SCHEMAS = voice_tools.TOOL_SCHEMAS
ToolContext = voice_tools.ToolContext


def label_for(name: str) -> str:
    return LABELS.get(name, f"Running {name}")


async def run_tool(
    service: RunService, name: str, args: dict[str, Any], ctx: ToolContext
) -> tuple[bool, dict[str, Any], str]:
    """Execute one tool with a timeout. Returns (ok, result, short summary)."""
    try:
        result = await asyncio.wait_for(voice_tools.dispatch(service, name, args, ctx), TOOL_TIMEOUT_S)
    except TimeoutError:
        result = {"error": f"{name} timed out after {int(TOOL_TIMEOUT_S)}s"}
    ok = "error" not in result
    summary = str(result["error"]) if not ok else json.dumps(result, default=str)
    return ok, result, summary[:200]
