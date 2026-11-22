# Frozen Contracts

**Last amended:** 2026-11-22 (documentation pass; the changelog below lists what each amendment changed).

Types live in `api/app/models.py` (Python, source of truth) and `web/lib/types.ts` (TS mirror).
All JSON is snake_case. Timestamps are ISO-8601 UTC. Changing a contract needs orchestrator approval.
When a doc and the code disagree, the code wins; report the mismatch.

## Changelog

| Date | Section | Change |
| ---- | ------- | ------ |
| 2026-11-21 | all | Initial freeze (f01). |
| 2026-11-21 | 5 | Voice WS section superseded by `contracts/v2-voice-and-users.md` (realtime, protocol v2). `WS /ws/voice` still exists for the REST-era agent. |
| 2026-11-22 | 4 | f18: `/health` gains `device_status`, `last_repair`, `disk_free_mb`; `DELETE /jobs/{id}`. |
| 2026-11-22 | 7, 8 | f20: live phone and replay endpoints; GitHub import. |
| 2026-11-22 | 6 | Tool table rewritten to the real 13 tools in `api/app/voice/tools.py` `TOOL_SCHEMAS` (it listed 7, including `cancel_run`). `cancel_run` is not a voice tool (`api/tests/voice/test_voice_tools.py::test_cancel_run_tool_is_removed`). Cancel is HTTP-only and a graceful stop. |
| 2026-11-22 | 9 | New section 9 documents routes added after the freeze (retry, agent-tests, credentials form field, insights). |

## 1. Public API (FastAPI, `api/`, default `http://localhost:8000`)

| Method | Path | Body / Query | Returns |
| ------ | ---- | ------------ | ------- |
| GET | `/api/health` | — | `{ok: true, harness: {configured: bool, reachable: bool, detail: str}, sarvam_configured: bool}` |
| GET | `/api/profiles` | — | `Profile[]` |
| POST | `/api/runs` | multipart: `apk` (file, `.apk`, ≤ 200 MB), `profiles` (comma-separated `ProfileId`, default `baseline,budget_2gb,flaky_network`) | `Run` (status `queued`), 201 |
| GET | `/api/runs` | — | `Run[]` newest first |
| GET | `/api/runs/{id}` | — | `Run` or 404 |
| GET | `/api/runs/{id}/findings` | — | `Finding[]` sorted by `impact.score` desc |
| GET | `/api/runs/{id}/events` | `after_seq` int | `RunEvent[]` |
| POST | `/api/runs/{id}/cancel` | — | `Run` |
| GET | `/api/runs/{id}/report.md` | — | `text/markdown` full report |
| GET | `/api/runs/{id}/artifacts/{path}` | — | file (screenshots png, logcat txt, ui xml, flow yaml); path traversal rejected (400) |

Errors: `{detail: str}` with 400/404/413/422/500.

## 2. Run events WebSocket — `WS /ws/runs/{id}`

On connect the server sends every past `RunEvent` (in `seq` order), then live ones. One JSON
`RunEvent` per message. The client may send `{"type":"ping"}`; server answers `{"type":"pong"}`.
Stream ends after an event of type `done` or `error` (socket stays open, client may close).

Event `type` meaning: `status` (data: `{status}`), `log` (free text), `step` (data: `{profile_id, step}`),
`finding` (data: `{finding_id, severity, title}`), `artifact` (data: `{path, kind}`), `done`
(data: `{summary}`), `error` (data: `{error}`).

## 3. Run pipeline (status order)

`queued → analyzing (static APK scan) → provisioning (harness upload/profile) → running (per profile)
→ scoring → done`. Any failure → `failed` with `error`. Cancel → `cancelled`.
If the harness is not configured or unreachable, runtime is **skipped, not faked**:
`summary.runtime_executed=false`, `summary.runtime_skipped_reason` set, and a `log` event says so.

## 4. Harness API (FastAPI, `harness/`, runs on EC2, default `http://127.0.0.1:8100` via SSH tunnel)

Every request needs header `X-Harness-Token: <HARNESS_TOKEN>`; missing/wrong → 401.

