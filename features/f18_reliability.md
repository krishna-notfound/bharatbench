# f18 - Reliability: watchdog, recovery, self-heal

**Status:** Built (merged to main) | **Written after build (retro-spec)** | **Commits:** 4cb2ec8, 7f23e35

> This spec was written after the code, from the code and git history, on 2026-11-22. It records what exists, not
> what was planned. Anything not listed under Verified is not verified.

## What it does
Runs always end. The API watchdog ends a stalled run (4 min without progress) or one over its 15 min runtime budget, keeping partial results. A sweeper ends wedged runs after 25 min. The harness checks device and disk health before a job, repairs the device (adb reconnect, `docker restart redroid`, purge old jobs), retries a profile once after an adb drop, and deletes jobs after download.

## Owned files
`api/app/{pipeline,services,harness_client}.py`, `harness/harness/{heal,jobs,main}.py`, `api/tests/test_reliability.py`, `harness/tests/test_heal.py`

## Behaviour and invariants
- Runtime is skipped with a human reason when the harness is unhealthy, busy or low on disk; static results are kept.
- Disk: API skips under 400 MB free; harness repairs under 600 MB and refuses under 300 MB.
- `/health` reports `device_status`, `last_repair`, `disk_free_mb` (contract section 4).

## Tests
`api/tests/test_reliability.py` (13 tests), `harness/tests/test_heal.py` (15 tests).

## Verified / not verified
Verified: unit tests with fakes. Not verified: self-repair on a genuinely wedged redroid container.

## Status Log
- 2026-11-22 - retro-spec written; code and tests were already merged.
