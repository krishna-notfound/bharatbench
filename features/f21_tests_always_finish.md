# f21 - Tests always finish

**Status:** Built (merged to main) | **Written after build (retro-spec)** | **Commits:** b4c31f4

> This spec was written after the code, from the code and git history, on 2026-11-22. It records what exists, not
> what was planned. Anything not listed under Verified is not verified.

## What it does
A stop is graceful (the run finishes with results so far), runs interrupted by a server restart resume with the same id (max two resumes), failed or cancelled runs can be retried idempotently, and the deploy script waits for idle. The cancel voice tool and stop UI were removed.

## Owned files
`api/app/services.py`, `api/app/pipeline.py`, `api/app/routes/runs.py`, `deploy/deploy_api.sh`, `api/tests/test_resume.py`, `api/tests/test_pipeline.py`

## Behaviour and invariants
- Shutdown never rewrites in-progress runs; startup recovery resumes them.
- `POST /api/runs/{id}/cancel` is HTTP-only and graceful; no voice tool cancels.

## Tests
`api/tests/test_resume.py` (4), `test_pipeline.py::test_stop_*`, `test_reliability.py::test_stop_keeps_completed_conditions`, `api/tests/voice/test_voice_tools.py::test_cancel_run_tool_is_removed`.

## Verified / not verified
Verified: unit tests. Not verified: a real deploy against a running device test (the deploy script check is textual).

## Status Log
- 2026-11-22 - retro-spec written; code and tests were already merged.
