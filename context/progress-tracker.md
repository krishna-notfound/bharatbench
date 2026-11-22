# Progress Tracker

Must describe the **actual** state of the repo.

## Current Phase

- Phase 2 - Hardening and documentation (HackFront 2026). Features f02-f23 are merged to `main` (`docs/FEATURE_MAP.md`).
  Web on Vercel, API and harness on EC2 (redroid device), storage on Supabase, CI/CD green on `main`.

## Current Goal

- Keep `main` deployable; make the repo verifiable for reviewers (`AGENTS.md`, `docs/EVALUATION.md`).

## Completed

- 2026-11-21 - f01 context template; contracts frozen (`contracts/README.md`, `api/app/models.py`, `api/app/profiles.py`, `web/lib/types.ts`); Next.js + shadcn scaffold.
- 2026-11-21 - f02 API core, f03 analyzer, f04 harness, f05 voice agent, f06 web UI, f07 redesign merged.
- 2026-11-21 - f08 Supabase storage backend (`api/app/storage/supabase.py`); selected with `STORAGE_BACKEND=supabase`, SQLite stays the default.
- 2026-11-21 - Deployed: web on Vercel (https://bharatbench-orpin.vercel.app, root `web`, auto-deploy from `main`); API on EC2 behind Caddy HTTPS, systemd `bharatbench-api`.
- 2026-11-21 - CI/CD: `.github/workflows/ci-cd.yml` (api, harness, web checks on every push/PR; push to `main` deploys the API over SSH via `deploy/deploy_api.sh`).
- 2026-11-21 - f09 realtime voice, f10 users and conversations (Supabase guest/Google auth, `AUTH_REQUIRED` off by default), f11 orb, f12 grounded explanations and dedupe, f13 sign-in and onboarding.
- 2026-11-21/22 - f14 harness on redroid (device `127.0.0.1:5555`), f15 Oryn-parity voice engine and dynamic security checks, f16 agent tools, f17 multilingual agent.
- 2026-11-22 - f18 reliability (watchdog, recovery, self-heal), f19 deterministic planner, f20 Play risk/compare/brief, GitHub import, live phone and replay, f21 tests always finish (graceful stop, resume, retry), f22 crawler v2, f23 agent-written tests and optional test account.
- 2026-11-22 - Reviewer docs: `AGENTS.md`, `llms.txt`, `docs/{EVALUATION,FEATURE_MAP,PROMPTS,CONFIG,TESTING,METRICS,LIMITATIONS}.md`, retro-specs for features built without one.

## In Progress

- Nothing open on `main` at the time of writing. Check `git branch -r` and open pull requests for work in flight.

## Next Up

- Demo-APK selection and a recorded end-to-end run on the deployed stack.
- Planned, not started: see "Not built" in `docs/LIMITATIONS.md` (Resend emails, GitHub build from source, multi-device queue, physical-device conditions).

## Open Questions

- [ ] Demo APK(s): which apps do we show? One with a known crash or slow-network bug is wanted.
- [ ] Sarvam LLM tool-calling behaviour per model: realtime uses `LLM_MODEL` (`sarvam-105b`), the REST voice agent uses `SARVAM_CHAT_MODEL` (`sarvam-105b-conversations`). Is one model enough? (`docs/CONFIG.md`)
- [ ] Battery-saver effect on redroid is unverified (profile is labelled `approximated`).
- [ ] The Sarvam key was pasted in chat on 2026-11-21; rotate it after the hackathon.
- [x] EC2 instance and key: provisioned and in use.
- [x] Sarvam LLM tool calling: verified live (Hinglish text turn -> tools -> Hindi TTS, 2026-11-21).

## Architecture Decisions

- 2026-11-21 — Web app is Next.js (not Expo/React Native) — product is a web platform; emulator is backend infra.
- 2026-11-21 — APK upload is the only input; GitHub→Gradle build deferred — untrusted build scripts, toolchain variance, time.
- 2026-11-21 — SQLite + files behind `Storage` interface now; Supabase later — Supabase owned by teammate, connect later.
- 2026-11-21 — Harness is a separate FastAPI service on EC2, 127.0.0.1 + token, reached via SSH tunnel — no public ports.
- 2026-11-21 — Custom Python agent orchestrator (no framework) — 7 tools, needs cancellation + barge-in control.
- 2026-11-21 — Runtime is skipped (not faked) when harness unavailable — honesty invariant.
- 2026-11-21 — One device, one job at a time — hackathon scope. (2026-11-22: the device is a redroid container, not an emulator; see f14.)
- 2026-11-21 — Supabase storage via PostgREST + httpx (no new dependency), models stored as JSON in `data`, selected by `STORAGE_BACKEND` — SQLite stays default; APK files still local.

- 2026-11-22 — f18 reliability: API watchdog (4 min no progress / 15 min cap -> run ends `done`, runtime skipped with a human reason, partial profiles kept), startup recovery + 25 min stuck-run sweeper (`failed` with reason), harness health gate with self-repair (`harness/heal.py`: adb reconnect, `docker restart redroid`, purge old jobs, leftover app uninstall), per-profile reconnect+retry, `DELETE /jobs/{id}` after download, `/health` device_status/last_repair/disk_free_mb, API skips runtime when disk_free_mb < 400.

## Deferred Work

- GitHub repo → APK build — after demo; needs isolated build VM.
- Supabase Storage bucket for APKs/artifacts (DB and Auth are done; files still live under `DATA_DIR`).
- Resend email on run completion — needs auth/user emails.
- Thermal / slow CPU / OEM killers — need physical devices.

## Session Notes

- Orchestrator = Opus, implementers = Sonnet in git worktrees. Repo root `C:\Users\krishna\Desktop\bharatbench`.
