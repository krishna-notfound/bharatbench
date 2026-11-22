# Testing

| Suite | Command | Collected tests | Notes |
| :--- | :--- | -: | :--- |
| API | `cd api && uv run pytest -q` | 306 | LLM, Sarvam, GitHub and harness are mocked (respx, fakes). One optional APK smoke test needs `BB_SAMPLE_APK`. |
| Harness | `cd harness && uv run pytest -q` | 119 | adb, tc, docker and the LLM are mocked; no device needed. |
| Web | `cd web && npm run lint && npx next typegen && npx tsc --noEmit && npm run build` | 0 unit tests | CI checks only (`.github/workflows/ci-cd.yml`). |
| Lint | `uv run ruff check .` in `api` and `harness` | - | run in CI. |

Counts come from `uv run pytest --collect-only -q | tail -1` when this file was written.

Not tested automatically: behaviour on a real redroid device, live Sarvam output quality, Supabase RLS, the web UI
beyond type/build checks, `deploy/*.sh` beyond a text check of `deploy_api.sh`.
Claim-to-test mapping: `docs/EVALUATION.md`.