| Method | Path | Body | Returns |
| ------ | ---- | ---- | ------- |
| GET | `/health` | — | `{adb: bool, devices: str[], emulator_booted: bool, maestro: bool, android_version: str\|null, device_status: ok\|degraded\|repairing\|down, last_repair, disk_free_mb}` (last three added in f18; job `events` may carry `DEVICE:` lines) |
| POST | `/jobs` | multipart: `apk` file + `request` (JSON `HarnessJobRequest`) | `HarnessJob`, 202. 409 if a job is running (one at a time). |
| GET | `/jobs/{job_id}` | — | `HarnessJob` |
| GET | `/jobs/{job_id}/result` | — | `HarnessResult` (409 while queued/running; also served for failed/cancelled jobs so partial results survive) |
| GET | `/jobs/{job_id}/artifacts/{path}` | — | file |
| POST | `/jobs/{job_id}/cancel` | — | `HarnessJob` |
| DELETE | `/jobs/{job_id}` | — | `{deleted, job_id}`; removes artifacts after the API downloaded them (409 while running, idempotent). Added in f18 |

Artifact paths in `HarnessResult` are relative to the job dir; the API downloads each into
`data/runs/{run_id}/artifacts/{profile_id}/...` and rewrites refs to that relative path.

## 5. Voice WebSocket — `WS /ws/voice`

Client → server:
- binary frames: 16 kHz mono PCM16 little-endian audio, ~100 ms chunks (only while user is speaking per client VAD, plus 300 ms tail)
- `{"type":"start", "language":"auto"|"hi-IN"|"en-IN", "run_id": str|null}` — first message
- `{"type":"speech_end"}` — client VAD detected end of utterance
- `{"type":"interrupt"}` — user started talking while assistant audio is playing (barge-in)
- `{"type":"text", "text": str}` — typed input (same pipeline minus STT)

Server → client:
- `{"type":"ready"}`
- `{"type":"transcript", "text": str, "final": bool}`
- `{"type":"assistant_text", "text": str, "turn_id": str}` (sentence chunks)
- `{"type":"tool_call", "name": str, "args": object, "turn_id": str}` / `{"type":"tool_result", "name": str, "ok": bool, "summary": str}`
- `{"type":"audio", "turn_id": str, "format": "wav"|"mp3", "sample_rate": int, "data": base64}` (one per sentence chunk)
- `{"type":"turn_end", "turn_id": str}`
- `{"type":"run_update", "run_id": str, "status": str, "message": str}` (agent watching a run it started)
- `{"type":"error", "message": str}`

On `interrupt` the server cancels the in-flight LLM/TTS task for the current turn and sends `turn_end`;
the client stops and flushes playback immediately.

## 6. Agent tools (voice agent -> `RunService`, no shell access)

Source of truth: `TOOL_SCHEMAS` in `api/app/voice/tools.py` (13 tools); dispatch is `dispatch()` in the same file and
the realtime engine reuses it via `api/app/realtime/registry.py` (20 s per tool call, at most 4 tool rounds per turn).
Unknown tools and missing arguments return `{"error": ...}` to the LLM (`api/tests/voice/test_voice_tools.py`).

| Tool | Args (required in bold) | Result (to LLM) |
| ---- | ---- | --------------- |
| `list_profiles` | - | profile ids, names, fidelity |
| `list_runs` | `limit?` | recent runs: id, apk, status, score |
| `start_test` | **`profiles`**, `apk_run_id?`, `apk_name?` | new run id + status (async, returns immediately); re-runs an already uploaded APK |
| `get_run_status` | **`run_id`** | status, progress events tail, summary |
| `list_findings` | **`run_id`**, `severity?`, `limit?` | top findings: id, title, severity, score |
| `explain_finding` | **`finding_id`** | full finding incl. evidence excerpts (truncated), cause, fix, repro |
| `get_report` | **`run_id`** | compact report: score, profiles run and whether applied, top findings, counts |
| `suggest_improvements` | **`run_id`**, `focus?` (`security`, `performance`, `reliability`, `network`, `all`) | prioritised fixes grouped by root cause, with finding ids |
| `run_deeper_tests` | `run_id?`, `profiles?`, `journey_steps?` | new run id (async); defaults to every supported profile not yet run, longer journey |
| `get_finding_evidence` | **`finding_id`** | log excerpts and artifact URLs |
| `plan_tests` | `apk_or_run?`, `plan_kind?` (`initial`, `followup`) | deterministic plan with reasons; starts nothing (`api/app/planner.py`) |
| `start_planned_test` | `apk_or_run?`, `plan_kind?` | computes the same plan and starts it; returns run id and reasons |
| `write_custom_tests` | **`request`**, `apk_or_run?` | 1-5 app-specific tests written from the user's words; starts a run with them (f23) |
| `compare_runs` | **`run_a`**, **`run_b`** | score delta; fixed / new / persisting findings |

