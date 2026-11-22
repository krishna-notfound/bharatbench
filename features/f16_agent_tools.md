# f16 - Agent tools for reports and follow-ups

**Status:** Built (merged to main) | **Written after build (retro-spec)** | **Commits:** b61ca11, 20fedb0

> This spec was written after the code, from the code and git history, on 2026-11-22. It records what exists, not
> what was planned. Anything not listed under Verified is not verified.

## What it does
Adds agent tools beyond the original seven: `get_report`, `suggest_improvements`, `run_deeper_tests`, `get_finding_evidence`, `compare_runs`.

## Owned files
`api/app/voice/tools.py`, `api/app/voice/prompts.py`, `api/tests/voice/test_agent_tools_f16.py`

## Behaviour and invariants
- Results are built only from stored findings; the agent may not describe screenshot pixels, only that one exists.
- `run_deeper_tests` returns a new run id immediately (async job pattern).
- Failures are returned as `{error}` for the LLM to report, never raised.

## Tests
`api/tests/voice/test_agent_tools_f16.py` (10 tests).

## Verified / not verified
Verified: unit tests with an in-memory service. Not measured: how well the LLM uses the tools.

## Status Log
- 2026-11-22 - retro-spec written; code and tests were already merged.
