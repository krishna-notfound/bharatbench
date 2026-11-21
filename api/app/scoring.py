"""Impact scoring: 100 * users_exposed * severity_weight * flow_usage."""

import math

from app.models import Finding, Impact, RunSummary, Severity
from app.profiles import PROFILE_BY_ID

SEVERITY_WEIGHTS: dict[Severity, float] = {"critical": 1.0, "high": 0.7, "medium": 0.4, "low": 0.15}


def flow_usage(finding: Finding) -> float:
    if finding.journey_step in (None, 0):
        return 1.0
    return max(0.3, 0.9**finding.journey_step)


def score_findings(findings: list[Finding]) -> list[Finding]:
    scored: list[Finding] = []
    for f in findings:
        users = PROFILE_BY_ID[f.profile_id].users_exposed if f.profile_id else 1.0
        weight = SEVERITY_WEIGHTS[f.severity]
        usage = flow_usage(f)
        impact = Impact(
            users_exposed=users,
            severity_weight=weight,
            flow_usage=usage,
            score=round(100 * users * weight * usage, 1),
        )
        scored.append(f.model_copy(update={"impact": impact}))
    return sorted(scored, key=lambda f: f.impact.score if f.impact else 0.0, reverse=True)


def summarize(findings: list[Finding], runtime_executed: bool, skipped_reason: str | None) -> RunSummary:
    counts: dict[Severity, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in findings:
        counts[f.severity] += 1
    total = sum(f.impact.score for f in findings if f.impact)
    return RunSummary(
        counts=counts,
        total_findings=len(findings),
        reliability_score=round(100.0 * math.exp(-total / 400.0), 1),
        runtime_executed=runtime_executed,
        runtime_skipped_reason=skipped_reason,
    )
