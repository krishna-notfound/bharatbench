"""Merge repeated findings so one rule firing N times reads as one finding."""

from __future__ import annotations

import re

from app.models import Evidence, Finding, Severity

MAX_EVIDENCE = 10
MAX_LISTED = 10
_SEV_ORDER: dict[Severity, int] = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_DIGITS = re.compile(r"\d+")


_ANR_COMP = re.compile(r"ANR in \S+(?: \(([^)]*)\))?")
_ANR_REASON = re.compile(r"Reason:\s*(.+)")
_EXC = re.compile(r"\b((?:[A-Za-z_]\w*\.)+[A-Z]\w*(?:Exception|Error))\b")
_FRAME = re.compile(r"\bat\s+([\w.$<>]+)\(")


def crash_signature(excerpt: str) -> str:
    """Stable id of a crash/ANR excerpt: ignores timestamps, pids and durations so repeats collapse."""
    anr = _ANR_COMP.search(excerpt)
    if anr:
        reason = _ANR_REASON.search(excerpt)
        why = _DIGITS.sub("#", reason.group(1).strip())[:100] if reason else ""
        return f"anr|{anr.group(1) or ''}|{why}"
    exc = _EXC.search(excerpt)
    if exc:
        frame = _FRAME.search(excerpt)
        return f"crash|{exc.group(1)}|{frame.group(1) if frame else ''}"
    for line in excerpt.splitlines():
        if line.strip():
            return _DIGITS.sub("#", line.strip())[:160]
    return ""


def _signature(f: Finding) -> str:
    """Crash signature for runtime findings: from the first logcat excerpt."""
    for e in f.evidence:
        if e.kind == "logcat" and e.excerpt:
            return crash_signature(e.excerpt)
    return ""


# Titles of these rules carry no per-signature detail, so separate findings would look identical to users.
_ONE_PER_PROFILE = {"rt.anr"}


def _key(f: Finding) -> tuple[str, ...]:
    if f.source == "static":
        return ("static", f.rule_id)
    if f.rule_id in _ONE_PER_PROFILE:
        return ("runtime", f.rule_id, f.profile_id or "")
    return ("runtime", f.rule_id, f.profile_id or "", _signature(f))


def _detail(f: Finding) -> str:
    if ": " in f.title:
        return f.title.split(": ", 1)[1]
    for e in f.evidence:
        if e.excerpt:
            return e.excerpt.splitlines()[0][:120]
    return f.title


def _merge(group: list[Finding]) -> Finding:
    first = group[0]
    if len(group) == 1:
        return first
    severity = max((f.severity for f in group), key=lambda s: _SEV_ORDER[s])
    seen: set[tuple[str, str | None, str | None]] = set()
    evidence: list[Evidence] = []
    for f in group:
        for e in f.evidence:
            k = (e.kind, e.ref, e.excerpt)
            if k not in seen and len(evidence) < MAX_EVIDENCE:
                seen.add(k)
                evidence.append(e)
    details = list(dict.fromkeys(_detail(f) for f in group))
    listed = details[:MAX_LISTED]
    more = len(details) - len(listed)
    summary = f"Affected ({len(group)}): " + "; ".join(listed) + (f"; and {more} more" if more > 0 else "")
    head = first.title.split(": ", 1)[0] if ": " in first.title else first.title
    return first.model_copy(
        update={
            "title": f"{head} ({len(group)} occurrences)",
            "severity": severity,
            "description": f"{first.description}\n\n{summary}",
            "evidence": evidence,
        }
    )


def dedupe_findings(findings: list[Finding], baseline_ran: bool = False) -> list[Finding]:
    """Group by key (static: rule_id; runtime: rule_id+profile+crash signature), keeping first-seen order.

    With `baseline_ran`, runtime findings on non-baseline profiles get a factual suffix saying whether the
    baseline profile produced a finding for the same rule.
    """
    groups: dict[tuple[str, ...], list[Finding]] = {}
    for f in findings:
        groups.setdefault(_key(f), []).append(f)
    merged = [_merge(g) for g in groups.values()]
    if not baseline_ran:
        return merged
    baseline_rules = {f.rule_id for f in merged if f.source == "runtime" and f.profile_id == "baseline"}
    out: list[Finding] = []
    for f in merged:
        if f.source == "runtime" and f.profile_id not in (None, "baseline"):
            note = (
                "Also observed on the baseline profile, so not specific to this condition."
                if f.rule_id in baseline_rules
                else "Not observed on the baseline profile, so this is triggered by the constrained condition."
            )
            f = f.model_copy(update={"description": f"{f.description}\n\nBaseline comparison: {note}"})
        out.append(f)
    return out
