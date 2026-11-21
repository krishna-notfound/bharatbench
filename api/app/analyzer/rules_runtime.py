"""Runtime rules: HarnessResult -> Findings. Every finding carries at least one Evidence."""

from app.analyzer.ids import finding_id
from app.analyzer.maestro import steps_to_maestro
from app.models import (
    Category,
    Evidence,
    Finding,
    HarnessCrash,
    HarnessProfileResult,
    HarnessResult,
    Severity,
)
from app.profiles import PROFILE_BY_ID

JOURNEY = "Auto crawl"
_PACKAGE_PLACEHOLDER = "<package>"


class _Ctx:
    """Builds findings for one profile result with shared repro data and a per-rule counter."""

    def __init__(
        self, run_id: str, pr: HarnessProfileResult, package: str, counts: dict[str, int], baseline_ms: int | None
    ) -> None:
        self.run_id = run_id
        self.pr = pr
        self.counts = counts
        self.baseline_ms = baseline_ms
        how = PROFILE_BY_ID[pr.profile_id].how
        self.steps = [f"Apply profile '{pr.profile_id}': {how}", "Launch the app"]
        for s in sorted(pr.steps, key=lambda x: x.index):
            if s.action == "launch":
                continue
            tgt = f" '{s.target}'" if s.target else ""
            self.steps.append(f"{s.action.replace('_', ' ').capitalize()}{tgt}")
        self.flow = pr.maestro_flow or steps_to_maestro(package, pr.steps, pr.screens)
        shots = [s.screenshot for s in pr.screens if s.screenshot]
        self.last_screenshot = shots[-1] if shots else None

    def baseline_note(self) -> str:
        if self.baseline_ms is None or self.pr.profile_id == "baseline" or not self.pr.launch_ms:
            return ""
        return f" Baseline launch was {self.baseline_ms} ms ({self.pr.launch_ms / self.baseline_ms:.1f}x)."

    def evidence(self, *items: Evidence) -> list[Evidence]:
        out = list(items)
        if self.pr.logcat:
            out.append(Evidence(kind="logcat", ref=self.pr.logcat))
        if self.last_screenshot:
            out.append(Evidence(kind="screenshot", ref=self.last_screenshot))
        return out

    def make(
        self,
        rule_id: str,
        category: Category,
        title: str,
        severity: Severity,
        description: str,
        evidence: list[Evidence],
        cause: str,
        fix: str,
        journey_step: int | None = None,
        repro: list[str] | None = None,
    ) -> Finding:
        n = self.counts.get(rule_id, 0) + 1
        self.counts[rule_id] = n
        if not evidence:
            evidence = [Evidence(kind="note", excerpt=f"{rule_id} on profile {self.pr.profile_id}")]
        return Finding(
            id=finding_id(self.run_id, rule_id, n),
            run_id=self.run_id,
            source="runtime",
            category=category,
            rule_id=rule_id,
            title=title,
            severity=severity,
            description=description,
            evidence=evidence,
            repro_steps=repro if repro is not None else self.steps,
            repro_flow=self.flow,
            affected_journey=JOURNEY,
            journey_step=journey_step,
            profile_id=self.pr.profile_id,
            probable_cause=cause,
            suggested_fix=fix,
        )


def _crash_step(pr: HarnessProfileResult) -> int:
    failed = [s.index for s in pr.steps if not s.ok]
    if failed:
        return failed[0]
    return pr.steps[-1].index if pr.steps else 0


def _crash_findings(ctx: _Ctx) -> list[Finding]:
    out: list[Finding] = []
    for crash in ctx.pr.crashes:
        out.append(_crash(ctx, crash))
    return out


def _crash(ctx: _Ctx, crash: HarnessCrash) -> Finding:
    step = _crash_step(ctx.pr)
    ev = ctx.evidence(Evidence(kind="logcat", excerpt=crash.excerpt[:1500]))
    if crash.type == "anr":
        return ctx.make(
            "rt.anr", "reliability", "App Not Responding (ANR)", "critical",
            f"The app stopped responding on profile '{ctx.pr.profile_id}'.", ev,
            "Blocking work (network, disk, locks) on the main thread.",
            "Move I/O off the main thread (coroutines/executors) and show progress states.",
            step,
        )
    label = "Native crash" if crash.type == "native_crash" else "App crash"
    return ctx.make(
        "rt.crash", "reliability", f"{label} on {ctx.pr.profile_id}", "critical",
        f"The app crashed on profile '{ctx.pr.profile_id}'.", ev,
        "Unhandled exception, often from missing null/error handling under constrained conditions.",
        "Reproduce with the flow, fix the stack trace's root cause and add error handling.",
        step,
    )


