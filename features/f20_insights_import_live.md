# f20 - Insights, GitHub import, live phone and replay

**Status:** Built (merged to main) | **Written after build (retro-spec)** | **Commits:** 319c47f, 5147b47, 7609643, 0575327, 52756ff, b7d64c4, 2f87a63

> This spec was written after the code, from the code and git history, on 2026-11-22. It records what exists, not
> what was planned. Anything not listed under Verified is not verified.

## What it does
(1) Lab-based Play Store risk, comparison with the previous run, and a spoken team brief. (2) Import the latest release APK from a public GitHub repo (nothing is built from source). (3) Live phone view (about 1 fps latest frame with tap ripple and captions) and post-run step replay.

## Owned files
`api/app/{insights,github_import,live}.py`, `api/app/routes/{insights,imports,live}.py`, `harness/harness/live.py`, `api/tests/{test_insights,test_github_import,test_live}.py`, `harness/tests/test_live.py`, contract sections 7 and 8

## Behaviour and invariants
- The Play card never claims a real-user rate; it says what the lab observed and quotes Google Play's thresholds.
- GitHub import: ZIP magic check, 200 MB cap, `.aab` never used, token sent to GitHub only.
- Only the latest live frame is kept in memory; frames exist only while a job runs.

## Tests
`api/tests/test_insights.py` (12), `test_github_import.py`, `test_live.py` (6), `harness/tests/test_live.py` (4).

## Verified / not verified
Verified: unit tests with respx and mocks. Not verified: GitHub rate-limit behaviour live; live frame rate on a loaded device.

## Status Log
- 2026-11-22 - retro-spec written; code and tests were already merged.
