# f19 - Deterministic test planner

**Status:** Built (merged to main) | **Written after build (retro-spec)** | **Commits:** 08226cc, e854931

> This spec was written after the code, from the code and git history, on 2026-11-22. It records what exists, not
> what was planned. Anything not listed under Verified is not verified.

## What it does
A rule-based planner chooses which profiles to run and why, from the APK's permissions and size (initial) or from the previous run's findings (follow-up). Exposed as the `plan_tests` and `start_planned_test` tools.

## Owned files
`api/app/planner.py`, `api/app/voice/tools.py`, `api/tests/test_planner.py`, `api/tests/voice/test_planner_tools.py`

## Behaviour and invariants
- No LLM in the planner; every plan item carries a reason string the agent must quote, not invent.
- A follow-up with nothing left to cover returns an empty plan with a note.

## Tests
`api/tests/test_planner.py` (12), `api/tests/voice/test_planner_tools.py` (6).

## Verified / not verified
Verified: unit tests. Not measured: whether the plans find more issues than the defaults.

## Status Log
- 2026-11-22 - retro-spec written; code and tests were already merged.
