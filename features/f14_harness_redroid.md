# f14 - Harness on redroid

**Status:** Built (merged to main) | **Written after build (retro-spec)** | **Commits:** eb021d4, 59adf4d, 54b07b1

> This spec was written after the code, from the code and git history, on 2026-11-22. It records what exists, not
> what was planned. Anything not listed under Verified is not verified.

## What it does
Moves the device from an Android emulator (needs KVM) to a redroid Android 12 container driven over adb at `127.0.0.1:5555`. Conditions are applied with `docker --memory`, `tc netem` on the container's host-side veth, and adb for battery and process death. The emulator path remains as `DEVICE_KIND=emulator` (optional, legacy).

## Owned files
`harness/harness/{adb,profiles,settings}.py`, `harness/scripts/`, `deploy/setup_harness_ec2.sh`, `deploy/bharatbench-harness.service`, `harness/tests/test_adb_profiles.py`

## Behaviour and invariants
- budget_2gb: 2 GB container memory cap plus netem (download 2 Mbit/s, 200 ms delay with 100 ms jitter, upload policed). CPU is not throttled.
- flaky_network: netem `loss 100%` 6 s on, 4 s off.
- low_storage is refused on redroid (shared host disk) and reported as not applied.
- `tc` runs via `sudo -n` with a NOPASSWD drop-in for `/usr/sbin/tc` only; every profile change is reverted in `try/finally`.
- A failed `tc` makes the condition `not applied`, never silently applied.

## Tests
`harness/tests/test_adb_profiles.py` (18 tests with a mock runner, including `test_redroid_budget_netem_and_revert`, `test_redroid_low_storage_refused`, `test_redroid_missing_veth_fails_fast`).

## Verified / not verified
Verified: unit tests with a mocked adb/tc runner. Observed on the deployed host: runs completed (see `docs/METRICS.md`). Not verified: the exact effect of battery saver on redroid.

## Status Log
- 2026-11-22 - retro-spec written; code and tests were already merged.
