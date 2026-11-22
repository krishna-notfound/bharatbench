import base64
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import insights
from app.models import AppInfo, Evidence, Finding, Run, RunSummary
from app.routes import insights as routes
from app.settings import get_settings

T0 = datetime(2026, 11, 20, tzinfo=UTC)
WAV_B64 = base64.b64encode(b"RIFFfakewav").decode()


def mk_run(rid: str, *, hours: int = 0, status: str = "done", executed: bool = True, score: float = 80.0,
           pkg: str | None = "com.x") -> Run:
    return Run(
        id=rid, apk_name="x.apk", status=status, profile_ids=["baseline"],  # type: ignore[arg-type]
        created_at=T0 + timedelta(hours=hours), updated_at=T0,
        app=AppInfo(package_name=pkg, app_name="X", size_bytes=1_048_576) if pkg else None,
        summary=RunSummary(reliability_score=score, runtime_executed=executed, total_findings=0),
    )


def mk_finding(fid: str, rule: str, run_id: str, profile: str | None = "baseline", title: str | None = None) -> Finding:
    return Finding(
        id=fid, run_id=run_id, source="runtime", category="reliability", rule_id=rule,
        title=title or f"{rule} title", severity="high", description="d",
        evidence=[Evidence(kind="note", excerpt="x")], profile_id=profile,  # type: ignore[arg-type]
    )


class FakeService:
    def __init__(self, runs: list[Run], findings: dict[str, list[Finding]]) -> None:
        self.runs, self.findings = runs, findings

    async def get_run(self, run_id: str) -> Run | None:
        return next((r for r in self.runs if r.id == run_id), None)

    async def list_runs(self) -> list[Run]:
        return sorted(self.runs, key=lambda r: r.created_at, reverse=True)

    async def list_findings(self, run_id: str) -> list[Finding]:
        return self.findings.get(run_id, [])


def make_client(monkeypatch: pytest.MonkeyPatch, runs: list[Run], findings: dict[str, list[Finding]]) -> TestClient:
    monkeypatch.setattr(routes, "get_run_service", lambda: FakeService(runs, findings))
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_play_network(monkeypatch):
    async def unknown(_pkg):
        return None

    monkeypatch.setattr(insights, "play_listing", unknown)


# ---- play risk
def risk(monkeypatch, run, findings, on_play=None):
    async def fake_listing(_pkg):
        return on_play

    monkeypatch.setattr(insights, "play_listing", fake_listing)
    c = make_client(monkeypatch, [run], {run.id: findings})
    r = c.get(f"/api/runs/{run.id}/play-risk")
    assert r.status_code == 200
    return r.json()


def test_risk_high_crash_any_profile(monkeypatch):
    body = risk(monkeypatch, mk_run("a"), [mk_finding("f1", "rt.crash", "a", "flaky_network")])
    assert body["level"] == "high"
    assert "for budget phones" not in body["headline"]
    assert body["reasons"][0]["finding_id"] == "f1"
    assert body["thresholds"] == {"crash_rate_pct": 1.09, "anr_rate_pct": 0.47}
    assert "cannot measure" in body["headline"]


def test_risk_high_budget_only(monkeypatch):
    body = risk(monkeypatch, mk_run("a"), [mk_finding("f1", "rt.anr", "a", "budget_2gb")])
    assert body["level"] == "high" and "budget phones" in body["headline"]


def test_risk_medium_network(monkeypatch):
    body = risk(monkeypatch, mk_run("a"), [mk_finding("f1", "rt.stuck_loading", "a")])
    assert body["level"] == "medium" and body["reasons"]


def test_risk_unknown_when_no_runtime(monkeypatch):
    body = risk(monkeypatch, mk_run("a", executed=False), [mk_finding("f1", "rt.crash", "a")])
    assert body["level"] == "unknown" and "not tested on a device" in body["headline"].lower()


def test_risk_low(monkeypatch):
    body = risk(monkeypatch, mk_run("a"), [])
    assert body["level"] == "low" and body["reasons"] == []


def test_risk_unknown_run_404(monkeypatch):
    c = make_client(monkeypatch, [], {})
    assert c.get("/api/runs/nope/play-risk").status_code == 404


