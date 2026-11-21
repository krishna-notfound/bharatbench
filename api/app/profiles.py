"""Frozen condition profiles. Fidelity is stated honestly; `how` is shown to users verbatim.

users_exposed values are adjustable ASSUMPTIONS (share of Indian target users facing the condition),
not measured data. They are surfaced in the UI and report as assumptions.
"""

from app.models import Profile

PROFILES: list[Profile] = [
    Profile(
        id="baseline",
        name="Baseline",
        description="Default redroid Android 12, normal network. Reference run for comparison.",
        fidelity="controlled",
        how="Android 12 (redroid container) with a 2 GB memory cap, no network shaping.",
        users_exposed=1.0,
    ),
    Profile(
        id="budget_2gb",
        name="Budget phone, 2 Mbps",
        description="Entry-level 2 GB RAM device on a slow ~2 Mbps mobile network with high latency.",
        fidelity="approximated",
        how="Container memory capped at 2 GB (docker --memory, cgroup OOM kills); Linux `tc netem` on the "
        "container's network link: download 2 Mbit/s with 200 ms delay (100 ms jitter), upload policed to "
        "2 Mbit/s. Host CPU is not throttled, so CPU slowness is NOT simulated.",
        users_exposed=0.45,
    ),
    Profile(
        id="flaky_network",
        name="Intermittent network",
        description="Connectivity drops for a few seconds repeatedly during the journey.",
        fidelity="controlled",
        how="`tc netem loss 100%` on the container's network link for 6 s, removed for 4 s, repeating "
        "during the journey (Wi-Fi/mobile-data toggles do not cut connectivity on redroid).",
        users_exposed=0.6,
    ),
    Profile(
        id="low_storage",
        name="Low storage (~400 MB free)",
        description="Device storage nearly full.",
        fidelity="controlled",
        how="Filler file written to /data/local/tmp until `df /data` shows ~400 MB free; removed after. "
        "NOT applied on redroid: its /data is the shared host disk, so the condition is reported as not applied.",
        users_exposed=0.35,
    ),
    Profile(
        id="battery_saver",
        name="Battery saver",
        description="Battery at 10% with system battery saver on (background restrictions).",
        fidelity="approximated",
        how="`dumpsys battery unplug`, `dumpsys battery set level 10`, `settings put global low_power 1`; "
        "reset after. The system battery-saver effect on redroid is unverified; OEM-specific aggressive "
        "killers are NOT simulated.",
        users_exposed=0.3,
    ),
    Profile(
        id="process_death",
        name="Process death & restore",
        description="App is backgrounded, killed by the system, then restored from recents.",
        fidelity="controlled",
        how="Press HOME, `am kill <package>`, relaunch; compare UI before/after for lost state.",
        users_exposed=0.5,
    ),
]

UNSUPPORTED_CONDITIONS: dict[str, str] = {
    "thermal_throttling": "Not simulated: the Android container runs on server CPUs; needs physical hardware.",
    "slow_cpu": "Not simulated: container CPU is not throttled to entry-level SoC speed.",
    "oem_background_killers": "Not simulated: vendor-specific (Xiaomi/Oppo/Vivo) task killers need real devices.",
}

PROFILE_BY_ID = {p.id: p for p in PROFILES}
