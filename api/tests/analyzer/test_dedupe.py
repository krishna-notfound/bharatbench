from app.analyzer.dedupe import MAX_EVIDENCE, dedupe_findings
from app.models import Evidence, Finding


def _static(i: int, sev="medium", rule="sec.exported_component") -> Finding:
    return Finding(
        id=f"s{i}", run_id="r", source="static", category="security", rule_id=rule,
        title=f"Exported activity without permission: com.x.A{i}", severity=sev, description="Reachable.",
        evidence=[Evidence(kind="manifest", excerpt=f"<activity A{i}>")],
    )


def _rt(i: int, profile="budget_2gb", rule="rt.crash", log="FATAL EXCEPTION pid 123") -> Finding:
    return Finding(
        id=f"r{i}", run_id="r", source="runtime", category="reliability", rule_id=rule,
        title="Crash", severity="high", description="Crashed.", profile_id=profile,
        evidence=[Evidence(kind="logcat", excerpt=log)],
    )


def test_static_same_rule_merged_with_max_severity_and_capped_evidence():
    group = [_static(i, "high" if i == 3 else "medium") for i in range(15)] + [_static(0, rule="sec.other")]
    out = dedupe_findings(group)
    assert len(out) == 2
    m = out[0]
    assert m.severity == "high" and "15 occurrences" in m.title
    assert len(m.evidence) == MAX_EVIDENCE
    assert "com.x.A0" in m.description and "and 5 more" in m.description


def test_single_finding_untouched():
    f = _static(1)
    assert dedupe_findings([f]) == [f]


def test_runtime_dedupe_by_profile_and_signature():
    out = dedupe_findings(
        [_rt(1, log="FATAL EXCEPTION pid 123"), _rt(2, log="FATAL EXCEPTION pid 456"),
         _rt(3, profile="flaky_network"), _rt(4, log="different crash")]
    )
    assert len(out) == 3


def test_baseline_comparison_suffix():
    base = _rt(9, profile="baseline", rule="rt.slow_launch")
    out = dedupe_findings([base, _rt(1, rule="rt.slow_launch"), _rt(2)], baseline_ran=True)
    by_rule = {(f.rule_id, f.profile_id): f for f in out}
    assert "Also observed on the baseline" in by_rule[("rt.slow_launch", "budget_2gb")].description
    assert "Not observed on the baseline" in by_rule[("rt.crash", "budget_2gb")].description
    assert "Baseline comparison" not in by_rule[("rt.slow_launch", "baseline")].description
    assert "Baseline comparison" not in dedupe_findings([_rt(1)], baseline_ran=False)[0].description
