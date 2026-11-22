# Frozen Contracts

Types live in `api/app/models.py` (Python, source of truth) and `web/lib/types.ts` (TS mirror).
All JSON is snake_case. Timestamps are ISO-8601 UTC. Changing a contract needs orchestrator approval.

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

## 6. Agent tools (voice agent → `RunService`, no shell access)

| Tool | Args | Result (to LLM) |
| ---- | ---- | --------------- |
| `list_profiles` | — | profile ids, names, fidelity |
| `list_runs` | `limit?` | recent runs: id, apk, status, score |
| `start_test` | `apk_run_id?` *(re-run an uploaded APK)*, `profiles` | new run id + status (async, returns immediately) |
| `get_run_status` | `run_id` | status, progress events tail, summary |
| `list_findings` | `run_id`, `severity?`, `limit?` | top findings: id, title, severity, score |
| `explain_finding` | `finding_id` | full finding incl. evidence excerpts, cause, fix, repro |
| `cancel_run` | `run_id` | new status |

Uploading an APK happens in the web UI (voice cannot attach files); `start_test` re-runs an already
uploaded APK. Destructive tool `cancel_run` requires the user to have said cancel/stop explicitly.

## 7. Live phone and step replay (f20, append-only)

- Harness (token-protected): `GET /jobs/{id}/live` -> `{seq, ts, profile_id, step_index, action, target, tap:{x,y}|null, screen:{w,h}|null, running, has_frame}`; `GET /jobs/{id}/live.png` -> latest frame (404 until one exists). A ~1 fps `adb exec-out screencap -p` loop runs only while the job runs; only the latest frame is kept in memory.
- `HarnessStep` gains optional `x`, `y` (tap point, device px) and `screen` (index into `screens` captured after the step).
- API: `GET /api/runs/{id}/live` (proxy; `{running:false, reason}` when no active job), `GET /api/runs/{id}/live.png` (`Cache-Control: no-store`), `GET /api/runs/{id}/replay` -> `{run_id, profiles:[{profile_id, screen, steps}]}` read from `artifacts/{profile_id}/steps.json`, written by the pipeline after artifact download.