# ---- compare
def test_compare_with_previous(monkeypatch):
    old, mid, new = mk_run("old", hours=0, score=42), mk_run("other", hours=1, pkg="com.other"), mk_run("new", hours=2, score=78)
    findings = {
        "old": [mk_finding("o1", "rt.crash", "old"), mk_finding("o2", "rt.slow_launch", "old")],
        "new": [mk_finding("n1", "rt.slow_launch", "new"), mk_finding("n2", "rt.network_errors", "new")],
    }
    c = make_client(monkeypatch, [old, mid, new], findings)
    body = c.get("/api/runs/new/compare").json()
    assert body["previous_run_id"] == "old"
    assert (body["score_before"], body["score_after"]) == (42, 78)
    assert [f["rule_id"] for f in body["fixed"]] == ["rt.crash"]
    assert [f["rule_id"] for f in body["new"]] == ["rt.network_errors"]
    assert [f["rule_id"] for f in body["persisting"]] == ["rt.slow_launch"]


def test_compare_404_when_no_earlier_run(monkeypatch):
    first = mk_run("a", hours=0)
    later_other_pkg = mk_run("b", hours=1, pkg="com.other")
    c = make_client(monkeypatch, [first, later_other_pkg], {})
    assert c.get("/api/runs/a/compare").status_code == 404
    assert c.get("/api/runs/b/compare").status_code == 404


# ---- brief
CHAT = "https://api.sarvam.ai/v1/chat/completions"
TTS = "https://api.sarvam.ai/text-to-speech"


@pytest.fixture
def sarvam_key(monkeypatch):
    monkeypatch.setenv("SARVAM_API_KEY", "test-key")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def brief_client(monkeypatch):
    run = mk_run("a", score=61)
    return make_client(monkeypatch, [run], {"a": [mk_finding("f1", "rt.crash", "a", title="App crash on Budget")]})


@respx.mock
def test_brief_text_and_audio(monkeypatch, sarvam_key):
    chat = respx.post(CHAT).mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "<think>x</think>**Score 61.** Fix the crash."}}]})
    )
    respx.post(TTS).mock(return_value=httpx.Response(200, json={"audios": [WAV_B64]}))
    r = brief_client(monkeypatch).post("/api/runs/a/brief", json={"language": "hi-IN"})
    assert r.status_code == 200
    body = r.json()
    assert body == {"text": "Score 61. Fix the crash.", "audio_b64": WAV_B64, "language": "hi-IN"}
    sent = chat.calls.last.request.content.decode()
    assert "Hindi" in sent and "App crash on Budget" in sent


@respx.mock
def test_brief_tts_failure_returns_text(monkeypatch, sarvam_key):
    respx.post(CHAT).mock(return_value=httpx.Response(200, json={"choices": [{"message": {"content": "Plain summary."}}]}))
    respx.post(TTS).mock(return_value=httpx.Response(500))
    body = brief_client(monkeypatch).post("/api/runs/a/brief", json={"language": "auto"}).json()
    assert body["text"] == "Plain summary." and body["audio_b64"] is None and body["language"] == "en-IN"


@respx.mock
def test_brief_llm_failure_is_502(monkeypatch, sarvam_key):
    respx.post(CHAT).mock(return_value=httpx.Response(500))
    assert brief_client(monkeypatch).post("/api/runs/a/brief", json={"language": "en-IN"}).status_code == 502


def test_brief_rejects_bad_language_and_unfinished(monkeypatch, sarvam_key):
    c = brief_client(monkeypatch)
    assert c.post("/api/runs/a/brief", json={"language": "xx-YY"}).status_code == 422
    c2 = make_client(monkeypatch, [mk_run("a", status="running")], {})
    assert c2.post("/api/runs/a/brief", json={"language": "auto"}).status_code == 409


def test_not_on_play_store_never_claims_play_limits_apply(monkeypatch):
    body = risk(monkeypatch, mk_run("a"), [], on_play=False)
    assert body["on_play_store"] is False
    assert "not on Google Play" in body["headline"] and "only apply once you publish" in body["headline"]
    assert "Low risk" not in body["headline"]


def test_on_play_store_mentions_play_limits(monkeypatch):
    body = risk(monkeypatch, mk_run("a"), [mk_finding("f1", "rt.anr", "a", "budget_2gb")], on_play=True)
    assert body["on_play_store"] is True and "is on Google Play" in body["headline"]


def test_low_names_the_conditions_actually_tested(monkeypatch):
    body = risk(monkeypatch, mk_run("a"), [], on_play=None)
    assert body["tested_conditions"] and "No crashes or freezes seen" in body["headline"]
