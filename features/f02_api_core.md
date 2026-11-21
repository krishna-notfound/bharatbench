# f02 — API core: runs, pipeline, storage, scoring, report

**Status:** Implemented (pending merge)  |  **Depends on:** f01 (contracts)  |  **Owner:** Sonnet agent `api-core`

## Purpose

The FastAPI backbone: accept APK uploads, persist runs/findings/events, run the pipeline
(static analysis → harness → runtime rules → scoring → report), stream events over WebSocket, serve artifacts.

## Scope

**In:** project setup (`api/pyproject.toml` via uv), settings, SQLite storage, `RunServiceImpl`, pipeline,
harness client, scoring, markdown report, all routes in `contracts/README.md` §1–3, mounting the voice router.
**Out (explicitly):** analyzer rules (f03 — call its functions), voice internals (f05), Supabase.

## Routes / Files

**Owned files:**
- `api/.env.example`, `api/README.md` (`api/pyproject.toml` is foundation-owned and already lists all deps; report if you need another)
- `api/app/__init__.py`, `api/app/main.py`, `api/app/settings.py`, `api/app/services.py`, `api/app/pipeline.py`
- `api/app/harness_client.py`, `api/app/scoring.py`, `api/app/report.py`, `api/app/events.py`
- `api/app/storage/__init__.py`, `api/app/storage/base.py`, `api/app/storage/sqlite.py`
- `api/app/routes/__init__.py`, `api/app/routes/runs.py`, `api/app/routes/health.py`, `api/app/routes/ws_runs.py`
- `api/tests/test_storage.py`, `api/tests/test_scoring.py`, `api/tests/test_routes.py`, `api/tests/test_pipeline.py`, `api/tests/conftest.py`

**Read-only dependencies:**
- `api/app/models.py`, `api/app/profiles.py` — contracts
- `api/app/analyzer/__init__.py` (f03) — `analyze_apk(apk_path: Path, run_id: str) -> tuple[AppInfo, list[Finding]]`,
  `runtime_findings(run_id: str, result: HarnessResult) -> list[Finding]`. Until f03 merges, import lazily and write tests with monkeypatched fakes.
- `api/app/voice/router.py` (f05) — `router: APIRouter` exposing `WS /ws/voice`; voice obtains the service via `app.services.get_run_service()`. Mount with `try: from app.voice.router import router` so api runs before f05 merges.

## Data and Interfaces

- deps: fastapi, uvicorn[standard], pydantic, pydantic-settings, httpx, python-multipart, aiosqlite, androguard, websockets; dev: pytest, pytest-asyncio, ruff.
- `settings.py`: `Settings(data_dir: Path = "../data", harness_url: str | None, harness_token: str | None, sarvam_api_key: str | None, cors_origins: str = "http://localhost:3000")`, reads `api/.env`.
- `storage/base.py`: `class Storage(Protocol)` with `init()`, `create_run(run, apk_path)`, `update_run(run)`, `get_run(id)`, `get_apk_path(id)`, `list_runs()`, `add_findings(run_id, findings)`, `list_findings(run_id)`, `add_event(event)`, `list_events(run_id, after_seq)`, `next_seq(run_id)`.
- `events.py`: in-memory pub/sub per run (`asyncio.Queue` per subscriber) + persistence through Storage; implements `EventSubscription` (history-then-live, no gaps: subscribe before reading history, dedupe by seq).
- `services.py`: `RunServiceImpl(RunService)`; `get_run_service() -> RunServiceImpl` singleton created in app lifespan. `create_run` saves APK to `data/runs/{id}/app.apk` and starts `pipeline.run_pipeline` as an `asyncio.Task` (kept in a dict for cancel). `rerun` copies the source run's APK.
- `harness_client.py`: `HarnessClient(url, token)` with `health()`, `submit(apk_path, HarnessJobRequest) -> HarnessJob`, `poll(job_id)`, `result(job_id) -> HarnessResult`, `download_artifact(job_id, path, dest)`, `cancel(job_id)`; httpx timeouts (connect 5 s, read 60 s).
- `pipeline.py`: statuses per `contracts/README.md` §3. Poll harness every 2 s, forward new `HarnessJob.events` lines as `log` events and `current_profile` changes as `step` events. Harness timeout: 15 min total. Download artifacts, rewrite refs to `{profile_id}/{file}`. Emits `finding` events as findings are stored.
- `scoring.py`: `SEVERITY_WEIGHTS = {"critical":1.0,"high":0.7,"medium":0.4,"low":0.15}`; `flow_usage(finding) = 1.0 if journey_step in (None, 0) else max(0.3, 0.9 ** journey_step)`; `users_exposed = PROFILE_BY_ID[profile_id].users_exposed if profile_id else 1.0`; `score_findings(findings) -> list[Finding]` sets `impact`, rounds score to 1 decimal, returns sorted desc; `summarize(findings, runtime_executed, skipped_reason) -> RunSummary` with `reliability_score = round(max(0, 100 - sum(scores)/ max(1, len)*... ))` → use exactly: `reliability_score = round(max(0.0, 100.0 - min(100.0, sum(f.impact.score for f in findings) / 3)), 1)`.
- `report.py`: `render_markdown(run, findings, profiles) -> str` — header, app info, summary, assumptions table (profiles + users_exposed + fidelity + unsupported conditions), findings ranked with evidence excerpts, fix, repro steps and Maestro YAML block.

