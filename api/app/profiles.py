"""Frozen condition profiles. Fidelity is stated honestly; `how` is shown to users verbatim.

users_exposed values are adjustable ASSUMPTIONS (share of Indian target users facing the condition),
not measured data. They are surfaced in the UI and report as assumptions.
"""

from app.models import Profile

PROFILES: list[Profile] = [
    Profile(
        id="baseline",
        name="Baseline",
        description="Default emulator, normal network. Reference run for comparison.",
        fidelity="controlled",
        how="Emulator with 2 GB RAM, no network shaping.",
        users_exposed=1.0,
    ),
    Profile(
        id="budget_2gb",
        name="Budget phone, 2 Mbps",
        description="Entry-level 2 GB RAM device on a slow ~2 Mbps mobile network with high latency.",
        fidelity="approximated",
        how="AVD hw.ramSize=2048; emulator console `network speed 2000:2000` (kbps) and "
        "`network delay 200:600` (ms). Host CPU is not throttled, so CPU slowness is NOT simulated.",
        users_exposed=0.45,
    ),
    Profile(
        id="flaky_network",
        name="Intermittent network",
        description="Connectivity drops for a few seconds repeatedly during the journey.",
        fidelity="controlled",
        how="`adb shell svc data disable|enable` and `svc wifi disable|enable` toggled: 6 s off every 10 s "
        "during the journey.",
        users_exposed=0.6,
    ),
    Profile(
        id="low_storage",
        name="Low storage (~400 MB free)",
        description="Device storage nearly full.",
        fidelity="controlled",
        how="Filler file written to /data/local/tmp until `df /data` shows ~400 MB free; removed after.",
        users_exposed=0.35,
    ),
    Profile(
        id="battery_saver",
        name="Battery saver",
        description="Battery at 10% with system battery saver on (background restrictions).",
        fidelity="approximated",
        how="`dumpsys battery unplug`, `dumpsys battery set level 10`, `settings put global low_power 1`; "
        "reset after. OEM-specific aggressive killers are NOT simulated.",
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
    "thermal_throttling": "Not simulated: emulator runs on server CPUs; needs physical hardware.",
    "slow_cpu": "Not simulated: emulator CPU is not throttled to entry-level SoC speed.",
    "oem_background_killers": "Not simulated: vendor-specific (Xiaomi/Oppo/Vivo) task killers need real devices.",
}

PROFILE_BY_ID = {p.id: p for p in PROFILES}
