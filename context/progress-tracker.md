# Progress Tracker

Must describe the **actual** state of the repo.

## Current Phase

- Phase 1 — Prototype build (HackFront 2026). Contracts frozen; features f02–f06 being built in parallel.

## Current Goal

- End-to-end demo: upload APK → static findings → runtime on EC2 emulator → ranked report → voice agent explains.

## Completed

- 2026-11-21 — Context template filled; contracts frozen (`contracts/README.md`, `api/app/models.py`, `api/app/profiles.py`, `web/lib/types.ts`); Next.js + shadcn scaffold in `web/`.
- 2026-11-21 — Local dev machine: agent-device 0.21.41 + Claude Code MCP configured (no Android SDK locally).
- 2026-11-21 � f08 Supabase storage backend (`api/app/storage/supabase.py`, PostgREST via httpx, respx tests, live round-trip verified); not yet the default (`STORAGE_BACKEND` stays `sqlite`).

## In Progress

- f02 API core, f03 analyzer, f04 harness, f05 voice agent, f06 web UI (parallel Sonnet agents).

## Next Up

- Merge + integration; provision EC2 (user) and run `harness/scripts/setup_ec2.sh`; end-to-end demo with a sample APK.

## Open Questions

- [ ] EC2 instance IP / key — user will drop into `secrets/` (pending).
- [ ] Sarvam API key — pending from user.
- [ ] Demo APK(s): which apps do we show? Need one with a known crash/slow-network bug.
- [ ] Sarvam LLM tool-calling support/model id — verify in docs (f05).

## Architecture Decisions

- 2026-11-21 — Web app is Next.js (not Expo/React Native) — product is a web platform; emulator is backend infra.
- 2026-11-21 — APK upload is the only input; GitHub→Gradle build deferred — untrusted build scripts, toolchain variance, time.
- 2026-11-21 — SQLite + files behind `Storage` interface now; Supabase later — Supabase owned by teammate, connect later.
- 2026-11-21 — Harness is a separate FastAPI service on EC2, 127.0.0.1 + token, reached via SSH tunnel — no public ports.
- 2026-11-21 — Custom Python agent orchestrator (no framework) — 7 tools, needs cancellation + barge-in control.
- 2026-11-21 — Runtime is skipped (not faked) when harness unavailable — honesty invariant.
- 2026-11-21 — One emulator, one job at a time — hackathon scope.
- 2026-11-21 � Supabase storage via PostgREST + httpx (no new dependency), models stored as JSON in `data`, selected by `STORAGE_BACKEND` � SQLite stays default; APK files still local.

## Deferred Work

- GitHub repo → APK build — after demo; needs isolated build VM.
- Supabase Auth/DB/Storage — teammate; implement `storage/supabase.py`.
- Resend email on run completion — needs auth/user emails.
- Thermal / slow CPU / OEM killers — need physical devices.

## Session Notes

- Orchestrator = Opus, implementers = Sonnet in git worktrees. Repo root `C:\Users\krishna\Desktop\bharatbench`.
