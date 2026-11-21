"""f16 tools: get_report, suggest_improvements, run_deeper_tests, get_finding_evidence, compare_runs."""

from __future__ import annotations

import json

from voice_fakes import NOW, FakeRunService, make_finding

from app.models import Evidence, Finding, Impact, Run, RunSummary
from app.voice.tools import TOOL_SCHEMAS, ToolContext, dispatch


def _finding(fid: str, rule: str, score: float, run_id: str = "run1", **kw) -> Finding:
    base = make_finding(fid, score, run_id=run_id)
    return base.model_copy(
        update={
            "rule_id": rule,
            "title": kw.pop("title", f"{rule} title"),
            "probable_cause": kw.pop("cause", "because"),
            "suggested_fix": kw.pop("fix", f"fix {rule}"),
            "impact": Impact(users_exposed=0.5, severity_weight=0.5, flow_usage=0.5, score=score),
            **kw,
        }
    )


def _done_run(run_id: str, profiles: list[str], score: float = 60.0, executed: bool = True) -> Run:
    return Run(
        id=run_id,
        apk_name="demo.apk",
        status="done",
        profile_ids=profiles,  # type: ignore[arg-type]
        created_at=NOW,
        updated_at=NOW,
        summary=RunSummary(reliability_score=score, runtime_executed=executed, total_findings=0),
    )


def test_schemas_registered() -> None:
    names = {t["function"]["name"] for t in TOOL_SCHEMAS}
    assert {"get_report", "suggest_improvements", "run_deeper_tests", "get_finding_evidence", "compare_runs"} <= names


async def test_get_report_compact_and_honest(service: FakeRunService) -> None:
    service.runs = [_done_run("run1", ["baseline", "flaky_network"])]
    service.findings = [
        _finding(f"f{i}", f"rule{i}", float(i), cause="c" * 400, fix="f" * 400) for i in range(1, 12)
    ] + [
        _finding(
            "np", "rt.profile_not_applied", 0.5, profile_id="flaky_network", description="tc not available"
        )
    ]
    result = await dispatch(service, "get_report", {"run_id": "demo.apk"}, ToolContext())
    assert result["run_id"] == "run1" and result["score"] == 60.0
    assert len(result["top_findings"]) == 8
    assert result["top_findings"][0]["id"] == "f11"
    assert result["total_findings"] == 12
    assert result["profiles"] == [
        {"id": "baseline", "applied": True},
        {"id": "flaky_network", "applied": False, "why": "tc not available"},
    ]
    assert "thermal" in result["unsupported_conditions"]
    assert len(json.dumps(result)) < 4000


async def test_get_report_runtime_skipped_marks_profiles_not_applied(service: FakeRunService) -> None:
    run = _done_run("run1", ["baseline"], executed=False)
    run.summary.runtime_skipped_reason = "Harness not configured"  # type: ignore[union-attr]
    service.runs = [run]
    result = await dispatch(service, "get_report", {"run_id": "run1"}, ToolContext())
    assert result["runtime_executed"] is False
    assert result["runtime_skipped_reason"] == "Harness not configured"
    assert result["profiles"][0]["applied"] is False


async def test_get_report_uses_active_run_and_unknown_errors(service: FakeRunService) -> None:
    assert (await dispatch(service, "get_report", {}, ToolContext("run1")))["run_id"] == "run1"
    assert "error" in await dispatch(service, "get_report", {"run_id": "ghost"}, ToolContext())


async def test_suggest_improvements_groups_orders_and_filters(service: FakeRunService) -> None:
    service.runs = [_done_run("run1", ["baseline"])]
    service.findings = [
        _finding("a", "sec.debuggable", 10.0, fix="Disable debuggable."),
        _finding("b", "rt.anr", 50.0, category="reliability", fix="Move work off main thread."),
        _finding("c", "rt.anr", 20.0, category="reliability", fix="Move work off main thread."),
        _finding("d", "rt.profile_not_applied", 99.0, category="network"),
    ]
    result = await dispatch(service, "suggest_improvements", {"run_id": "run1"}, ToolContext())
    actions = result["actions"]
    assert [a["rule_id"] for a in actions] == ["rt.anr", "sec.debuggable"]
    assert actions[0]["evidence_finding_ids"] == ["b", "c"] and actions[0]["total_impact"] == 70.0
    assert actions[0]["fix"] == "Move work off main thread." and actions[0]["priority"] == 1
    sec = await dispatch(service, "suggest_improvements", {"run_id": "run1", "focus": "security"}, ToolContext())
    assert [a["rule_id"] for a in sec["actions"]] == ["sec.debuggable"]
    net = await dispatch(service, "suggest_improvements", {"run_id": "run1", "focus": "network"}, ToolContext())
    assert net["actions"] == [] and "note" in net
    assert "error" in await dispatch(
        service, "suggest_improvements", {"run_id": "run1", "focus": "bogus"}, ToolContext()
    )


