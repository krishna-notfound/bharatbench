from __future__ import annotations

from datetime import UTC, datetime

from app.models import AppInfo, Finding, ProfileId, Run, RunSummary
from app.planner import plan_followup, plan_initial

NOW = datetime(2026, 11, 21, tzinfo=UTC)


def app(perms: list[str] | None = None, **kw) -> AppInfo:
    return AppInfo(package_name="x.y", size_bytes=kw.pop("size_bytes", 5_000_000), permissions=perms or [], **kw)


def run(profiles: list[ProfileId], executed: bool = True, reason: str | None = None) -> Run:
    return Run(
        id="r1", apk_name="a.apk", status="done", profile_ids=profiles, created_at=NOW, updated_at=NOW,
        summary=RunSummary(runtime_executed=executed, runtime_skipped_reason=reason),
    )


def fnd(fid: str, rule: str, profile: ProfileId | None = None, source: str = "runtime") -> Finding:
    return Finding(
        id=fid, run_id="r1", source=source, category="reliability", rule_id=rule,  # type: ignore[arg-type]
        title="t", severity="high", description="d", profile_id=profile,
    )


def test_initial_minimal_app_is_baseline_only() -> None:
    p = plan_initial(app(), [])
    assert p.profiles == ["baseline"] and p.journey_steps == 8
    assert p.reasons[0].profile == "baseline"


def test_initial_internet() -> None:
    p = plan_initial(app(["android.permission.INTERNET"]), [])
    assert p.profiles == ["baseline", "flaky_network", "budget_2gb"]
    assert "network" in p.reasons[1].why


def test_initial_heavy_adds_budget_without_internet() -> None:
    p = plan_initial(app(size_bytes=50 * 1024 * 1024, native_abis=["a", "b", "c"]), [])
    assert "budget_2gb" in p.profiles and "flaky_network" not in p.profiles
    assert "large APK" in p.reasons[1].why and "3 native ABIs" in p.reasons[1].why


def test_initial_storage_battery() -> None:
    p = plan_initial(app(["android.permission.WRITE_EXTERNAL_STORAGE", "android.permission.WAKE_LOCK"]), [])
    assert "low_storage" in p.profiles and "battery_saver" in p.profiles
    p2 = plan_initial(app(["android.permission.READ_MEDIA_IMAGES", "android.permission.ACCESS_FINE_LOCATION"]), [])
    assert "low_storage" in p2.profiles and "battery_saver" in p2.profiles


def test_initial_complex_app_gets_process_death_and_12_steps() -> None:
    p = plan_initial(app(dex_count=3), [fnd("s1", "sec.debuggable", source="static")])
    assert "process_death" in p.profiles and p.journey_steps == 12
    assert p.note and "1 static" in p.note


def test_followup_crash_on_profile_reruns_with_baseline() -> None:
    p = plan_followup(run(["baseline", "budget_2gb"]), [fnd("f1", "rt.crash", "budget_2gb")])
    assert p.profiles == ["budget_2gb", "baseline"] and p.journey_steps == 16
    assert all("f1" in r.why for r in p.reasons)


def test_followup_anr_on_baseline() -> None:
    p = plan_followup(run(["baseline"]), [fnd("f2", "rt.anr", "baseline")])
    assert p.profiles == ["baseline"] and p.journey_steps == 16


def test_followup_network_problems() -> None:
    p = plan_followup(run(["baseline"]), [fnd("f3", "rt.stuck_loading", "flaky_network")])
    assert p.profiles == ["flaky_network", "budget_2gb"] and p.journey_steps == 16
    assert "f3" in p.reasons[0].why


def test_followup_state_lost_and_memory() -> None:
    p = plan_followup(run(["baseline"]), [fnd("f4", "rt.state_lost", "process_death"), fnd("f5", "rt.memory_high", "budget_2gb")])
    assert set(p.profiles) == {"process_death", "budget_2gb"} and p.journey_steps == 16


def test_followup_profile_not_applied_retries_with_default_steps() -> None:
    p = plan_followup(run(["baseline", "low_storage"]), [fnd("f6", "rt.profile_not_applied", "low_storage"), fnd("f7", "rt.slow_launch", "baseline")])
    assert "low_storage" in p.profiles
    assert p.journey_steps == 8


def test_followup_nothing_found_covers_uncovered_profiles() -> None:
    p = plan_followup(run(["baseline", "flaky_network"]), [fnd("s1", "sec.x", source="static")])
    assert p.profiles == ["budget_2gb", "low_storage", "battery_saver", "process_death"]
    assert p.journey_steps == 16


def test_followup_runtime_not_executed_retries_same_profiles() -> None:
    p = plan_followup(run(["baseline"], executed=False, reason="harness down"), [])
    assert p.profiles == ["baseline"] and "harness down" in p.reasons[0].why


def test_followup_everything_covered_is_empty_with_note() -> None:
    every: list[ProfileId] = ["baseline", "budget_2gb", "flaky_network", "low_storage", "battery_saver", "process_death"]
    p = plan_followup(run(every), [])
    assert p.profiles == [] and p.note
