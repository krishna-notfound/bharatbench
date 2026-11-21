from app.analyzer import runtime_findings, steps_to_maestro
from app.models import (
    HarnessCrash,
    HarnessProfileResult,
    HarnessResult,
    HarnessScreen,
    HarnessStep,
)

RUN = "abcdef123456"


def profile(profile_id="baseline", **kw) -> HarnessProfileResult:
    base = {
        "profile_id": profile_id,
        "applied": True,
        "launched": True,
        "launch_ms": 1000,
        "logcat": f"{profile_id}/logcat.txt",
        "screens": [HarnessScreen(index=0, screenshot=f"{profile_id}/s0.png")],
        "steps": [
            HarnessStep(index=1, action="tap", target="Login", ok=True),
            HarnessStep(index=2, action="tap", target="x", ok=False),
        ],
    }
    base.update(kw)
    return HarnessProfileResult(**base)


def run(*profiles) -> list:
    return runtime_findings(RUN, HarnessResult(job_id="j", device="emu", profiles=list(profiles)))


def by_rule(findings, rule):
    return [f for f in findings if f.rule_id == rule]


def test_clean_run_has_no_findings():
    assert run(profile()) == []


def test_crash_positive():
    (f,) = by_rule(run(profile(crashes=[HarnessCrash(type="crash", excerpt="FATAL EXCEPTION NPE")])), "rt.crash")
    assert f.severity == "critical" and f.category == "reliability" and f.source == "runtime"
    assert f.profile_id == "baseline" and f.affected_journey == "Auto crawl" and f.journey_step == 2
    kinds = {e.kind for e in f.evidence}
    assert {"logcat", "screenshot"} <= kinds
    assert f.repro_flow.startswith("appId:") and f.repro_steps and f.probable_cause and f.suggested_fix
    assert f.id == "abcdef12-rt.crash-1"


def test_crash_negative_and_anr_and_multiple():
    assert by_rule(run(profile()), "rt.crash") == []
    crashes = [HarnessCrash(type="anr", excerpt="ANR in x"), HarnessCrash(type="crash", excerpt="a"),
               HarnessCrash(type="native_crash", excerpt="b")]
    fs = run(profile(crashes=crashes))
    assert len(by_rule(fs, "rt.anr")) == 1 and len(by_rule(fs, "rt.crash")) == 2
    assert len({f.id for f in fs}) == 3


def test_launch_failed():
    (f,) = by_rule(run(profile(launched=False, launch_ms=None)), "rt.launch_failed")
    assert f.severity == "critical" and f.journey_step == 0 and f.evidence
    assert by_rule(run(profile()), "rt.launch_failed") == []


def test_slow_launch_thresholds_and_baseline():
    fs = run(profile(), profile("budget_2gb", launch_ms=6000, logcat=None))
    (f,) = by_rule(fs, "rt.slow_launch")
    assert f.severity == "high" and "Baseline launch was 1000 ms" in f.description
    assert f.evidence[0].kind == "metric"
    (m,) = by_rule(run(profile(launch_ms=3000)), "rt.slow_launch")
    assert m.severity == "medium"
    assert by_rule(run(profile(launch_ms=2000)), "rt.slow_launch") == []


def test_network_errors_deduped_types():
    errs = ["java.net.SocketTimeoutException: a", "java.net.SocketTimeoutException: b", "java.io.IOException: c"]
    (f,) = by_rule(run(profile("flaky_network", network_errors=errs)), "rt.network_errors")
    assert f.severity == "high" and f.category == "network"
    assert f.title.count("SocketTimeoutException") == 1
    assert "OkHttp timeouts" in f.suggested_fix
    assert by_rule(run(profile()), "rt.network_errors") == []


def test_stuck_loading():
    (f,) = by_rule(run(profile(stuck_loading=True)), "rt.stuck_loading")
    assert f.severity == "high" and f.category == "network" and f.evidence
    assert by_rule(run(profile()), "rt.stuck_loading") == []


def test_state_lost():
    (f,) = by_rule(run(profile("process_death", state_lost_after_restore=True)), "rt.state_lost")
    assert f.severity == "high" and f.category == "reliability"
    assert by_rule(run(profile("process_death", state_lost_after_restore=False)), "rt.state_lost") == []
    assert by_rule(run(profile("process_death", state_lost_after_restore=None)), "rt.state_lost") == []


def test_memory_high_only_on_budget():
    (f,) = by_rule(run(profile("budget_2gb", memory_pss_kb=350_000)), "rt.memory_high")
    assert f.severity == "medium" and f.category == "memory"
    assert by_rule(run(profile("budget_2gb", memory_pss_kb=300_000)), "rt.memory_high") == []
    assert by_rule(run(profile("baseline", memory_pss_kb=900_000)), "rt.memory_high") == []


def test_profile_not_applied_note():
    (f,) = run(profile("low_storage", applied=False, apply_note="df failed", launched=False))
    assert f.rule_id == "rt.profile_not_applied" and f.severity == "low" and f.category == "storage"
    assert "df failed" in f.evidence[0].excerpt
    assert by_rule(run(profile("low_storage")), "rt.profile_not_applied") == []


def test_every_runtime_finding_has_evidence():
    p = profile(
        "budget_2gb", logcat=None, screens=[], steps=[], launched=False, stuck_loading=True,
        crashes=[HarnessCrash(type="anr", excerpt="x")], network_errors=["E: x"], memory_pss_kb=400_000,
        launch_ms=9000,
    )
    fs = run(p)
    assert len(fs) >= 5
    assert all(f.evidence for f in fs)


def test_maestro_yaml():
    steps = [
        HarnessStep(index=1, action="tap", target="Sign in", ok=True),
        HarnessStep(index=2, action="tap", target="com.app:id/btn_ok", ok=True),
        HarnessStep(index=3, action="tap", target="120,340", ok=True),
        HarnessStep(index=4, action="back", ok=True),
        HarnessStep(index=5, action="background", ok=True),
        HarnessStep(index=6, action="kill", ok=True),
        HarnessStep(index=7, action="restore", ok=True),
        HarnessStep(index=8, action="wait", ok=True),
    ]
    yaml = steps_to_maestro("com.app", steps, [])
    assert yaml.splitlines() == [
        "appId: com.app",
        "---",
        "- launchApp",
        '- tapOn: "Sign in"',
        '- tapOn: {id: "btn_ok"}',
        '- tapOn: {point: "120,340"}',
        "- back",
        "- pressKey: Home",
        "- stopApp",
        "- launchApp",
    ]
    assert "assertVisible" not in yaml


def test_maestro_escapes_quotes():
    yaml = steps_to_maestro("p", [HarnessStep(index=1, action="tap", target='say "hi"', ok=True)], [])
    assert '- tapOn: "say \\"hi\\""' in yaml
