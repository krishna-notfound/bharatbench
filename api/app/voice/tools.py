"""Agent tools (contracts/README.md section 6): schemas for the LLM and dispatch onto RunService."""

from __future__ import annotations

from typing import Any, get_args

from app.models import Finding, ProfileId, Run, RunService
from app.profiles import PROFILES

DEFAULT_PROFILES: list[ProfileId] = ["baseline", "budget_2gb", "flaky_network"]
_PROFILE_IDS = list(get_args(ProfileId))


def _fn(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


TOOL_SCHEMAS: list[dict[str, Any]] = [
    _fn("list_profiles", "List the available test profiles (conditions) with fidelity.", {}, []),
    _fn(
        "list_runs",
        "List recent test runs: id, apk, status, reliability score.",
        {"limit": {"type": "integer", "description": "Max runs, default 5"}},
        [],
    ),
    _fn(
        "start_test",
        "Start a new test by re-running an already uploaded APK. Returns immediately with the new run id.",
        {
            "apk_run_id": {
                "type": "string",
                "description": "Run id (from list_runs) whose APK to re-run; default the active run",
            },
            "apk_name": {
                "type": "string",
                "description": "Alternative to apk_run_id: APK file name, e.g. fdroid.apk",
            },
            "profiles": {
                "type": "array",
                "items": {"type": "string", "enum": _PROFILE_IDS},
                "description": "Profile ids to test under",
            },
        },
        ["profiles"],
    ),
    _fn(
        "get_run_status",
        "Status, recent progress events and summary of a run.",
        {"run_id": {"type": "string"}},
        ["run_id"],
    ),
    _fn(
        "list_findings",
        "Top findings of a run by impact score.",
        {
            "run_id": {"type": "string"},
            "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
            "limit": {"type": "integer", "description": "Max findings, default 5"},
        },
        ["run_id"],
    ),
    _fn(
        "explain_finding",
        "Full detail of one finding: evidence, probable cause, suggested fix, repro steps.",
        {"finding_id": {"type": "string"}},
        ["finding_id"],
    ),
    _fn(
        "cancel_run",
        "Cancel a run. Only when the user explicitly asked to cancel or stop it.",
        {"run_id": {"type": "string"}},
        ["run_id"],
    ),
]


class ToolContext:
    """What tools may read about the session: the active run."""

    def __init__(self, active_run_id: str | None = None) -> None:
        self.active_run_id = active_run_id


def _run_brief(run: Run) -> dict[str, Any]:
    return {
        "id": run.id,
        "apk": run.apk_name,
        "status": run.status,
        "score": run.summary.reliability_score if run.summary else None,
    }


def _finding_brief(f: Finding) -> dict[str, Any]:
    return {
        "id": f.id,
        "title": f.title,
        "severity": f.severity,
        "score": f.impact.score if f.impact else None,
    }


def _sorted_findings(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: f.impact.score if f.impact else 0.0, reverse=True)


async def _resolve_run(service: RunService, ref: str | None, ctx: ToolContext) -> Run | None:
    """Find a run by id; fall back to apk name (models often pass 'fdroid.apk' or 'fdroid' as a run id)."""
    if not ref:
        return None
    ref = str(ref).strip()
    run = await service.get_run(ref)
    if run is not None:
        return run
    needle = ref.lower().removesuffix(".apk")
    runs = await service.list_runs()  # newest first
    for pool in ([r for r in runs if r.status != "failed"], runs):
        for r in pool:
            if needle and needle in r.apk_name.lower():
                return r
    return None


async def _find_finding(service: RunService, finding_id: str, ctx: ToolContext) -> Finding | None:
    run_ids: list[str] = [ctx.active_run_id] if ctx.active_run_id else []
    run_ids += [r.id for r in await service.list_runs() if r.id != ctx.active_run_id]
    for run_id in run_ids:
        for f in await service.list_findings(run_id):
            if f.id == finding_id:
                return f
    return None


async def dispatch(service: RunService, name: str, args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Run one tool. Failures are returned as {"error": ...} for the LLM to report honestly."""
    try:
        return await _dispatch(service, name, args, ctx)
    except (LookupError, ValueError, TypeError, RuntimeError, OSError) as exc:
        return {"error": f"{name} failed: {type(exc).__name__}: {exc}"}


async def _dispatch(service: RunService, name: str, args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    if name == "list_profiles":
        return {"profiles": [{"id": p.id, "name": p.name, "fidelity": p.fidelity} for p in PROFILES]}
    if name == "list_runs":
        runs = await service.list_runs()
        return {"runs": [_run_brief(r) for r in runs[: int(args.get("limit") or 5)]]}
    if name == "start_test":
        return await _start_test(service, args, ctx)
    if name == "get_run_status":
        run = await _resolve_run(service, args["run_id"], ctx)
        if run is None:
            return {"error": f"run {args['run_id']} not found; use an id from list_runs"}
        events = await service.list_events(run.id)
        return {
            **_run_brief(run),
            "error_message": run.error,
            "summary": run.summary.model_dump() if run.summary else None,
            "recent_events": [e.message for e in events[-5:]],
        }
    if name == "list_findings":
        run = await _resolve_run(service, args["run_id"], ctx)
        if run is None:
            return {"error": f"run {args['run_id']} not found; use an id from list_runs"}
        findings = _sorted_findings(await service.list_findings(run.id))
        severity = args.get("severity")
        if severity:
            findings = [f for f in findings if f.severity == severity]
        return {"findings": [_finding_brief(f) for f in findings[: int(args.get("limit") or 5)]]}
    if name == "explain_finding":
        finding = await _find_finding(service, str(args["finding_id"]), ctx)
        if finding is None:
            return {"error": f"finding {args['finding_id']} not found"}
        data = finding.model_dump(mode="json", exclude={"repro_flow"})
        data["evidence"] = [
            {"kind": e["kind"], "excerpt": (e.get("excerpt") or "")[:300]} for e in data["evidence"]
        ]
        return data
    if name == "cancel_run":
        target = await _resolve_run(service, args["run_id"], ctx)
        if target is None:
            return {"error": f"run {args['run_id']} not found; use an id from list_runs"}
        if target.status in ("done", "failed", "cancelled"):
            return {"run_id": target.id, "status": target.status, "note": "run already finished; nothing to cancel"}
        run = await service.cancel_run(target.id)
        if run is None:
            return {"error": f"run {args['run_id']} not found"}
        return {"run_id": run.id, "status": run.status}
    return {"error": f"unknown tool {name}"}


async def _start_test(service: RunService, args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    requested = args.get("profiles") or DEFAULT_PROFILES
    profiles = [p for p in requested if p in _PROFILE_IDS]
    if not profiles:
        return {"error": f"no valid profile ids; valid: {_PROFILE_IDS}"}
    ref = args.get("apk_run_id") or args.get("apk_name")
    source_run = await _resolve_run(service, ref, ctx) if ref else None
    if ref and source_run is None:
        return {"error": f"no uploaded APK matching {ref}; use list_runs to see available APKs"}
    if source_run is None and ctx.active_run_id:
        source_run = await service.get_run(ctx.active_run_id)
    if source_run is None:
        runs = await service.list_runs()
        if not runs:
            return {"error": "no uploaded APK yet; ask the user to upload an APK in the web UI"}
        source_run = next((r for r in runs if r.status != "failed"), runs[0])
    run = await service.rerun(source_run.id, profiles)
    return {"run_id": run.id, "status": run.status, "profiles": profiles}
