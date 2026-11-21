"""Agent tools (contracts/README.md section 6): schemas for the LLM and dispatch onto RunService."""

from __future__ import annotations

import os
from typing import Any, get_args

from app.models import Finding, ProfileId, Run, RunService
from app.planner import TestPlan, plan_followup, plan_initial
from app.profiles import PROFILES, UNSUPPORTED_CONDITIONS

_FOCUS = ("security", "performance", "reliability", "network", "all")
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
    _fn(
        "get_report",
        "Compact full report of a run: app, status, score, profiles run and whether each applied, top findings with "
        "cause and fix, counts. Call this first to summarise a finished test.",
        {"run_id": {"type": "string", "description": "Run id from list_runs (apk name also accepted)"}},
        ["run_id"],
    ),
    _fn(
        "suggest_improvements",
        "Prioritised list of what to fix, built only from this run's findings, grouped by root cause, with finding ids.",
        {
            "run_id": {"type": "string"},
            "focus": {"type": "string", "enum": list(_FOCUS), "description": "Limit to one area, default all"},
        },
        ["run_id"],
    ),
    _fn(
        "run_deeper_tests",
        "Re-run the same APK for more coverage: by default every supported profile not yet run, with a longer "
        "journey (16 steps). Returns the new run id immediately; the test runs in the background.",
        {
            "run_id": {"type": "string", "description": "Run whose APK to test again; default the active run"},
            "profiles": {"type": "array", "items": {"type": "string", "enum": _PROFILE_IDS}},
            "journey_steps": {"type": "integer", "description": "Journey length, default 16, max 20"},
        },
        [],
    ),
    _fn(
        "get_finding_evidence",
        "Evidence of one finding: log excerpts and artifact URLs (screenshots, logs) to describe honestly.",
        {"finding_id": {"type": "string"}},
        ["finding_id"],
    ),
    _fn(
        "plan_tests",
        "Decide which tests to run and why, WITHOUT starting anything. plan_kind 'initial' plans from the app's "
        "permissions and size; 'followup' plans from the findings of a finished run. Returns profiles, "
        "journey_steps and a plain-language reason per profile.",
        {
            "apk_or_run": {"type": "string", "description": "Run id or apk name; default the active run"},
            "plan_kind": {
                "type": "string",
                "enum": ["initial", "followup"],
                "description": "default: followup if the run finished, else initial",
            },
        },
        [],
    ),
    _fn(
        "start_planned_test",
        "Compute the test plan (same as plan_tests) and START it. Returns the new run id and the reasons, so you "
        "can tell the user why those tests were chosen.",
        {
            "apk_or_run": {"type": "string", "description": "Run id or apk name; default the active run"},
            "plan_kind": {"type": "string", "enum": ["initial", "followup"]},
        },
        [],
    ),
    _fn(
        "compare_runs",
        "Compare two runs: score delta and fixed / new / persisting findings.",
        {"run_a": {"type": "string", "description": "Older / baseline run"}, "run_b": {"type": "string"}},
        ["run_a", "run_b"],
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
    if name in _NEW_TOOLS:
        return await _NEW_TOOLS[name](service, args, ctx)
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


# ---------- f16: report, improvement and deeper-test tools ----------

_FOCUS_CATEGORIES: dict[str, set[str]] = {
    "security": {"security"},
    "performance": {"performance", "memory", "storage"},
    "reliability": {"reliability", "memory", "storage"},
    "network": {"network"},
}
DEEP_JOURNEY_STEPS = 16
MAX_JOURNEY_STEPS = 20
UNSUPPORTED_NOTE = "Not simulated: " + ", ".join(k.replace("_", " ") for k in UNSUPPORTED_CONDITIONS) + "."


def _clip(text: str | None, n: int = 140) -> str:
    one = " ".join((text or "").split())
    return one if len(one) <= n else one[: n - 1] + "..."


def _api_base() -> str:
    return os.environ.get("API_BASE", "").rstrip("/")


def _impact(f: Finding) -> float:
    return round(f.impact.score, 1) if f.impact else 0.0


async def _load_run_and_findings(
    service: RunService, ref: Any, ctx: ToolContext
) -> tuple[Run | None, list[Finding]]:
    run = await _resolve_run(service, ref or ctx.active_run_id, ctx)
    if run is None:
        return None, []
    return run, _sorted_findings(await service.list_findings(run.id))


def _not_found(ref: Any) -> dict[str, Any]:
    return {"error": f"run {ref} not found; use an id from list_runs"}


def _profile_rows(run: Run, findings: list[Finding]) -> list[dict[str, Any]]:
    skipped = {f.profile_id: _clip(f.description, 120) for f in findings if f.rule_id == "rt.profile_not_applied"}
    executed = bool(run.summary and run.summary.runtime_executed)
    rows: list[dict[str, Any]] = []
    for pid in run.profile_ids:
        if not executed:
            rows.append({"id": pid, "applied": False, "why": "runtime testing did not run"})
        elif pid in skipped:
            rows.append({"id": pid, "applied": False, "why": skipped[pid]})
        else:
            rows.append({"id": pid, "applied": True})
    return rows


async def _get_report(service: RunService, args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    run, findings = await _load_run_and_findings(service, args.get("run_id"), ctx)
    if run is None:
        return _not_found(args.get("run_id"))
    s = run.summary
    app = run.app
    report: dict[str, Any] = {
        "run_id": run.id,
        "apk": run.apk_name,
        "app": (
            {
                "name": app.app_name,
                "package": app.package_name,
                "version": app.version_name,
                "target_sdk": app.target_sdk,
                "size_mb": round(app.size_bytes / 1_048_576, 1),
            }
            if app
            else None
        ),
        "status": run.status,
        "error": _clip(run.error, 200) or None,
        "score": s.reliability_score if s else None,
        "profiles": _profile_rows(run, findings),
        "runtime_executed": s.runtime_executed if s else False,
        "runtime_skipped_reason": _clip(s.runtime_skipped_reason, 200) if s and s.runtime_skipped_reason else None,
        "counts": s.counts if s else None,
        "total_findings": len(findings),
        "top_findings": [
            {
                "id": f.id,
                "severity": f.severity,
                "title": _clip(f.title, 90),
                "profile": f.profile_id,
                "impact": _impact(f),
                "cause": _clip(f.probable_cause),
                "fix": _clip(f.suggested_fix),
            }
            for f in findings[:8]
        ],
        "unsupported_conditions": UNSUPPORTED_NOTE,
    }
    if run.status not in ("done", "failed", "cancelled"):
        report["note"] = "run is still in progress; results are partial or missing"
    return report


async def _suggest_improvements(service: RunService, args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    run, findings = await _load_run_and_findings(service, args.get("run_id"), ctx)
    if run is None:
        return _not_found(args.get("run_id"))
    focus = args.get("focus") or "all"
    if focus not in _FOCUS:
        return {"error": f"focus must be one of {list(_FOCUS)}"}
    if focus != "all":
        findings = [f for f in findings if f.category in _FOCUS_CATEGORIES[focus]]
    groups: dict[tuple[str, str], list[Finding]] = {}
    for f in findings:
        if f.rule_id == "rt.profile_not_applied":
            continue  # a skipped condition is not an app defect
        key = (f.rule_id, _clip(f.suggested_fix or f.probable_cause or f.title, 80))
        groups.setdefault(key, []).append(f)
    actions = []
    for (rule_id, _), fs in groups.items():
        top = fs[0]  # findings are impact-sorted
        actions.append(
            {
                "rule_id": rule_id,
                "area": top.category,
                "severity": top.severity,
                "total_impact": round(sum(_impact(f) for f in fs), 1),
                "problem": _clip(top.title, 100),
                "why": _clip(top.probable_cause),
                "fix": _clip(top.suggested_fix, 220) or "no fix text recorded for this finding",
                "evidence_finding_ids": [f.id for f in fs[:5]],
                "profiles": sorted({f.profile_id for f in fs if f.profile_id}),
            }
        )
    actions.sort(key=lambda a: a["total_impact"], reverse=True)
    result: dict[str, Any] = {
        "run_id": run.id,
        "focus": focus,
        "actions": [{"priority": i + 1, **a} for i, a in enumerate(actions[:8])],
    }
    if not actions:
        result["note"] = "no findings in this run for that focus; nothing to improve from this evidence"
    return result


async def _run_deeper_tests(service: RunService, args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    ref = args.get("run_id") or ctx.active_run_id
    if ref:
        source = await _resolve_run(service, ref, ctx)
        if source is None:
            return _not_found(ref)
    else:
        runs = await service.list_runs()
        if not runs:
            return {"error": "no uploaded APK yet; ask the user to upload an APK in the web UI"}
        source = next((r for r in runs if r.status != "failed"), runs[0])
    requested = args.get("profiles")
    if requested:
        profiles = [p for p in requested if p in _PROFILE_IDS]
        if not profiles:
            return {"error": f"no valid profile ids; valid: {_PROFILE_IDS}"}
    else:
        supported = [p.id for p in PROFILES if p.fidelity != "unsupported"]
        profiles = [p for p in supported if p not in source.profile_ids]
        if not profiles:
            profiles = list(source.profile_ids)  # everything already ran: repeat them with a longer journey
    try:
        steps = int(args.get("journey_steps") or DEEP_JOURNEY_STEPS)
    except (TypeError, ValueError):
        steps = DEEP_JOURNEY_STEPS
    steps = max(1, min(steps, MAX_JOURNEY_STEPS))
    run = await service.rerun(source.id, profiles, steps)
    return {
        "run_id": run.id,
        "status": run.status,
        "source_run_id": source.id,
        "profiles": profiles,
        "journey_steps": steps,
        "note": "started in the background; check get_run_status or get_report later",
    }


async def _get_finding_evidence(service: RunService, args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    finding = await _find_finding(service, str(args["finding_id"]), ctx)
    if finding is None:
        return {"error": f"finding {args['finding_id']} not found"}
    base = _api_base()
    evidence = []
    for e in finding.evidence:
        item: dict[str, Any] = {"kind": e.kind, "excerpt": (e.excerpt or "")[:400] or None}
        if e.ref:
            item["ref"] = e.ref
            item["url"] = f"{base}/api/runs/{finding.run_id}/artifacts/{e.ref}"
        evidence.append(item)
    return {
        "finding_id": finding.id,
        "run_id": finding.run_id,
        "title": finding.title,
        "severity": finding.severity,
        "profile": finding.profile_id,
        "journey_step": finding.journey_step,
        "evidence": evidence,
        "note": "only the listed excerpts are known; screenshots and logs can be opened via their urls, "
        "their pixels or full text are not visible to you",
    }


async def _compare_runs(service: RunService, args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    run_a, fa = await _load_run_and_findings(service, args.get("run_a"), ctx)
    run_b, fb = await _load_run_and_findings(service, args.get("run_b"), ctx)
    if run_a is None or run_b is None:
        return _not_found(args.get("run_a") if run_a is None else args.get("run_b"))

    def keyed(fs: list[Finding]) -> dict[tuple[str, str | None], Finding]:
        return {(f.rule_id, f.profile_id): f for f in fs}

    ka, kb = keyed(fa), keyed(fb)

    def brief(f: Finding) -> dict[str, Any]:
        return {"rule_id": f.rule_id, "profile": f.profile_id, "title": _clip(f.title, 80), "severity": f.severity}

    sa = run_a.summary.reliability_score if run_a.summary else None
    sb = run_b.summary.reliability_score if run_b.summary else None
    return {
        "run_a": {"id": run_a.id, "apk": run_a.apk_name, "status": run_a.status, "score": sa},
        "run_b": {"id": run_b.id, "apk": run_b.apk_name, "status": run_b.status, "score": sb},
        "score_delta": round(sb - sa, 1) if sa is not None and sb is not None else None,
        "fixed": [brief(ka[k]) for k in ka if k not in kb][:10],
        "new": [brief(kb[k]) for k in kb if k not in ka][:10],
        "persisting": [brief(kb[k]) for k in kb if k in ka][:10],
        "note": "findings are matched by rule_id plus profile; a profile run in only one run can show as fixed or new",
    }


async def _make_plan(
    service: RunService, args: dict[str, Any], ctx: ToolContext
) -> tuple[Run, TestPlan] | dict[str, Any]:
    ref = args.get("apk_or_run") or args.get("run_id") or ctx.active_run_id
    if ref:
        run = await _resolve_run(service, ref, ctx)
        if run is None:
            return _not_found(ref)
    else:
        runs = await service.list_runs()
        if not runs:
            return {"error": "no uploaded APK yet; ask the user to upload an APK in the web UI"}
        run = next((r for r in runs if r.status != "failed"), runs[0])
    kind = args.get("plan_kind")
    if kind not in (None, "initial", "followup"):
        return {"error": "plan_kind must be 'initial' or 'followup'"}
    findings = await service.list_findings(run.id)
    if kind is None:
        kind = "followup" if run.summary is not None and run.status == "done" else "initial"
    if kind == "initial":
        if run.app is None:
            return {"error": "the app has not been analysed yet, so there is nothing to plan from; try again shortly"}
        return run, plan_initial(run.app, [f for f in findings if f.source == "static"])
    return run, plan_followup(run, findings)


def _plan_dict(plan: TestPlan) -> dict[str, Any]:
    out: dict[str, Any] = {
        "plan_kind": plan.kind,
        "profiles": plan.profiles,
        "journey_steps": plan.journey_steps,
        "reasons": [r.model_dump() for r in plan.reasons],
    }
    if plan.note:
        out["note"] = plan.note
    return out


async def _plan_tests(service: RunService, args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    made = await _make_plan(service, args, ctx)
    if isinstance(made, dict):
        return made
    run, plan = made
    return {"source_run_id": run.id, **_plan_dict(plan), "started": False}


async def _start_planned_test(service: RunService, args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    made = await _make_plan(service, args, ctx)
    if isinstance(made, dict):
        return made
    source, plan = made
    if not plan.profiles:
        return {
            "source_run_id": source.id,
            **_plan_dict(plan),
            "started": False,
            "note": plan.note or "the plan has no tests to run",
        }
    steps = max(1, min(plan.journey_steps, MAX_JOURNEY_STEPS))
    run = await service.rerun(source.id, plan.profiles, steps)
    return {
        "run_id": run.id,
        "status": run.status,
        "source_run_id": source.id,
        **_plan_dict(plan),
        "started": True,
        "note": "started in the background; check get_run_status or get_report later",
    }


_NEW_TOOLS = {
    "plan_tests": _plan_tests,
    "start_planned_test": _start_planned_test,
    "get_report": _get_report,
    "suggest_improvements": _suggest_improvements,
    "run_deeper_tests": _run_deeper_tests,
    "get_finding_evidence": _get_finding_evidence,
    "compare_runs": _compare_runs,
}