## Rules and Edge Cases

1. Upload: reject non-`.apk` (400), > 200 MB (413, check while streaming), unknown profile id (422).
2. Harness not configured / health fails → skip runtime, set `runtime_skipped_reason`, log event, still `done`.
3. Any exception in pipeline → status `failed`, `error` event with message; never leave a run non-terminal. On API startup, mark non-terminal runs from a previous process as `failed` ("API restarted").
4. Cancel: cancel asyncio task, call harness cancel if a job exists, status `cancelled`.
5. Artifact route: resolve path under `data/runs/{id}/artifacts`, reject traversal (400).
6. CORS from `cors_origins` (comma list).

## Tasks

- [ ] uv project + settings + storage (tests first: create/get/list/events seq)
- [ ] events bus + RunServiceImpl
- [ ] scoring + report (tests first with exact values: high severity, budget_2gb, step 0 → 100×0.45×0.7×1.0 = 31.5)
- [ ] harness client + pipeline (test with fake analyzer + fake harness via respx or monkeypatch)
- [ ] routes + WS + main (TestClient tests: upload validation, list, findings sort, traversal 400)

## Acceptance Criteria

- [ ] `uv run pytest -q` passes.
- [ ] `uv run uvicorn app.main:app --port 8000` starts; `GET /api/health` returns harness `configured:false` when unset.
- [ ] Uploading a real APK yields a `done` run with static findings and `runtime_executed:false` + reason when no harness.

## Verification

`cd api && uv sync && uv run pytest -q && uv run ruff check .`; start server, `curl -F apk=@x.apk localhost:8000/api/runs`.

## Status Log

- 2026-11-21 — Specced.
- 2026-11-21 � Implemented on `feat/f02-api-core`. 33 tests pass (storage, scoring incl. 31.5 known value, pipeline, routes, WS). Review Focus 1/2/4 covered (corrupt APK -> failed; harness ConnectError at start and mid-run -> done + skipped reason; late WS client gets history then done). Server run on :8010: /api/health, /api/profiles, upload verified. Analyzer (f03) imported lazily; without it runs end `failed` with "No module named 'app.analyzer'". Notes: `step` event `step` = 1-based profile index; cancel emits status `cancelled` then an `error` event `{error:"cancelled"}` to terminate streams; `anyio` (starlette dependency) used for async file IO; `ruff check` flags PYI034 in frozen `models.py:198` (not edited).
