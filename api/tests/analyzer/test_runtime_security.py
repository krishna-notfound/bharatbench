from app.analyzer import runtime_findings
from app.analyzer.dedupe import crash_signature, dedupe_findings
from app.models import (
    HarnessCrash,
    HarnessProfileResult,
    HarnessResult,
    HarnessSecurityCheck,
    HarnessSecurityEvidence,
)

RUN = "abcdef123456"
PKG = "com.example.shop"


def prof(profile_id="baseline", **kw) -> HarnessProfileResult:
    base = {"profile_id": profile_id, "applied": True, "launched": True, "launch_ms": 1000, "logcat": "logcat/b.txt"}
    base.update(kw)
    return HarnessProfileResult(**base)


def run(profiles, security=()) -> list:
    return runtime_findings(RUN, HarnessResult(job_id="j", device="d", profiles=profiles, security=list(security)), PKG)


def anr(ts: str, pid: int, ms: int) -> HarnessCrash:
    return HarnessCrash(
        type="anr",
        excerpt=(
            f"11-21 {ts}  1000  1100 E ActivityManager: ANR in {PKG} ({PKG}/.MainActivity)\n"
            f"11-21 {ts}  1000  1100 E ActivityManager: PID: {pid}\n"
            f"11-21 {ts}  1000  1100 E ActivityManager: Reason: Input dispatching timed out (waited {ms}ms)"
        ),
    )


def test_identical_anrs_on_one_profile_become_one_finding():
    out = run([prof(crashes=[anr("17:46:12.100", 4242, 5001), anr("17:46:40.900", 4301, 5013)])])
    anrs = [f for f in out if f.rule_id == "rt.anr"]
    assert len(anrs) == 1 and "2 times" in anrs[0].description
    assert anrs[0].title == "App not responding (ANR) on Baseline"


def test_different_anr_reasons_stay_separate():
    other = HarnessCrash(type="anr", excerpt=anr("17:47:00.000", 1, 1).excerpt.replace("Input dispatching", "Broadcast of"))
    assert len([f for f in run([prof(crashes=[anr("17:46:12.100", 1, 1), other])]) if f.rule_id == "rt.anr"]) == 2


def test_dedupe_collapses_anrs_that_only_differ_in_time():
    f1 = run([prof(crashes=[anr("17:46:12.100", 4242, 5001)])])[0]
    f2 = run([prof(crashes=[anr("17:51:03.400", 9999, 5020)])])[0]
    assert crash_signature(f1.evidence[0].excerpt) == crash_signature(f2.evidence[0].excerpt)
    assert len(dedupe_findings([f1, f2])) == 1


def test_crash_title_names_the_exception():
    c = HarnessCrash(
        type="crash",
        excerpt=f"11-21 17:46:11.000  4242  4242 E AndroidRuntime: FATAL EXCEPTION: main\n"
        "11-21 17:46:11.000  4242  4242 E AndroidRuntime: java.lang.NullPointerException: boom\n"
        f"11-21 17:46:11.000  4242  4242 E AndroidRuntime: \tat {PKG}.Cart.load(Cart.java:42)",
    )
    f = next(f for f in run([prof(crashes=[c])]) if f.rule_id == "rt.crash")
    assert f.title == "App crash on Baseline: NullPointerException"


def test_network_title_has_no_log_timestamps():
    lines = [
        "11-21 17:46:12.123  4242  4242 W OkHttp: java.net.SocketTimeoutException: timeout",
        "11-21 17:46:13.223  4242  4242 W OkHttp: java.net.SocketTimeoutException: timeout again",
        "11-21 17:46:14.323  4242  4242 W OkHttp: java.net.UnknownHostException: api.example.com",
    ]
    f = next(f for f in run([prof(network_errors=lines)]) if f.rule_id == "rt.network_errors")
    assert f.title == "Network errors on Baseline: SocketTimeoutException ×2, UnknownHostException"
    assert "11-21" not in f.title and "11-21" not in f.description
    assert any("11-21" in (e.excerpt or "") for e in f.evidence)  # raw lines stay as evidence


def check(cid, passed=False, ran=True, severity="high", ev=("x",)) -> HarnessSecurityCheck:
    return HarnessSecurityCheck(
        id=cid, title=cid, passed=passed, ran=ran, severity=severity, note="n",
        evidence=[HarnessSecurityEvidence(kind="note", excerpt=e) for e in ev],
    )  # fmt: skip


def test_failed_security_checks_become_runtime_security_findings():
    sec = [
        check("sec.storage_secrets", ev=("shared_prefs/a.xml: credential auth_token=eyJh…hijk",)),
        check("sec.exported_components", severity="medium", ev=()),
        check("sec.cleartext_traffic", passed=True),  # passed -> no finding
        check("sec.debuggable", ran=False),  # could not run -> no finding
    ]
    out = [f for f in run([prof()], sec) if f.rule_id.startswith("rt.sec.")]
    assert [f.rule_id for f in out] == ["rt.sec.storage_secrets", "rt.sec.exported_components"]
    assert all(f.source == "runtime" and f.category == "security" and f.evidence for f in out)
    assert out[0].severity == "high" and "eyJh…hijk" in out[0].evidence[0].excerpt
    assert out[1].evidence[0].kind == "note"  # fallback evidence when the check supplied none


def test_security_empty_by_default_keeps_old_behaviour():
    assert run([prof()]) == []