def _profile_findings(
    run_id: str, pr: HarnessProfileResult, package: str, counts: dict[str, int], baseline_ms: int | None
) -> list[Finding]:
    ctx = _Ctx(run_id, pr, package, counts, baseline_ms)
    if not pr.applied:
        note = pr.apply_note or "Profile could not be applied."
        profile = PROFILE_BY_ID[pr.profile_id]
        category: Category = "network" if "network" in pr.profile_id else "reliability"
        if pr.profile_id == "low_storage":
            category = "storage"
        elif pr.profile_id == "budget_2gb":
            category = "memory"
        return [
            ctx.make(
                "rt.profile_not_applied", category, f"Profile not applied: {profile.name}", "low",
                f"This condition did not run. {note}",
                [Evidence(kind="note", excerpt=note)],
                "The harness could not set up this condition.",
                "Re-run, or test this condition on a physical device.",
                repro=[f"Profile '{pr.profile_id}' was not applied."],
            )
        ]

    out: list[Finding] = []
    if not pr.launched:
        out.append(
            ctx.make(
                "rt.launch_failed", "reliability", f"App failed to launch on {pr.profile_id}", "critical",
                "The app did not reach a foreground activity.",
                ctx.evidence(Evidence(kind="note", excerpt=pr.apply_note or "launched=false")),
                "Crash or hang during startup, or missing/incompatible components.",
                "Check logcat for startup exceptions; test on the target API levels.",
                0,
            )
        )
    out.extend(_crash_findings(ctx))

    if pr.launch_ms is not None and pr.launch_ms > 2000:
        severity: Severity = "high" if pr.launch_ms > 5000 else "medium"
        out.append(
            ctx.make(
                "rt.slow_launch", "performance", f"Slow launch ({pr.launch_ms} ms) on {pr.profile_id}",
                severity,
                f"Cold start took {pr.launch_ms} ms on profile '{pr.profile_id}'." + ctx.baseline_note(),
                ctx.evidence(Evidence(kind="metric", excerpt=f"launch_ms={pr.launch_ms}")),
                "Heavy work in Application.onCreate or the first activity.",
                "Defer initialisation, use baseline profiles and a splash screen, avoid startup network calls.",
                0,
            )
        )
    if pr.network_errors:
        kinds = list(dict.fromkeys(e.split(":", 1)[0].strip() for e in pr.network_errors))
        out.append(
            ctx.make(
                "rt.network_errors", "network", f"Network errors on {pr.profile_id}: {', '.join(kinds)}",
                "high",
                "Network calls failed under this condition: " + "; ".join(pr.network_errors[:5]),
                ctx.evidence(Evidence(kind="logcat", excerpt="\n".join(pr.network_errors[:10]))),
                "Requests without timeout/retry; no offline handling.",
                "Add OkHttp timeouts + retry with backoff + offline state.",
            )
        )
    if pr.stuck_loading:
        out.append(
            ctx.make(
                "rt.stuck_loading", "network", f"Stuck on loading screen on {pr.profile_id}", "high",
                "The same screen showed a progress indicator for 15 s or more.",
                ctx.evidence(Evidence(kind="note", excerpt="stuck_loading=true (>=15 s)")),
                "No timeout or error state for slow or failed requests.",
                "Add request timeouts, an error/retry state and cached content.",
            )
        )
    if pr.state_lost_after_restore is True:
        out.append(
            ctx.make(
                "rt.state_lost", "reliability", "State lost after process death", "high",
                "After the system killed the app and it was restored, the user's UI state was lost.",
                ctx.evidence(Evidence(kind="note", excerpt="state_lost_after_restore=true")),
                "State held only in memory; onSaveInstanceState / SavedStateHandle not used.",
                "Persist UI state with SavedStateHandle/rememberSaveable and restore it on recreate.",
            )
        )
    if pr.profile_id == "budget_2gb" and pr.memory_pss_kb is not None and pr.memory_pss_kb > 300_000:
        out.append(
            ctx.make(
                "rt.memory_high", "memory", f"High memory use ({pr.memory_pss_kb // 1024} MB PSS)", "medium",
                "PSS exceeds 300 MB on a 2 GB device, risking low-memory kills.",
                ctx.evidence(Evidence(kind="metric", excerpt=f"memory_pss_kb={pr.memory_pss_kb}")),
                "Large bitmaps, unbounded caches or leaks.",
                "Downscale images, bound caches, profile with the Android Studio memory profiler.",
            )
        )
    return out


def runtime_findings(run_id: str, result: HarnessResult, package: str = _PACKAGE_PLACEHOLDER) -> list[Finding]:
    baseline = next((p.launch_ms for p in result.profiles if p.profile_id == "baseline" and p.launch_ms), None)
    counts: dict[str, int] = {}
    return [f for pr in result.profiles for f in _profile_findings(run_id, pr, package, counts, baseline)]
