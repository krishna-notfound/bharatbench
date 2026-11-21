# BharatBench Prototype Implementation Plan

> **For agentic workers:** Execute your assigned feature file task-by-task (checkbox syntax). Parallel
> agents in git worktrees; orchestrator merges.

**Goal:** Working end-to-end BharatBench prototype (upload → static scan → EC2 emulator runtime → ranked report → voice agent).

**Architecture:** Monorepo. `web/` Next.js talks only to `api/` FastAPI. `api/` runs the pipeline, analyzer, scoring, report and Sarvam voice agent. `harness/` FastAPI on EC2 drives emulator via ADB, reached through an SSH tunnel.

**Tech Stack:** Next.js 16.4 / React 19.3 / Tailwind 4.3 / shadcn (Base UI) · Python 3.12+ / FastAPI / pydantic v2 / uv / aiosqlite / androguard / httpx · Sarvam · Android emulator / ADB / Maestro.

**Spec:** `docs/superpowers/specs/2026-11-21-bharatbench-prototype-design.md` + `features/f02..f06` + `contracts/README.md`.

## Global Constraints

- Contracts frozen: `api/app/models.py`, `api/app/profiles.py`, `contracts/README.md`, `web/lib/types.ts`.
- No fabricated results; harness unavailable ⇒ runtime skipped with reason.
- Subprocess: arg lists, no shell, timeouts. Harness binds 127.0.0.1, `X-Harness-Token` required.
- UI tokens only (`context/ui-context.md`); `web/components/ui/**` protected.
- APK ≤ 200 MB, `.apk` only. Scoring: `score = 100 × users_exposed × severity_weight × flow_usage`, weights critical 1.0 / high 0.7 / medium 0.4 / low 0.15.

## Review Focus

1. A huge or corrupt APK upload — expect 413/400 or run `failed` with a clear error, never a hung `analyzing` run (f02 test: corrupt bytes named `.apk` → run ends `failed`).
2. Harness unreachable mid-run — run ends `done` with static findings + skipped reason, not `failed` (f02 pipeline test with harness raising `httpx.ConnectError`).
3. A profile revert failing (network left throttled / filler file left) — next profile must still start clean (f04 test: revert raises → job continues, event recorded).
4. WS client connecting after the run finished — receives full history then `done` (f02 ws test).
5. User interrupts the voice agent during a tool call — turn cancelled, no orphan TTS audio sent after `turn_end` (f05 test).

## Tasks (one agent each, parallel)

| Task | Feature file | Agent | Branch |
| ---- | ------------ | ----- | ------ |
| 1 | `features/f02_api_core.md` | Sonnet `api-core` | `feat/f02-api-core` |
| 2 | `features/f03_analyzer.md` | Sonnet `analyzer` | `feat/f03-analyzer` |
| 3 | `features/f04_harness.md` | Sonnet `harness` | `feat/f04-harness` |
| 4 | `features/f05_voice_agent.md` | Sonnet `voice` | `feat/f05-voice` |
| 5 | `features/f06_web_ui.md` | Sonnet `web` | `feat/f06-web` |
| 6 | Integration (orchestrator) | Opus | `main` |

Each feature file's *Tasks*, *Acceptance Criteria*, and *Verification* sections are the step list; TDD for
pure logic (storage, scoring, rules, parsers, tool dispatch). Each agent commits on its branch with messages
`feat(fNN): ...`. Review Focus items 1–5 are added as tests in tasks 1, 1, 3, 1, 4 respectively.

Task 6 (orchestrator): merge branches in order f03 → f02 → f04 → f06 → f05; run `uv run pytest -q` in api and
harness, `npm run lint && npx tsc --noEmit && npm run build` in web; start api + web, upload a real APK,
confirm static findings render; then EC2 setup + tunnel + runtime run when user provides the host.
