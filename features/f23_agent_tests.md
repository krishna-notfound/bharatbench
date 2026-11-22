# f23 - Agent-written tests and optional test account

**Status:** Built (merged to main) | **Written after build (retro-spec)** | **Commits:** 9ade077, 812231b, 8963b29, 1512342

> This spec was written after the code, from the code and git history, on 2026-11-22. It records what exists, not
> what was planned. Anything not listed under Verified is not verified.

## What it does
The voice agent can write app-specific UI tests from the user's words (`write_custom_tests`). The harness drives them with an LLM that sees the visible UI nodes and answers one action at a time. A failed test becomes a finding. An optional test account is held in memory, masked everywhere, tokenised for the LLM, and can trigger an offline-after-login phase.

## Owned files
`api/app/agent_tests.py`, `api/app/analyzer/rules_agent.py`, `api/app/voice/tools.py`, `harness/harness/{agent,secrets,jobs}.py`, `api/tests/test_agent_tests*.py`, `api/tests/test_credentials.py`, `api/tests/voice/test_custom_tests_tool.py`, `harness/tests/test_agent.py`, `harness/tests/test_credentials.py`

## Behaviour and invariants
- Default runs send no agent tests; only `write_custom_tests` creates them.
- `low_storage` is excluded (not applicable on redroid).
- Credentials: never stored or logged; the LLM sees tokens, the password is substituted at input time.
- No LLM key on the harness: agent tests are skipped with a note.

## Tests
api: `test_agent_tests.py` (7), `test_agent_tests_pipeline.py` (2), `test_credentials.py` (3), `voice/test_custom_tests_tool.py` (4). harness: `test_agent.py` (5), `test_credentials.py` (5).

## Verified / not verified
Verified: unit tests with mocked LLM and device. Not measured: pass/fail accuracy of the LLM driver on real apps.

## Status Log
- 2026-11-22 - retro-spec written; code and tests were already merged.
