"""Agent test failures -> runtime findings (f23). Passed or unjudged tests never produce findings."""

from app.analyzer.ids import finding_id
from app.models import Evidence, Finding, HarnessResult


def agent_test_findings(run_id: str, result: HarnessResult) -> list[Finding]:
    out: list[Finding] = []
    for n, t in enumerate((t for t in result.agent_tests if t.passed is False), start=1):
        shots = [s.screenshot for s in t.screens if s.screenshot]
        steps = [
            f"{s.action.replace('_', ' ').capitalize()}{f' {chr(39)}{s.target}{chr(39)}' if s.target else ''}"
            f"{f' ({s.note})' if s.note else ''}"
            for s in t.steps
            if s.action != "launch"
        ]
        evidence = [Evidence(kind="note", excerpt=f"Agent verdict: {t.reason}")]
        if steps:
            evidence.append(Evidence(kind="note", excerpt="Steps: " + "; ".join(steps)[:600]))
        if shots:
            evidence.append(Evidence(kind="screenshot", ref=shots[-1]))
        out.append(
            Finding(
                id=finding_id(run_id, "rt.agent_test_failed", n),
                run_id=run_id,
                source="runtime",
                category="reliability",
                rule_id="rt.agent_test_failed",
                title=f"Agent test failed: {t.title}",
                severity="medium",
                description=f"The agent wrote this test for your app and it did not pass: {t.reason}",
                evidence=evidence,
                repro_steps=["Launch the app", *steps],
                affected_journey=t.title,
                profile_id=t.condition,
            )
        )
    return out
