from __future__ import annotations

import json

import httpx
import respx
from voice_fakes import NOW, FakeRunService

from app import agent_tests
from app.agent_tests import SUPPORTED, validate
from app.models import AppInfo, Run, RunSummary
from app.realtime.registry import LABELS, label_for
from app.voice.tools import TOOL_SCHEMAS, ToolContext, dispatch

BASE = "https://llm.test/v1"


def _run() -> Run:
    return Run(
        id="run1", apk_name="shop.apk", status="done", profile_ids=["baseline"],  # type: ignore[list-item]
        created_at=NOW, updated_at=NOW, summary=RunSummary(runtime_executed=True),
        app=AppInfo(package_name="com.shop", app_name="Shop", size_bytes=1000, activities=["com.shop.Signup"]),
    )


def _reply(tests: object) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"tests": tests})}}]})


def _t(i: str, cond: str = "baseline") -> dict:
    return {"id": i, "title": f"Test {i}", "goal": "do it", "condition": cond, "success_check": "see it"}


def test_validate_excludes_low_storage_and_caps() -> None:
    assert "low_storage" not in SUPPORTED
    got = validate({"tests": [_t("a", "low_storage"), _t("b", "nope"), *[_t(f"c{i}") for i in range(8)]]})
    assert len(got) == 5 and all(t.condition in SUPPORTED for t in got)


def test_schema_and_label() -> None:
    assert "write_custom_tests" in {t["function"]["name"] for t in TOOL_SCHEMAS}
    assert label_for("write_custom_tests") == "Writing your tests" == LABELS["write_custom_tests"]


@respx.mock
async def test_write_custom_tests_starts_run(service: FakeRunService, monkeypatch) -> None:
    monkeypatch.setattr(agent_tests, "_llm_config", lambda: (BASE, "m", "k", "bearer"))
    route = respx.post(f"{BASE}/chat/completions").mock(
        return_value=_reply([_t("bad_email"), _t("hindi_search", "flaky_network")])
    )
    service.runs = [_run()]
    r = await dispatch(service, "write_custom_tests", {"request": "signup with a wrong email, search in Hindi"}, ToolContext("run1"))
    assert [t["title"] for t in r["tests"]] == ["Test bad_email", "Test hindi_search"]
    assert r["run_id"] == "run2"
    assert service.rerun_calls == [("run1", ["baseline", "flaky_network"])]
    assert [t.id for t in service.rerun_tests[0]] == ["bad_email", "hindi_search"]
    sent = json.loads(route.calls[0].request.content)["messages"][1]["content"]
    assert "wrong email" in sent and "com.shop" in sent


@respx.mock
async def test_write_custom_tests_errors_are_honest(service: FakeRunService, monkeypatch) -> None:
    service.runs = [_run()]
    monkeypatch.setattr(agent_tests, "_llm_config", lambda: None)
    r = await dispatch(service, "write_custom_tests", {"request": "x"}, ToolContext("run1"))
    assert "error" in r and service.rerun_calls == []
    monkeypatch.setattr(agent_tests, "_llm_config", lambda: (BASE, "m", "k", "bearer"))
    respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(200, json={"choices": [{"message": {"content": "no json"}}]}))
    r = await dispatch(service, "write_custom_tests", {"request": "x"}, ToolContext("run1"))
    assert "usable tests" in r["error"] and service.rerun_calls == []
    r = await dispatch(service, "write_custom_tests", {"request": "x", "apk_or_run": "zzz"}, ToolContext())
    assert "error" in r
