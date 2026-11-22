from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fix_prompt import FULL_LIMIT, finding_prompt, report_prompt
from app.models import AppInfo, Evidence, Finding, Impact, Run, RunSummary
from app.report import render_markdown
from app.routes import fix_prompts as routes

T0 = datetime(2026, 11, 20, tzinfo=UTC)
LOG = "\n".join(
    ["E/AndroidRuntime: FATAL EXCEPTION: main"]
    + ["ANR in com.acme.shop (com.acme.shop/.ui.HomeActivity)"]
    + [f"  at com.acme.shop.data.Repo.load(Repo.kt:{i})" for i in range(80)]
)


def mk_run(status: str = "done") -> Run:
    return Run(
        id="r1", apk_name="shop.apk", status=status, profile_ids=["budget_2gb"],  # type: ignore[arg-type]
        created_at=T0, updated_at=T0,
        app=AppInfo(
            package_name="com.acme.shop", app_name="Acme Shop", version_name="2.3.1", version_code="231",
            min_sdk=23, target_sdk=33, size_bytes=48_000_000, native_abis=["arm64-v8a"], dex_count=3,
            main_activity="com.acme.shop.ui.HomeActivity", permissions=["android.permission.CAMERA"],
        ),
        summary=RunSummary(reliability_score=60, runtime_executed=True, total_findings=3),
    )


def mk(fid: str, rule: str, *, sev: str = "high", score: float = 10, ev: list[Evidence] | None = None,
       profile: str | None = "budget_2gb", title: str | None = None, cat: str = "reliability") -> Finding:
    return Finding(
        id=fid, run_id="r1", source="runtime" if rule.startswith("rt.") else "static", category=cat,  # type: ignore[arg-type]
        rule_id=rule, title=title or f"Title {rule}", severity=sev, description=f"Desc {rule}",  # type: ignore[arg-type]
        evidence=ev or [], profile_id=profile,  # type: ignore[arg-type]
        probable_cause="Cause X", suggested_fix="Fix Y", repro_steps=["Open app", "Tap Home"],
        repro_flow="appId: com.acme.shop\n---\n- launchApp",
        impact=Impact(users_exposed=0.5, severity_weight=0.5, flow_usage=0.5, score=score),
    )


def test_anr_prompt_has_evidence_criteria_verify():
    f = mk("f1", "rt.anr", ev=[Evidence(kind="logcat", excerpt=LOG)])
    p = finding_prompt(mk_run(), f)
    assert "com.acme.shop" in p and "2.3.1" in p and "targetSdk 33" in p
    assert "Container memory capped at 2 GB" in p  # real profile `how`
    assert "ANR in com.acme.shop" in p
    assert "more lines omitted" in p  # logcat trimmed to ~40 lines
    assert p.count("Repo.kt:") <= 40
    assert "No blocking I/O or network on the main thread" in p
    assert "verify in the code" in p and "Cause X" in p and "Fix Y" in p
    assert "```yaml" in p and "1. Open app" in p
    assert "Before/after card" in p and "bharatbench-orpin.vercel.app" in p
    assert "`com.acme.shop.data.Repo`" in p  # search term from evidence
    assert "cheap" not in p.lower()


@pytest.mark.parametrize(
    ("rule", "needle"),
    [
        ("rt.network_errors", "timeout"),
        ("sec.cleartext", "networkSecurityConfig"),
        ("perf.no_shrinking", "minifyEnabled"),
        ("sec.exported_component", "exported"),
        ("rt.crash", "FATAL EXCEPTION"),
    ],
)
def test_rule_specific_acceptance(rule, needle):
    p = finding_prompt(mk_run(), mk("f", rule, ev=[Evidence(kind="note", excerpt="http://api.acme.in/v1")]))
    assert needle in p and "## Acceptance criteria" in p and "## How to verify" in p


def test_hardcoded_secret_stays_masked():
    f = mk("f", "sec.hardcoded_secret", profile=None, cat="security",
           ev=[Evidence(kind="code", excerpt="api_key = AIza****wXyZ")])
    p = finding_prompt(mk_run(), f)
    assert "AIza****wXyZ" in p
    assert "rotated or revoked" in p
    assert "static analysis" in p


def test_unknown_rule_falls_back():
    p = finding_prompt(mk_run(), mk("f", "zz.new_rule"))
    assert "## Acceptance criteria" in p and "smallest safe fix" in p and "re-run" in p


def test_report_prompt_orders_by_impact():
    fs = [mk("a", "rt.anr", score=5, title="Low one"), mk("b", "sec.cleartext", score=40, title="Top one"),
          mk("c", "perf.no_shrinking", score=20, title="Mid one")]
    p = report_prompt(mk_run(), fs)
    assert p.index("Top one") < p.index("Mid one") < p.index("Low one")
    assert "## Verification checklist" in p and "one commit per issue" in p


def test_report_prompt_size_cap_truncates_low_severity():
    big = Evidence(kind="logcat", excerpt=LOG)
    fs = [mk(f"f{i}", "rt.anr", score=100 - i, ev=[big], title=f"Issue {i}") for i in range(60)]
    p = report_prompt(mk_run(), fs)
    assert len(p) <= FULL_LIMIT
    assert "Issue 0" in p and "condensed" in p
    assert "## Verification checklist" in p


def test_report_markdown_includes_fix_section():
    md = render_markdown(mk_run(), [mk("a", "rt.anr")], [])
    assert "## Fix with AI" in md and "Fix all issues found by BharatBench" in md


class FakeService:
    def __init__(self, run, findings):
        self.run, self.findings = run, findings

    async def get_run(self, rid):
        return self.run if self.run and rid == self.run.id else None

    async def list_findings(self, rid):
        return self.findings


def client(monkeypatch, run, findings=()):
    monkeypatch.setattr(routes, "get_run_service", lambda: FakeService(run, list(findings)))
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app)


def test_routes_ok(monkeypatch):
    c = client(monkeypatch, mk_run(), [mk("f1", "rt.anr")])
    r = c.get("/api/runs/r1/fix-prompt")
    assert r.status_code == 200 and r.json()["findings"] == 1 and "Fix all issues" in r.json()["prompt"]
    r = c.get("/api/runs/r1/findings/f1/fix-prompt")
    assert r.status_code == 200 and "## Acceptance criteria" in r.json()["prompt"]


def test_routes_404_409(monkeypatch):
    c = client(monkeypatch, mk_run(), [mk("f1", "rt.anr")])
    assert c.get("/api/runs/nope/fix-prompt").status_code == 404
    assert c.get("/api/runs/r1/findings/zzz/fix-prompt").status_code == 404
    c2 = client(monkeypatch, mk_run("running"), [mk("f1", "rt.anr")])
    assert c2.get("/api/runs/r1/fix-prompt").status_code == 409
    assert c2.get("/api/runs/r1/findings/f1/fix-prompt").status_code == 409
