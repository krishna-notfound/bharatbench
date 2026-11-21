# Architecture Context

```text
Browser (Next.js web)  ──REST + WS /ws/runs/{id}──►  FastAPI api (laptop or EC2)
   └─ mic AudioWorklet ──WS /ws/voice (PCM16)──────►    ├─ pipeline: analyze → harness → score → report
                                                         ├─ analyzer (androguard)  ├─ storage (SQLite + files)
                                                         ├─ voice agent ──HTTPS/WSS──► Sarvam STT / LLM / TTS
                                                         └─ harness client ──HTTP (SSH tunnel :8100)──►
                                                               harness service on EC2 (KVM)
                                                               ADB ─► Android Emulator (2 GB AVD) + Maestro
```

## Stack

| Layer | Technology | Role |
| ----- | ---------- | ---- |
| Web | Next.js (App Router) + TypeScript | Upload, live run, report, voice panel |
| UI | Tailwind v4 + shadcn/ui + lucide-react | Components and tokens |
| API | Python 3.12+, FastAPI, uvicorn, pydantic v2, httpx, uv | REST, WebSockets, pipeline, agent |
| Static analysis | androguard | Parse manifest, dex, resources of the APK |
| Storage (now) | SQLite (`data/bharatbench.db`) + files (`data/runs/`) | Runs, findings, events, artifacts |
| Storage (Supabase) | Supabase Postgres via PostgREST (`api/app/storage/supabase.py`) | Available now behind `STORAGE_BACKEND=supabase` (needs `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`); Storage bucket + Auth still later |
| Voice/AI | Sarvam: streaming STT, chat LLM (tool calling), TTS | Voice agent |
| Harness | FastAPI on Ubuntu 24.04 EC2 with KVM, Android SDK cmdline-tools, emulator, ADB, Maestro | Executes APK under profiles |
| Email (later) | Resend | Run-complete emails |

Verified versions: fill from `web/package.json`, `api/uv.lock`, `harness/uv.lock` — never from memory.

## System Boundaries

- `api/app/models.py`, `api/app/profiles.py` — frozen contracts. No logic.
- `api/app/main.py` + `api/app/routes/` — HTTP/WS routing only; delegates to services.
- `api/app/services.py` — `RunServiceImpl` implementing `RunService`; owns run lifecycle + event bus.
- `api/app/pipeline.py` — runs one pipeline per run as an asyncio task; never blocks the event loop (CPU work in `asyncio.to_thread`).
- `api/app/storage/` — the only module that touches SQLite/files. Interface `Storage` in `storage/base.py`.
- `api/app/harness_client.py` — the only module that talks to the harness.
- `api/app/analyzer/` — pure functions: APK path → `AppInfo` + findings; `HarnessResult` → findings. No I/O besides reading the APK.
- `api/app/scoring.py` + `api/app/report.py` — pure functions.
- `api/app/voice/` — voice WS endpoint, Sarvam clients, agent loop, tools. Talks only to `RunService`.
- `harness/` — runs on EC2 only; talks to ADB/emulator/Maestro via subprocess; knows nothing about the api's DB.
- `web/` — talks only to the API (`NEXT_PUBLIC_API_URL`); never to Sarvam or the harness.

## Data Model

| Entity | Key fields | Relations | Notes |
| ------ | ---------- | --------- | ----- |
| runs | id (uuid hex), apk_name, apk_path, status, profile_ids (json), app (json), summary (json), error, created_at, updated_at | 1→n findings, events | apk stored at `data/runs/{id}/app.apk` |
| findings | id, run_id, json (Finding), score | n→1 run | sorted by score desc |
| events | run_id, seq, ts, type, message, data (json) | n→1 run | seq starts at 1 per run |

Artifacts: `data/runs/{run_id}/artifacts/{profile_id}/{file}`. Pydantic models in `models.py` are the naming source of truth.

## Data Access Layer

- UI reads/writes only through the REST/WS API in `contracts/README.md`, via `web/lib/api.ts`.
- API code reaches data only via `Storage` (`api/app/storage/base.py`); current impl `storage/sqlite.py`.
- `storage/supabase.py` implements the same interface (select with `STORAGE_BACKEND`; default `sqlite`).

## Auth and Authorization Model

- Prototype: no user auth. API binds to localhost / is behind the demo machine.
- Harness: shared secret header `X-Harness-Token`, bound to 127.0.0.1 on EC2, reached only via SSH tunnel.
- Later: Supabase Auth JWT verified in FastAPI dependency; runs get `user_id`; RLS in Postgres.

## Storage Model

- SQLite: runs, findings, events. Files: APKs, screenshots, UI dumps, logcat, Maestro flows.
- Secrets only in `api/.env`, `harness/.env`, `secrets/` (all gitignored). Env vars:
  `SARVAM_API_KEY`, `HARNESS_URL`, `HARNESS_TOKEN`, `DATA_DIR`, `CORS_ORIGINS`, `NEXT_PUBLIC_API_URL`,
  harness: `HARNESS_TOKEN`, `ANDROID_SERIAL` (default `emulator-5554`), `JOBS_DIR`, `ANDROID_HOME`.

## Invariants

1. No runtime finding without harness evidence; harness unavailable ⇒ runtime skipped and stated.
2. Uploaded APKs are never executed on the API host; only parsed (androguard) and forwarded to the emulator.
3. Voice agent has no shell/file access; only `contracts/README.md` §6 tools.
4. Harness listens on 127.0.0.1 only and requires `X-Harness-Token`; one job at a time; every profile change is reverted after its profile (network, storage filler, battery) even on failure (`try/finally`).
5. Every run ends in `done`, `failed` or `cancelled`; every pipeline exception is caught and recorded.
6. Artifact paths are resolved under the run dir; `..`/absolute paths rejected.
7. Event `seq` per run is strictly increasing; WS clients get history then live events with no gaps.

## Known Risks

| Risk | Impact | Mitigation |
| ---- | ------ | ---------- |
| EC2 type lacks nested virtualization → emulator without KVM is unusably slow | No runtime demo | Use c8i/m8i (nested virt) or `*.metal`; `harness/scripts/setup_ec2.sh` checks `/dev/kvm` first |
| Emulator boot 1–3 min, flaky | Slow demo | Boot once at setup with snapshot; harness reuses the running emulator |
| Sarvam API shape differs from assumptions | Voice breaks | f05 agent verifies docs first; text-input fallback in voice WS |
| Crawler taps destructive/paid buttons | Bad demo | Denylist of labels (logout, delete, pay, buy, purchase, sign out, uninstall) |
| Network shaping via emulator console is approximate | Over-claiming | Fidelity labels from `profiles.py` shown everywhere |
| Androguard slow on huge APKs | Upload feels stuck | Runs in thread; status events; 200 MB cap |
