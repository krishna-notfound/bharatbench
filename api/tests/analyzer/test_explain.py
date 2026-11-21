import json

import httpx
import pytest
import respx

from app.analyzer import explain
from app.analyzer.explain import NOTE_PREFIX, explain_findings, parse_output, validate_grounded
from app.models import Evidence, Finding, Impact

URL = "https://api.sarvam.ai/v1/chat/completions"


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    monkeypatch.setattr(explain, "_llm_config", lambda: ("https://api.sarvam.ai/v1", "sarvam-105b", "k", "sarvam"))


def _finding(i: int = 1, score: float = 50.0) -> Finding:
    return Finding(
        id=f"f{i}", run_id="r", source="static", category="security", rule_id="sec.exported_component",
        title="Exported activity without permission: com.example.ShareActivity", severity="medium",
        description="Reachable by any app.",
        evidence=[Evidence(kind="manifest", excerpt='<activity android:name="com.example.ShareActivity">')],
        probable_cause="Exported.", suggested_fix="Set exported=false.",
        impact=Impact(users_exposed=1, severity_weight=0.4, flow_usage=1, score=score),
    )


def _reply(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


GOOD = {
    "probable_cause": "com.example.ShareActivity is exported without a permission.",
    "suggested_fix": "Set android:exported to false.",
    "developer_explanation": "Any app can launch ShareActivity, so other apps could feed it data.",
}


@respx.mock
async def test_valid_json_adds_note_and_updates_text():
    route = respx.post(URL).mock(return_value=_reply(json.dumps(GOOD)))
    out, n = await explain_findings([_finding()])
    assert n == 1 and route.called
    assert route.calls[0].request.headers["api-subscription-key"] == "k"
    f = out[0]
    assert f.evidence[-1].kind == "note" and f.evidence[-1].excerpt.startswith(NOTE_PREFIX)
    assert f.suggested_fix == GOOD["suggested_fix"]
    assert len(f.evidence) == 2


@respx.mock
async def test_fenced_json_with_think_block_parses():
    body = "<think>hmm</think>\n```json\n" + json.dumps(GOOD) + "\n```"
    respx.post(URL).mock(return_value=_reply(body))
    _, n = await explain_findings([_finding()])
    assert n == 1


@respx.mock
async def test_invalid_json_keeps_deterministic_text():
    respx.post(URL).mock(return_value=_reply("sorry, I cannot do that"))
    orig = _finding()
    out, n = await explain_findings([orig])
    assert n == 0 and out[0] == orig


@respx.mock
async def test_hallucinated_identifier_rejected():
    bad = dict(GOOD, developer_explanation="com.evil.Backdoor leaks data to https://evil.example/x.")
    respx.post(URL).mock(return_value=_reply(json.dumps(bad)))
    orig = _finding()
    out, n = await explain_findings([orig])
    assert n == 0 and out[0] == orig


@respx.mock
async def test_http_error_keeps_text():
    respx.post(URL).mock(return_value=httpx.Response(500))
    orig = _finding()
    out, n = await explain_findings([orig])
    assert n == 0 and out == [orig]


@respx.mock
async def test_timeout_keeps_text():
    respx.post(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    orig = _finding()
    out, n = await explain_findings([orig])
    assert n == 0 and out == [orig]


async def test_total_budget_cancels_slow_calls(monkeypatch):
    import asyncio

    async def slow(*a, **k):
        await asyncio.sleep(5)

    monkeypatch.setattr(explain, "_explain_one", slow)
    out, n = await explain_findings([_finding()], budget_s=0.1)
    assert n == 0 and len(out) == 1


async def test_no_key_is_noop(monkeypatch):
    monkeypatch.setattr(explain, "_llm_config", lambda: None)
    orig = _finding()
    out, n = await explain_findings([orig])
    assert n == 0 and out == [orig]


@respx.mock
async def test_only_top_8_called():
    route = respx.post(URL).mock(return_value=_reply(json.dumps(GOOD)))
    findings = [_finding(i, score=float(i)) for i in range(12)]
    out, n = await explain_findings(findings)
    assert n == 8 and route.call_count == 8
    assert all(len(f.evidence) == 2 for f in out[4:])
    assert all(len(f.evidence) == 1 for f in out[:4])


def test_parse_and_validate_helpers():
    assert parse_output("{}") is None
    assert parse_output(json.dumps(GOOD)) == GOOD
    assert validate_grounded(GOOD, json.dumps(_finding().model_dump(mode="json")))
    assert not validate_grounded({"a": "see https://x.io/p"}, "nothing here")
