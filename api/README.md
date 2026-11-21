# BharatBench API

FastAPI backend: APK upload, run pipeline (static analysis -> harness -> scoring), events WebSocket, report.

```bash
uv sync
cp .env.example .env        # leave HARNESS_URL empty to skip runtime testing
uv run uvicorn app.main:app --reload --port 8000
uv run pytest -q && uv run ruff check .
```

Routes are specified in `../contracts/README.md`. Without `HARNESS_URL` (or if the harness is unreachable)
runs finish `done` with static findings only, `summary.runtime_executed=false` and a skipped reason.
Data (SQLite db, APKs, artifacts) lives under `DATA_DIR/` (`runs/{id}/app.apk`, `runs/{id}/artifacts/`).
