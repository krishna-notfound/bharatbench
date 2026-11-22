"""Markdown report rendering."""

from app.fix_prompt import report_prompt
from app.models import Finding, Profile, Run
from app.profiles import UNSUPPORTED_CONDITIONS


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _one_line(text: str) -> str:
    """Collapse multi-line errors (e.g. httpx 'For more information check: ...') into one line."""
    return " ".join(text.split()).split(" For more information check:")[0]


def render_markdown(run: Run, findings: list[Finding], profiles: list[Profile]) -> str:
    lines: list[str] = [f"# BharatBench report: {run.apk_name}", ""]
    lines += [f"- Run: `{run.id}`", f"- Status: {run.status}", f"- Created: {run.created_at.isoformat()}"]
    if run.error:
        lines.append(f"- Error: {_one_line(run.error)}")
    lines.append("")

    lines += ["## App", ""]
    if run.app:
        a = run.app
        lines += [
            f"- Package: `{a.package_name}`",
            f"- Name: {a.app_name or 'unknown'}",
            f"- Version: {a.version_name or 'unknown'} ({a.version_code or 'unknown'})",
            f"- SDK: min {a.min_sdk}, target {a.target_sdk}",
            f"- Size: {a.size_bytes / 1_000_000:.1f} MB; dex files: {a.dex_count}",
            f"- Native ABIs: {', '.join(a.native_abis) or 'none'}",
            f"- Permissions: {len(a.permissions)}",
        ]
    else:
        lines.append("App information is not available (analysis did not complete).")
    lines.append("")

    lines += ["## Summary", ""]
    if run.summary:
        s = run.summary
        lines += [
            f"- Reliability score: **{s.reliability_score}** / 100",
            (
                f"- Findings: {s.total_findings} (critical {s.counts['critical']}, high {s.counts['high']}, "
                f"medium {s.counts['medium']}, low {s.counts['low']})"
            ),
            f"- Runtime testing executed: {'yes' if s.runtime_executed else 'no'}",
        ]
        if s.runtime_skipped_reason:
            lines.append(f"- Runtime skipped because: {_one_line(s.runtime_skipped_reason)}")
    else:
        lines.append("No summary yet.")
    lines.append("")

    lines += [
        "## Assumptions",
        "",
        "`users_exposed` is an adjustable assumption (share of target users facing the condition), not measured data.",
        "",
        "| Profile | Users exposed | Fidelity | How it is applied |",
        "| ------- | ------------- | -------- | ----------------- |",
    ]
    for p in profiles:
        lines.append(
            f"| {_cell(p.name)} | {p.users_exposed:.0%} | {p.fidelity} | {_cell(p.how)} |"
        )
    lines += ["", "Not simulated:", ""]
    lines += [f"- `{k}`: {v}" for k, v in UNSUPPORTED_CONDITIONS.items()]
    lines.append("")

    lines += ["## Findings (ranked by impact)", ""]
    if not findings:
        lines += ["No findings.", ""]
    ranked = sorted(findings, key=lambda f: f.impact.score if f.impact else 0.0, reverse=True)
    for i, f in enumerate(ranked, 1):
        score = f"{f.impact.score}" if f.impact else "n/a"
        lines += [f"### {i}. {f.title}", ""]
        lines += [
            f"- Severity: {f.severity} | Impact score: {score} | Category: {f.category} | Rule: `{f.rule_id}`",
            f"- Source: {f.source}" + (f" | Profile: {f.profile_id}" if f.profile_id else ""),
        ]
        if f.affected_journey:
            lines.append(f"- Journey: {f.affected_journey} (step {f.journey_step})")
        lines += ["", f.description, ""]
        if f.probable_cause:
            lines += [f"**Probable cause:** {f.probable_cause}", ""]
        if f.evidence:
            lines.append("**Evidence:**")
            for e in f.evidence:
                ref = f" (`{e.ref}`)" if e.ref else ""
                lines.append(f"- {e.kind}{ref}")
                if e.excerpt:
                    lines += ["  ```", *[f"  {ln}" for ln in e.excerpt.splitlines()], "  ```"]
            lines.append("")
        if f.suggested_fix:
            lines += [f"**Suggested fix:** {f.suggested_fix}", ""]
        if f.repro_steps:
            lines.append("**Repro steps:**")
            lines += [f"{n}. {step}" for n, step in enumerate(f.repro_steps, 1)]
            lines.append("")
        if f.repro_flow:
            lines += ["**Maestro flow:**", "", "```yaml", f.repro_flow.rstrip(), "```", ""]
    if findings:
        lines += [
            "## Fix with AI",
            "",
            ("Paste this prompt into your AI coding assistant (Claude Code, Cursor or Copilot) inside your app's "
            "repository, then re-run the test to confirm. Each finding also has its own prompt in the BharatBench app."),
            "",
            "````markdown",
            report_prompt(run, findings),
            "````",
            "",
        ]
    return "\n".join(lines)
