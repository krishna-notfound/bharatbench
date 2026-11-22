from __future__ import annotations

from voice_fakes import NOW, FakeRunService, make_finding

from app.models import AppInfo, Run, RunSummary
from app.realtime.registry import LABELS
from app.voice.tools import TOOL_SCHEMAS, ToolContext, dispatch


def _run(app: AppInfo | None, status: str = "done", profiles=("baseline",)) -> Run:
    return Run(
        id="run1", apk_name="demo.apk", status=status, profile_ids=list(profiles),  # type: ignore[arg-type]
        created_at=NOW, updated_at=NOW, app=app, summary=RunSummary(runtime_executed=True),
    )


def _app() -> AppInfo:
    return AppInfo(package_name="p", size_bytes=1000, permissions=["android.permission.INTERNET"])


def test_schemas_and_labels() -> None:
    names = {t["function"]["name"] for t in TOOL_SCHEMAS}
    assert {"plan_tests", "start_planned_test"} <= names <= set(LABELS) | names
    assert "plan_tests" in LABELS and "start_planned_test" in LABELS


async def test_plan_tests_does_not_start(service: FakeRunService) -> None:
    service.runs = [_run(_app())]
    service.findings = []
    r = await dispatch(service, "plan_tests", {"apk_or_run": "demo", "plan_kind": "initial"}, ToolContext())
    assert r["started"] is False and service.rerun_calls == []
    assert r["profiles"] == ["baseline", "flaky_network", "budget_2gb"]
    assert r["reasons"][1]["why"]


async def test_start_planned_initial(service: FakeRunService) -> None:
    service.runs = [_run(_app())]
    service.findings = []
    r = await dispatch(service, "start_planned_test", {"apk_or_run": "run1", "plan_kind": "initial"}, ToolContext())
    assert service.rerun_calls == [("run1", ["baseline", "flaky_network", "budget_2gb"])]
    assert service.rerun_steps == [8]
    assert r["run_id"] == "run2" and r["started"] is True and r["reasons"]


async def test_start_planned_followup_defaults_and_uses_findings(service: FakeRunService) -> None:
    service.runs = [_run(_app())]
    f = make_finding("f1", 5.0).model_copy(update={"rule_id": "rt.crash", "source": "runtime", "profile_id": "flaky_network"})
    service.findings = [f]
    r = await dispatch(service, "start_planned_test", {}, ToolContext("run1"))
    assert service.rerun_calls == [("run1", ["flaky_network", "baseline"])]
    assert service.rerun_steps == [16] and "f1" in r["reasons"][0]["why"]


async def test_followup_with_nothing_to_do_does_not_start(service: FakeRunService) -> None:
    every = ["baseline", "budget_2gb", "flaky_network", "low_storage", "battery_saver", "process_death"]
    service.runs = [_run(_app(), profiles=every)]
    service.findings = []
    r = await dispatch(service, "start_planned_test", {"apk_or_run": "run1"}, ToolContext())
    assert r["started"] is False and service.rerun_calls == [] and r["note"]


async def test_errors(service: FakeRunService) -> None:
    service.runs = [_run(None, status="analyzing")]
    assert "error" in await dispatch(service, "plan_tests", {"apk_or_run": "ghost"}, ToolContext())
    assert "error" in await dispatch(service, "plan_tests", {"apk_or_run": "run1"}, ToolContext())  # no app info
    assert "error" in await dispatch(service, "plan_tests", {"apk_or_run": "run1", "plan_kind": "x"}, ToolContext())
    service.runs = []
    assert "error" in await dispatch(service, "start_planned_test", {}, ToolContext())
