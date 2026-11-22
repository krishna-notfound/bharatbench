"""Deterministic, explainable test planning (f19).

`plan_initial` picks conditions from what the APK declares; `plan_followup` picks what to re-test after
results. Every choice carries a plain-language `why` the voice agent can say out loud. No network, no LLM.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.models import AppInfo, Finding, ProfileId, Run
from app.profiles import PROFILES

DEFAULT_STEPS = 8
MANY_ACTIVITIES_STEPS = 12
DEEP_STEPS = 16

_ALL: list[ProfileId] = [p.id for p in PROFILES if p.fidelity != "unsupported"]
_LARGE_APK_BYTES = 30 * 1024 * 1024
_STORAGE_PERMS = ("WRITE_EXTERNAL_STORAGE", "MANAGE_EXTERNAL_STORAGE", "READ_MEDIA_", "READ_EXTERNAL_STORAGE")
_BATTERY_PERMS = (
    "WAKE_LOCK",
    "FOREGROUND_SERVICE",
    "RECEIVE_BOOT_COMPLETED",
    "ACCESS_FINE_LOCATION",
    "ACCESS_COARSE_LOCATION",
    "ACCESS_BACKGROUND_LOCATION",
    "SCHEDULE_EXACT_ALARM",
)
_CRASHY = ("rt.anr", "rt.crash", "rt.launch_failed")
_NETWORKY = ("rt.network_errors", "rt.stuck_loading")
_ACTIONABLE = {*_CRASHY, *_NETWORKY, "rt.memory_high", "rt.state_lost"}


class PlanReason(BaseModel):
    profile: ProfileId
    why: str


class TestPlan(BaseModel):
    __test__ = False  # not a pytest class

    kind: Literal["initial", "followup"]
    profiles: list[ProfileId]
    journey_steps: int
    reasons: list[PlanReason]
    note: str | None = None


def _perm_names(app: AppInfo) -> set[str]:
    return {p.rsplit(".", 1)[-1].upper() for p in app.permissions}


def _matching(perms: set[str], prefixes: tuple[str, ...]) -> list[str]:
    return sorted(p for p in perms if p.startswith(prefixes))


def _is_complex(app: AppInfo) -> bool:
    """AppInfo has no activity count, so a big dex/APK or many permissions stands in for 'many screens'."""
    count = getattr(app, "activity_count", None)
    if isinstance(count, int):
        return count > 3
    return app.dex_count >= 2 or app.size_bytes >= _LARGE_APK_BYTES or len(app.permissions) >= 10


def _heavy(app: AppInfo) -> str | None:
    bits = []
    if app.size_bytes >= _LARGE_APK_BYTES:
        bits.append(f"large APK, {app.size_bytes // (1024 * 1024)} MB")
    if len(app.native_abis) >= 3:
        bits.append(f"{len(app.native_abis)} native ABIs")
    if app.dex_count >= 3:
        bits.append(f"{app.dex_count} dex files")
    return ", ".join(bits) or None


def plan_initial(app: AppInfo, static_findings: list[Finding]) -> TestPlan:
    perms = _perm_names(app)
    reasons: list[PlanReason] = [
        PlanReason(profile="baseline", why="Always run first: the normal-conditions reference to compare against.")
    ]
    heavy = _heavy(app)
    if "INTERNET" in perms:
        reasons.append(
            PlanReason(
                profile="flaky_network",
                why="Your app talks to the network, so I will cut connectivity mid-journey.",
            )
        )
    if "INTERNET" in perms or heavy:
        why = "Your app talks to the network, so a slow 2 Mbps link on a 2 GB phone is the common case."
        if heavy:
            why = (
                f"{why} It is also heavy ({heavy}), a memory-pressure risk."
                if "INTERNET" in perms
                else f"It is heavy ({heavy}), a memory-pressure risk on 2 GB phones."
            )
        reasons.append(PlanReason(profile="budget_2gb", why=why))
    storage = _matching(perms, _STORAGE_PERMS)
    if storage:
        reasons.append(
            PlanReason(
                profile="low_storage",
                why=f"It asks for storage or media access ({', '.join(storage[:2])}), so a nearly full phone matters.",
            )
        )
    battery = _matching(perms, _BATTERY_PERMS)
    if battery:
        reasons.append(
            PlanReason(
                profile="battery_saver",
                why=f"It uses background work or location ({', '.join(battery[:2])}), which battery saver restricts.",
            )
        )
    complex_app = _is_complex(app)
    if complex_app:
        reasons.append(
            PlanReason(
                profile="process_death",
                why="It looks like it has many screens and state, so I will check what is lost when Android kills it.",
            )
        )
    note = None
    if static_findings:
        note = f"{len(static_findings)} static finding(s) already recorded; runtime tests look for what a static scan cannot."
    return TestPlan(
        kind="initial",
        profiles=list(dict.fromkeys(r.profile for r in reasons)),
        journey_steps=MANY_ACTIVITIES_STEPS if complex_app else DEFAULT_STEPS,
        reasons=reasons,
        note=note,
    )


def _ids(fs: list[Finding]) -> str:
    return ", ".join(f.id for f in fs[:4])


def plan_followup(run: Run, findings: list[Finding]) -> TestPlan:
    reasons: list[PlanReason] = []
    steps = DEFAULT_STEPS

    def add(profile: ProfileId, why: str) -> None:
        reasons.append(PlanReason(profile=profile, why=why))

    runtime = [f for f in findings if f.source == "runtime"]
    by_rule: dict[str, list[Finding]] = {}
    for f in runtime:
        by_rule.setdefault(f.rule_id, []).append(f)

    for rule in _CRASHY:
        for f in by_rule.get(rule, []):
            prof: ProfileId = f.profile_id or "baseline"
            label = rule.removeprefix("rt.").replace("_", " ")
            if prof == "baseline":
                add("baseline", f"A {label} showed up even on normal conditions (finding {f.id}); a longer journey will capture more.")
            else:
                add(prof, f"A {label} appeared on {prof} (finding {f.id}); repeating it with a longer journey.")
                add("baseline", f"Re-running baseline to confirm the {label} (finding {f.id}) is specific to {prof}.")
            steps = DEEP_STEPS
    net = [f for rule in _NETWORKY for f in by_rule.get(rule, [])]
    if net:
        add("flaky_network", f"Network errors or a stuck loading screen (findings {_ids(net)}); testing connectivity drops again, deeper.")
        add("budget_2gb", f"Same network problems (findings {_ids(net)}); checking whether a slow link on a 2 GB phone makes it worse.")
        steps = DEEP_STEPS
    if mem := by_rule.get("rt.memory_high"):
        add("budget_2gb", f"High memory use (finding {_ids(mem)}); repeating under the 2 GB cap with a longer journey.")
        steps = DEEP_STEPS
    if lost := by_rule.get("rt.state_lost"):
        add("process_death", f"State was lost after Android killed the app (finding {_ids(lost)}); testing process death deeper.")
        steps = DEEP_STEPS
    for f in by_rule.get("rt.profile_not_applied", []):
        if f.profile_id:
            add(f.profile_id, f"{f.profile_id} was not applied last time (finding {f.id}); retrying it.")

    note = None
    if not _ACTIONABLE & set(by_rule) and not reasons:
        uncovered = [p for p in _ALL if p not in run.profile_ids]
        if run.summary is not None and not run.summary.runtime_executed:
            why = (run.summary.runtime_skipped_reason or "no reason recorded").splitlines()[0][:90]
            for p in run.profile_ids:
                add(p, f"Runtime tests did not execute last time ({why}); trying again.")
        elif uncovered:
            what = "found no runtime problems" if not runtime else "found nothing I can chase further"
            for p in uncovered:
                add(p, f"The last run {what} and never tried {p}; covering it with a longer journey.")
            steps = DEEP_STEPS
        elif not reasons:
            note = "Every condition has already been tested and nothing actionable showed up; nothing more to plan."

    return TestPlan(
        kind="followup",
        profiles=list(dict.fromkeys(r.profile for r in reasons)),
        journey_steps=steps,
        reasons=reasons,
        note=note,
    )
