import pytest

from app.scoring import SEVERITY_WEIGHTS, flow_usage, score_findings, summarize
from tests.conftest import make_finding


def test_known_value_high_budget_step0():
    f = make_finding(severity="high", profile_id="budget_2gb", journey_step=0)
    [scored] = score_findings([f])
    assert scored.impact.score == 31.5
    assert scored.impact.users_exposed == 0.45
    assert scored.impact.severity_weight == 0.7
    assert scored.impact.flow_usage == 1.0


def test_weights_verbatim():
    assert SEVERITY_WEIGHTS == {"critical": 1.0, "high": 0.7, "medium": 0.4, "low": 0.15}


def test_flow_usage():
    assert flow_usage(make_finding(journey_step=None)) == 1.0
    assert flow_usage(make_finding(journey_step=0)) == 1.0
    assert flow_usage(make_finding(journey_step=2)) == pytest.approx(0.81)
    assert flow_usage(make_finding(journey_step=50)) == 0.3


def test_no_profile_means_full_exposure_and_sorted_desc():
    low = make_finding("a", severity="low")
    crit = make_finding("b", severity="critical")
    scored = score_findings([low, crit])
    assert [f.id for f in scored] == ["b", "a"]
    assert scored[0].impact.score == 100.0
    assert scored[1].impact.score == 15.0


def test_summarize_formula_and_counts():
    scored = score_findings([make_finding("a", severity="critical"), make_finding("b", severity="high")])
    s = summarize(scored, False, "no harness")
    # 100 * exp(-(100 + 70) / 400) = 65.4
    assert s.reliability_score == 65.4
    assert s.counts == {"critical": 1, "high": 1, "medium": 0, "low": 0}
    assert s.total_findings == 2
    assert s.runtime_executed is False and s.runtime_skipped_reason == "no harness"


def test_summarize_decays_and_empty_is_100():
    many = score_findings([make_finding(str(i), severity="critical") for i in range(10)])
    assert summarize(many, True, None).reliability_score == 8.2
    assert summarize([], True, None).reliability_score == 100.0
