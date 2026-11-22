"""Tool dispatch against a fake RunService."""

from __future__ import annotations

from voice_fakes import FakeRunService, make_run

from app.voice.tools import TOOL_SCHEMAS, ToolContext, dispatch


async def test_start_test_reruns_most_recent_run_with_profiles(service: FakeRunService) -> None:
    result = await dispatch(
        service, "start_test", {"profiles": ["flaky_network", "budget_2gb", "bogus"]}, ToolContext()
    )
    assert service.rerun_calls == [("run1", ["flaky_network", "budget_2gb"])]
    assert result == {"run_id": "run2", "status": "queued", "profiles": ["flaky_network", "budget_2gb"]}


async def test_start_test_prefers_active_run_and_explicit_id(service: FakeRunService) -> None:
    service.runs += [make_run("active9"), make_run("x9")]
    await dispatch(service, "start_test", {"profiles": ["baseline"]}, ToolContext("active9"))
    await dispatch(
        service, "start_test", {"profiles": ["baseline"], "apk_run_id": "x9"}, ToolContext("active9")
    )
    assert [c[0] for c in service.rerun_calls] == ["active9", "x9"]


async def test_run_refs_resolve_by_apk_name_and_unknown_run_errors(service: FakeRunService) -> None:
    status = await dispatch(service, "get_run_status", {"run_id": "demo.apk"}, ToolContext())
    assert status["id"] == "run1"
    await dispatch(service, "start_test", {"profiles": ["baseline"], "apk_name": "demo"}, ToolContext())
    assert service.rerun_calls == [("run1", ["baseline"])]
    assert "error" in await dispatch(service, "list_findings", {"run_id": "ghost.apk"}, ToolContext())
    assert "error" in await dispatch(service, "start_test", {"profiles": ["baseline"], "apk_name": "ghost"}, ToolContext())


async def test_start_test_without_any_run_returns_error(service: FakeRunService) -> None:
    service.runs.clear()
    result = await dispatch(service, "start_test", {"profiles": ["baseline"]}, ToolContext())
    assert "upload" in result["error"]
    assert service.rerun_calls == []


async def test_start_test_rejects_all_invalid_profiles(service: FakeRunService) -> None:
    assert "error" in await dispatch(service, "start_test", {"profiles": ["nope"]}, ToolContext())


async def test_list_runs_and_profiles(service: FakeRunService) -> None:
    runs = await dispatch(service, "list_runs", {}, ToolContext())
    assert runs["runs"][0] == {"id": "run1", "apk": "demo.apk", "status": "done", "score": 61.0}
    profiles = await dispatch(service, "list_profiles", {}, ToolContext())
    assert {"baseline", "flaky_network"} <= {p["id"] for p in profiles["profiles"]}


async def test_list_findings_sorted_by_score_and_filtered(service: FakeRunService) -> None:
    result = await dispatch(service, "list_findings", {"run_id": "run1"}, ToolContext())
    assert [f["id"] for f in result["findings"]] == ["f2", "f1"]
    crit = await dispatch(
        service, "list_findings", {"run_id": "run1", "severity": "critical", "limit": 1}, ToolContext()
    )
    assert [f["id"] for f in crit["findings"]] == ["f2"]


async def test_explain_finding_truncates_evidence_and_unknown_is_error(service: FakeRunService) -> None:
    result = await dispatch(service, "explain_finding", {"finding_id": "f1"}, ToolContext())
    assert result["id"] == "f1" and len(result["evidence"][0]["excerpt"]) == 300
    assert "error" in await dispatch(service, "explain_finding", {"finding_id": "zzz"}, ToolContext())


async def test_get_status_and_missing(service: FakeRunService) -> None:
    status = await dispatch(service, "get_run_status", {"run_id": "run1"}, ToolContext())
    assert status["status"] == "done" and status["summary"]["total_findings"] == 2
    assert "error" in await dispatch(service, "get_run_status", {"run_id": "nope"}, ToolContext())


async def test_missing_required_arg_and_unknown_tool_return_errors(service: FakeRunService) -> None:
    assert "error" in await dispatch(service, "get_run_status", {}, ToolContext())
    assert "error" in await dispatch(service, "rm_rf", {}, ToolContext())


async def test_cancel_run_tool_is_removed(service: FakeRunService) -> None:
    assert "cancel_run" not in {t["function"]["name"] for t in TOOL_SCHEMAS}
    assert "error" in await dispatch(service, "cancel_run", {"run_id": "run1"}, ToolContext())
