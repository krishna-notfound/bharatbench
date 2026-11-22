# Feature map: f02-f23 -> code -> tests -> status

Source of the feature list and merge order: `git log --oneline` (feature commits are prefixed `feat(fNN)`).
Specs: `features/README.md` (specs written before the build, or labelled "Written after build (retro-spec)").
Status values: **Merged** = on `main`, unit tests pass in CI; **Merged, live-observed** = additionally observed on
the deployed stack (only where `docs/METRICS.md` or the progress tracker records it). Nothing here is "Verified" in
the sense of a formal acceptance test on a device matrix.

| ID | Feature | Code | Tests | Status |
| :-- | :--- | :--- | :--- | :--- |
| f02 | API core: runs, pipeline, events, scoring, report, SQLite storage | `api/app/{main,services,pipeline,scoring,report,events,models,profiles}.py`, `api/app/routes/`, `api/app/storage/sqlite.py` | `api/tests/test_routes.py`, `test_pipeline.py`, `test_scoring.py`, `test_storage.py` | Merged |
| f03 | Static and runtime analyzer rules, Maestro export | `api/app/analyzer/{apk,rules_security,rules_performance,rules_runtime,maestro}.py` | `api/tests/analyzer/` (68 tests across 6 files incl. an optional APK smoke test) | Merged |
| f04 | Harness service: adb profiles, crawler, evidence, EC2 scripts | `harness/harness/{main,jobs,adb,profiles,crawler,evidence,parsers,manifest,models,settings}.py`, `harness/scripts/` | `harness/tests/test_adb_profiles.py`, `test_api_jobs.py`, `test_crawler.py`, `test_parsers.py` | Merged |
| f05 | Voice agent (REST-era): Sarvam STT, LLM with tools, TTS, `WS /ws/voice` | `api/app/voice/` | `api/tests/voice/` (test_voice_ws, test_voice_tools, test_voice_clients, ...) | Merged |
| f06 | Web UI: upload, live run, findings | `web/app/runs/`, `web/components/{upload,runs,findings,live}/` | none (web has no unit tests; CI runs lint, tsc, build) | Merged |
| f07 | Oryn-inspired redesign, agent panel | `web/components/{shell,welcome,voice}/` | none (as f06) | Merged |
| f08 | Supabase storage backend (PostgREST via httpx) | `api/app/storage/supabase.py`, `supabase/migrations/20261121000000_bharatbench_core.sql` | `api/tests/test_storage_supabase.py` (respx mocks) | Merged; selected with `STORAGE_BACKEND=supabase` |
| f09 | Realtime voice server and client (`WS /ws/realtime`) | `api/app/realtime/`, `web/lib/realtime/`, `web/lib/audio/` | `api/tests/realtime/` (23 tests) | Merged, live-observed (first-audio latency, `docs/METRICS.md`) |
| f10 | Users, conversations, Supabase auth, run user scoping | `api/app/auth/`, `api/app/conversations/`, `api/app/routes/conversations.py`, `supabase/migrations/20261121010000_users_conversations.sql`, `web/lib/supabase/` | `api/tests/auth/`, `api/tests/conversations/` | Merged; `AUTH_REQUIRED` off by default |
| f11 | Orb and welcome hero | `web/components/orb/`, `web/components/welcome/` | none | Merged |
| f12 | Finding dedupe, baseline comparison, grounded LLM explanations | `api/app/analyzer/{dedupe,explain}.py` | `api/tests/analyzer/test_dedupe.py`, `test_explain.py` | Merged |
| f13 | Sign-in page and onboarding | `web/app/{login,onboarding,auth}/`, `web/components/{auth,onboarding}/` | none | Merged |
| f14 | Harness on redroid (tc netem on veth), deploy scripts, honest profile text | `harness/harness/{adb,profiles}.py`, `deploy/setup_harness_ec2.sh`, `deploy/bharatbench-harness.service` | `harness/tests/test_adb_profiles.py` (redroid cases) | Merged, live-observed (device runs in `docs/METRICS.md`) |
| f15 | Oryn-parity voice engine (streaming STT/TTS, speculative turns) and dynamic security checks on the harness | `api/app/realtime/`, `harness/harness/security.py` | `api/tests/realtime/`, `harness/tests/test_security.py`, `api/tests/analyzer/test_runtime_security.py` | Merged |
| f16 | Agent tools: report, improvements, deeper tests, evidence, compare | `api/app/voice/tools.py` | `api/tests/voice/test_agent_tools_f16.py` | Merged |
| f17 | Multilingual agent (11 Sarvam languages), per-message language detection | `api/app/voice/languages.py`, `api/app/voice/prompts.py` | `api/tests/voice/test_multilang.py`, `test_language_directive.py` | Merged |
| f18 | Reliability: run watchdog, startup recovery, harness self-heal, job cleanup | `api/app/{pipeline,services}.py`, `harness/harness/heal.py` | `api/tests/test_reliability.py`, `harness/tests/test_heal.py` | Merged |
| f19 | Deterministic test planner; `plan_tests`, `start_planned_test` | `api/app/planner.py`, `api/app/voice/tools.py` | `api/tests/test_planner.py`, `api/tests/voice/test_planner_tools.py` | Merged |
| f20 | Play Store risk, run comparison, spoken team brief; GitHub release-APK import; live phone and replay | `api/app/{insights,github_import,live}.py`, `api/app/routes/{insights,imports,live}.py`, `harness/harness/live.py` | `api/tests/test_insights.py`, `test_github_import.py`, `test_live.py`, `harness/tests/test_live.py` | Merged |
| f21 | Tests always finish: graceful stop, resume after restart, idempotent retry | `api/app/services.py` (`cancel_run`, `recover_orphans`), `api/app/routes/runs.py` (retry), `deploy/deploy_api.sh` | `api/tests/test_resume.py`, `test_pipeline.py` (stop tests), `test_reliability.py::test_stop_keeps_completed_conditions` | Merged |
| f22 | Crawler v2: form filling, change-detection settle (no fixed sleeps) | `harness/harness/{crawler,forms}.py` | `harness/tests/test_forms.py`, `test_crawler.py` | Merged, live-observed (run time in `docs/METRICS.md`) |
| f23 | Agent-written app-specific tests; optional test account (memory-only, masked, tokenised for the LLM); offline-after-login phase | `api/app/agent_tests.py`, `api/app/analyzer/rules_agent.py`, `harness/harness/{agent,secrets}.py`, `harness/harness/jobs.py:348-460` | `api/tests/test_agent_tests.py`, `test_agent_tests_pipeline.py`, `test_credentials.py`, `api/tests/voice/test_custom_tests_tool.py`, `harness/tests/test_agent.py`, `test_credentials.py` | Merged |

Notes
- f01 is the foundation (contracts, context, scaffolds); it has no feature file.
- There is no f08 spec before this change; `features/f08_supabase_storage.md` is a retro-spec.
- Merge commits and hashes: `git log --oneline --merges`.
- The web app has no unit tests for any feature; its checks are lint, `tsc --noEmit` and `next build` (CI job `web`).
