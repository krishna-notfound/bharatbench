# f22 - Crawler v2: forms and change-detection settle

**Status:** Built (merged to main) | **Written after build (retro-spec)** | **Commits:** 8fa4f29, 40d9cf1

> This spec was written after the code, from the code and git history, on 2026-11-22. It records what exists, not
> what was planned. Anything not listed under Verified is not verified.

## What it does
The journey fills visible form fields (fake values, or the optional test account) once, submits, hides the keyboard, and waits for the UI to change instead of sleeping a fixed time.

## Owned files
`harness/harness/{crawler,forms}.py`, `harness/harness/parsers.py`, `harness/tests/test_forms.py`, `harness/tests/test_crawler.py`

## Behaviour and invariants
- A denylisted label (`parsers.DENYLIST`) is never tapped, including submit buttons.
- Fields are not refilled on the next iteration; secret values are masked in logs.
- An unchanged screen reuses the last screenshot and foreground check.

## Tests
`harness/tests/test_forms.py` (11), `test_crawler.py` (8).

## Verified / not verified
Verified: unit tests with a mock adb. Observed live: a 2-condition run went from 204 s to 167 s (see `docs/METRICS.md`; single observation).

## Status Log
- 2026-11-22 - retro-spec written; code and tests were already merged.
