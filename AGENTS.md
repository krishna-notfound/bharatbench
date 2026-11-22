# AGENTS.md - orientation for automated reviewers and coding agents

Purpose (3 lines). BharatBench takes an Android APK, scans it statically, then runs it on a real Android 12 phone
(redroid container) under constrained conditions (memory cap, slow or flaky network, battery saver, process death),
and returns findings ranked by estimated user impact, with evidence. A voice agent (Sarvam STT, LLM, TTS) starts
tests and explains results. If the device lab is unreachable, runtime is reported as skipped, never simulated.

Rule: **code beats docs when they conflict.** Docs here were checked against the code when written; if a pointer
is stale, trust the code and report the mismatch. `CLAUDE.md` is the contributor workflow file for the Claude Code
CLI; this file is the reviewer map.

## Reading order (15 minutes)

1. `README.md` - overview, fidelity table, architecture diagram.
2. `docs/EVALUATION.md` - every claim -> file:line -> test -> how to verify.
3. `docs/FEATURE_MAP.md` - f02-f23 -> code -> tests -> status.
4. `contracts/README.md` and `contracts/v2-voice-and-users.md` - frozen API, WebSocket, harness and voice contracts.
5. `api/app/models.py`, `api/app/profiles.py` - data model and condition profiles (with fidelity labels).
6. `docs/PROMPTS.md`, `docs/CONFIG.md`, `docs/LIMITATIONS.md`, `docs/TESTING.md`, `docs/METRICS.md`.
7. `llms.txt` - one-line index of the above.

## Repo map (path level)

| Path | What is there |
| :--- | :--- |
| `api/app/` | FastAPI service: `main.py` (wiring), `pipeline.py`, `services.py`, `scoring.py`, `report.py`, `planner.py`, `agent_tests.py`, `insights.py`, `live.py`, `github_import.py`, `harness_client.py`, `settings.py` |
| `api/app/analyzer/` | Static APK rules (`rules_security.py`, `rules_performance.py`, `apk.py`), runtime rules (`rules_runtime.py`, `rules_agent.py`), `dedupe.py`, `explain.py`, `maestro.py` |
| `api/app/voice/` | REST-era voice agent: `prompts.py`, `agent.py`, `tools.py` (tool schemas and dispatch), Sarvam STT/TTS/LLM clients, `languages.py` |
| `api/app/realtime/` | Streaming voice (`WS /ws/realtime`): `session.py`, `turns.py`, `interruptions.py`, `providers.py`, `registry.py`, `router.py` |
| `api/app/auth/`, `api/app/conversations/` | Supabase JWT verification; conversation store |
| `api/app/storage/` | One `Storage` interface; SQLite (default) and Supabase implementations |
| `api/app/routes/` | HTTP and WebSocket routes |
| `api/tests/` | pytest suite (see `docs/TESTING.md`) |
| `harness/harness/` | Device-host service: `main.py` (HTTP), `jobs.py` (job runner), `adb.py`, `profiles.py`, `crawler.py`, `forms.py`, `agent.py`, `security.py`, `heal.py`, `live.py`, `evidence.py`, `secrets.py`, `parsers.py` |
| `harness/tests/` | pytest suite with a mocked adb |
| `web/` | Next.js app (no unit tests; CI runs lint, tsc, build) |
| `contracts/`, `context/`, `features/`, `docs/` | frozen contracts, project context, one spec per feature, evaluator docs |
| `deploy/` | Caddyfile, systemd units, EC2 setup and deploy scripts |
| `supabase/migrations/` | Postgres schema and RLS policies |
| `.github/workflows/ci-cd.yml` | CI (ruff, pytest, web lint/tsc/build) and API deploy on push to `main` |

## Where is X

| Topic | Location |
| :--- | :--- |
| Run pipeline (static -> harness -> score -> done) | `api/app/pipeline.py` (`run_pipeline`); lifecycle in `api/app/services.py` |
| Harness driver (job runner, profile apply and revert) | `harness/harness/jobs.py`, `harness/harness/profiles.py`, `harness/harness/adb.py` |
| Crawler (journey, forms, settle) | `harness/harness/crawler.py`, `harness/harness/forms.py`, `harness/harness/parsers.py` |
| Security checks, static | `api/app/analyzer/rules_security.py` |
| Security checks, dynamic (cleartext capture, exported-component probes, debuggable) | `harness/harness/security.py` |
| Live phone view and replay | `harness/harness/live.py`, `api/app/routes/live.py`, `api/app/live.py` |
| Agent tools (voice agent -> API) | `api/app/voice/tools.py` (`TOOL_SCHEMAS`, 13 tools), `api/app/realtime/registry.py` |
| Agent-written tests | `api/app/agent_tests.py`, `harness/harness/agent.py`, `api/app/analyzer/rules_agent.py` |
| LLM prompts | `docs/PROMPTS.md` (index with file:line) |
| Realtime voice | server `api/app/realtime/` (route in `router.py`), client `web/lib/realtime/` |
| Storage | `api/app/storage/`; schema in `supabase/migrations/` |
| Auth | `api/app/auth/supabase.py`; enforcement flag `AUTH_REQUIRED` (default off); web in `web/lib/supabase/` |
| Deploy | `deploy/deploy_api.sh`, `deploy/*.service`, `deploy/setup_*.sh`, `docs/SETUP.md` |
| CI | `.github/workflows/ci-cd.yml` |
| Scoring and fidelity labels | `api/app/scoring.py`, `api/app/profiles.py` |
| Environment variables | `docs/CONFIG.md`, `api/.env.example`, `harness/.env.example`, `web/.env.example` |

## Verify in 5 minutes, offline

No device, API keys or network are needed for the Python suites (harness tests mock adb; API tests mock the
harness and the LLM).

```bash
cd api     && uv sync && uv run pytest --collect-only -q | tail -1   # expect: 306 tests collected
cd api     && uv run pytest -q && uv run ruff check .                # expect: all pass, ruff clean
cd harness && uv sync && uv run pytest --collect-only -q | tail -1   # expect: 123 tests collected
cd harness && uv run pytest -q && uv run ruff check .                # expect: all pass, ruff clean
cd web     && npm ci && npm run lint && npx next typegen && npx tsc --noEmit && npm run build   # as in CI
```

Counts were taken when this file was written; if they differ, the suites changed, not the claim.
Not verifiable offline: runtime behaviour on a real device, live Sarvam calls, Supabase. See `docs/LIMITATIONS.md`.

## Conventions

- Names and shapes come from `api/app/models.py` (frozen) and `api/app/profiles.py` (frozen); the TypeScript mirror
  is `web/lib/types.ts`.
- Anything not measured is labelled "not measured" (`docs/METRICS.md`). Planned work is labelled planned.