async def test_run_deeper_tests_defaults_to_unrun_profiles_and_16_steps(service: FakeRunService) -> None:
    service.runs = [_done_run("run1", ["baseline", "budget_2gb"])]
    result = await dispatch(service, "run_deeper_tests", {"run_id": "run1"}, ToolContext())
    called_profiles = service.rerun_calls[0][1]
    assert service.rerun_calls[0][0] == "run1"
    assert "baseline" not in called_profiles and "budget_2gb" not in called_profiles
    assert {"flaky_network", "process_death"} <= set(called_profiles)
    assert service.rerun_steps == [16]
    assert result["run_id"] == "run2" and result["journey_steps"] == 16


async def test_run_deeper_tests_explicit_profiles_clamps_steps_and_uses_active(service: FakeRunService) -> None:
    result = await dispatch(
        service,
        "run_deeper_tests",
        {"profiles": ["baseline", "nope"], "journey_steps": 99},
        ToolContext("run1"),
    )
    assert service.rerun_calls == [("run1", ["baseline"])]
    assert service.rerun_steps == [20] and result["profiles"] == ["baseline"]
    assert "error" in await dispatch(service, "run_deeper_tests", {"profiles": ["nope"]}, ToolContext())
    assert "error" in await dispatch(service, "run_deeper_tests", {"run_id": "ghost"}, ToolContext())


async def test_run_deeper_tests_all_profiles_already_run_repeats_them(service: FakeRunService) -> None:
    every = ["baseline", "budget_2gb", "flaky_network", "low_storage", "battery_saver", "process_death"]
    service.runs = [_done_run("run1", every)]
    await dispatch(service, "run_deeper_tests", {"run_id": "run1"}, ToolContext())
    assert service.rerun_calls[0][1] == every


async def test_get_finding_evidence_builds_artifact_urls(service: FakeRunService, monkeypatch) -> None:
    monkeypatch.setenv("API_BASE", "https://api.example.com/")
    service.findings = [
        _finding(
            "f9",
            "rt.anr",
            30.0,
            evidence=[
                Evidence(kind="screenshot", ref="baseline/s1.png"),
                Evidence(kind="logcat", ref="baseline/logcat.txt", excerpt="ANR in com.x"),
            ],
        )
    ]
    result = await dispatch(service, "get_finding_evidence", {"finding_id": "f9"}, ToolContext())
    ev = result["evidence"]
    assert ev[0]["url"] == "https://api.example.com/api/runs/run1/artifacts/baseline/s1.png"
    assert ev[1]["excerpt"] == "ANR in com.x" and ev[1]["kind"] == "logcat"
    assert "error" in await dispatch(service, "get_finding_evidence", {"finding_id": "zz"}, ToolContext())


async def test_compare_runs_delta_fixed_new_persisting(service: FakeRunService) -> None:
    service.runs = [_done_run("runB", ["baseline"], 80.0), _done_run("runA", ["baseline"], 60.0)]
    service.findings = [
        _finding("a1", "sec.debuggable", 10.0, run_id="runA", profile_id=None),
        _finding("a2", "rt.anr", 30.0, run_id="runA", profile_id="baseline"),
        _finding("b1", "rt.anr", 25.0, run_id="runB", profile_id="baseline"),
        _finding("b2", "rt.crash", 15.0, run_id="runB", profile_id="baseline"),
    ]
    result = await dispatch(service, "compare_runs", {"run_a": "runA", "run_b": "runB"}, ToolContext())
    assert result["score_delta"] == 20.0
    assert [f["rule_id"] for f in result["fixed"]] == ["sec.debuggable"]
    assert [f["rule_id"] for f in result["new"]] == ["rt.crash"]
    assert [f["rule_id"] for f in result["persisting"]] == ["rt.anr"]
    assert "error" in await dispatch(service, "compare_runs", {"run_a": "runA", "run_b": "ghost"}, ToolContext())