Uploading an APK happens in the web UI (voice cannot attach files); `start_test` re-runs an already uploaded APK.

**Cancel is not a voice tool.** Stopping a run is `POST /api/runs/{id}/cancel` only. It is a graceful stop: the
pipeline is flagged, finishes the work in flight, and ends the run `done` with the results collected so far
(`api/app/services.py` `cancel_run`; `api/tests/test_pipeline.py::test_stop_is_graceful_and_ends_done`). The agent's
system prompt tells it tests always run to completion and never to claim a test was stopped.

## 7. Live phone and step replay (f20, append-only)

- Harness (token-protected): `GET /jobs/{id}/live` -> `{seq, ts, profile_id, step_index, action, target, tap:{x,y}|null, screen:{w,h}|null, running, has_frame}`; `GET /jobs/{id}/live.png` -> latest frame (404 until one exists). A ~1 fps `adb exec-out screencap -p` loop runs only while the job runs; only the latest frame is kept in memory.
- `HarnessStep` gains optional `x`, `y` (tap point, device px) and `screen` (index into `screens` captured after the step).
- API: `GET /api/runs/{id}/live` (proxy; `{running:false, reason}` when no active job), `GET /api/runs/{id}/live.png` (`Cache-Control: no-store`), `GET /api/runs/{id}/replay` -> `{run_id, profiles:[{profile_id, screen, steps}]}` read from `artifacts/{profile_id}/steps.json`, written by the pipeline after artifact download.

## 8. GitHub import (f20)

`POST /api/runs/import` body `{"repo_url": str, "profiles"?: ProfileId[]}` → `201 Run` (same shape as `POST /api/runs`).
Accepts `https://github.com/{owner}/{repo}` (also `.git` suffix and `/releases/tag/{tag}`). Uses the GitHub
REST API only: latest release, falling back to the newest release that has an `.apk` asset (`.aab` is never
used; names with universal, arm64 then x86_64 are preferred). Asset must be <= 200 MB (checked from the
declared size and again while streaming) and start with the ZIP magic `PK`. The run's `apk_name` is the asset
name and a `log` event records `Imported from github.com/{owner}/{repo} release {tag}`. Nothing is built from
source. Optional server env `GITHUB_TOKEN` (private repos / rate limits) is sent to GitHub only, never logged.

Errors (`detail` is user-facing): 400 not a GitHub repo URL / not a ZIP / empty; 404 repo not found or private,
no releases, or "This repo has no APK in its releases. Upload the APK, or add one to a GitHub release.";
413 APK over 200 MB; 422 unknown profile; 429 GitHub rate limit; 502/504 GitHub or download failure.

## 9. Routes added after the freeze (f21-f23; documented 2026-11-22)

Shapes are in the route modules named here; the code is the source of truth.

- `POST /api/runs` also accepts an optional multipart field `credentials` (JSON `TestCredentials`: `login`,
  `password`, `note`, `offline_after_login`). Memory-only for the life of the run; never stored, echoed or logged
  (`api/app/routes/runs.py:42`, `api/app/models.py:131`, `api/tests/test_credentials.py`).
- `POST /api/runs/{id}/retry` - idempotent re-run of a `cancelled` or `failed` run; repeated calls return the same
  new run (`api/app/routes/runs.py:136`).
- `GET /api/runs/{id}/agent-tests` - results of the app-specific tests written by the agent (`runs.py:108`).
- `GET /api/runs/{id}/play-risk`, `GET /api/runs/{id}/compare`, `POST /api/runs/{id}/brief` - lab-based Play Store
  risk, comparison with the previous run, and a spoken team brief (`api/app/routes/insights.py`, f20).
- `GET /api/conversations`, `GET /api/conversations/{id}/messages` - see `contracts/v2-voice-and-users.md` section 3.
