import json

import httpx
import pytest

from app.agent_tests import fallback_tests, generate_agent_tests, validate
from app.analyzer.rules_agent import agent_test_findings
from app.models import AppInfo, HarnessAgentTestResult, HarnessJobRequest, HarnessResult, HarnessStep

APP = AppInfo(package_name="com.x", size_bytes=1000, permissions=["android.permission.INTERNET"])


def good(**kw):
    return {"id": "bad_email", "title": "Bad email", "goal": "g", "condition": "baseline", "success_check": "s", **kw}


def test_validate_drops_unsupported_and_dupes():
    out = validate(
        {
            "tests": [
                good(),
                good(),
                good(id="a", condition="low_storage"),
                good(id="b", condition="nope"),
                {"title": "x"},
                good(id="c", condition="flaky_network"),
            ]
        }
    )
    assert [t.id for t in out] == ["bad_email", "c"]


def test_fallback_uses_planner_and_is_valid():
    ids = [t.id for t in fallback_tests(APP, [])]
    assert "first_screen_flow" in ids and "network_drop_retry" in ids


@pytest.fixture
def key(monkeypatch):
    from app import settings

    monkeypatch.setenv("LLM_API_KEY", "k")
    settings.get_settings.cache_clear()
    yield
    settings.get_settings.cache_clear()


def client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_llm_tests_used(key):
    body = json.dumps({"tests": [good(), good(id="two", condition="flaky_network")]})
    async with client(lambda r: httpx.Response(200, json={"choices": [{"message": {"content": body}}]})) as c:
        tests, src = await generate_agent_tests(APP, [], client=c)
    assert src == "llm" and len(tests) == 2


async def test_llm_failure_falls_back(key):
    async with client(lambda r: httpx.Response(500)) as c:
        tests, src = await generate_agent_tests(APP, [], client=c)
    assert src == "fallback" and tests


async def test_llm_garbage_falls_back(key):
    async with client(lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "no json"}}]})) as c:
        _, src = await generate_agent_tests(APP, [], client=c)
    assert src == "fallback"


def test_contract_round_trip_and_default():
    req = HarnessJobRequest(run_id="r", package_name="p", profiles=["baseline"])
    assert req.agent_tests == []
    t = validate({"tests": [good()]})
    again = HarnessJobRequest.model_validate_json(
        HarnessJobRequest(run_id="r", package_name="p", profiles=["baseline"], agent_tests=t).model_dump_json()
    )
    assert again.agent_tests[0].id == "bad_email"
    res = HarnessResult.model_validate({"job_id": "j", "device": "d", "profiles": []})
    assert res.agent_tests == []


def test_failed_test_becomes_finding_passed_does_not():
    step = HarnessStep(index=1, action="tap", target="Sign up", ok=True, note="open")
    r = HarnessResult(
        job_id="j",
        device="d",
        profiles=[],
        agent_tests=[
            HarnessAgentTestResult(id="a", title="A", passed=False, reason="no error shown", steps=[step]),
            HarnessAgentTestResult(id="b", title="B", passed=True, reason="ok"),
            HarnessAgentTestResult(id="c", title="C", passed=None, reason="skipped"),
        ],
    )
    f = agent_test_findings("run12345", r)
    assert len(f) == 1 and f[0].title == "Agent test failed: A" and f[0].category == "reliability"
    assert f[0].source == "runtime" and any("no error shown" in (e.excerpt or "") for e in f[0].evidence)
