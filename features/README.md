# Features

One file per feature: `fNN_<about_it>.md`, numbered in build order. **A feature file must exist and be
filled in before any code for that feature is written.** Features f08, f14 and f16-f23 were built without a spec;
their files are labelled "Written after build (retro-spec)" and describe what exists, not what was planned.

Feature -> code -> tests -> status: see `docs/FEATURE_MAP.md`.

## Index

| ID | File | Area | Depends on | Status | Spec |
| -- | ---- | ---- | ---------- | ------ | ---- |
| f01 | (foundation, no file) contracts, context, scaffolds | all | - | Built | n/a |
| f02 | `f02_api_core.md` | api | f01 | Built | Before build |
| f03 | `f03_analyzer.md` | api/analyzer | f01 | Built | Before build |
| f04 | `f04_harness.md` | harness | f01 | Built | Before build |
| f05 | `f05_voice_agent.md` | api/voice + web/voice | f01, f02 | Built | Before build |
| f06 | `f06_web_ui.md` | web | f01 | Built | Before build |
| f07 | `f07_oryn_redesign.md` | web redesign | f05, f06 | Built | Before build |
| f08 | `f08_supabase_storage.md` | api/storage | f02 | Built | Retro-spec |
| f09 | `f09_realtime_voice.md` | realtime voice | contracts v2 | Built | Before build |
| f10 | `f10_users_conversations.md` | auth + conversations | contracts v2 | Built | Before build |
| f11 | `f11_orb_workspace.md` | orb + welcome | f07 | Built | Before build |
| f12 | `f12_explanations.md` | AI explanations, dedupe | f03 | Built | Before build |
| f13 | `f13_auth_onboarding.md` | sign-in + onboarding | f10, f11 | Built | Before build |
| f14 | `f14_harness_redroid.md` | harness device | f04 | Built | Retro-spec |
| f15 | `f15_oryn_parity_security.md` | voice engine + dynamic security | f09, f14 | Built | Before build |
| f16 | `f16_agent_tools.md` | agent tools | f05 | Built | Retro-spec |
| f17 | `f17_multilingual.md` | multilingual agent | f09 | Built | Retro-spec |
| f18 | `f18_reliability.md` | reliability | f02, f04 | Built | Retro-spec |
| f19 | `f19_planner.md` | test planner | f16 | Built | Retro-spec |
| f20 | `f20_insights_import_live.md` | insights, import, live phone | f02, f04 | Built | Retro-spec |
| f21 | `f21_tests_always_finish.md` | stop, resume, retry | f18 | Built | Retro-spec |
| f22 | `f22_crawler_v2.md` | crawler | f04 | Built | Retro-spec |
| f23 | `f23_agent_tests.md` | agent-written tests, test account | f16, f22 | Built | Retro-spec |

Deferred (not built): GitHub repo -> APK build from source, Resend emails, multi-device concurrency, physical-device
conditions (thermal, slow CPU, OEM killers). Planned but not started items are listed in `docs/LIMITATIONS.md`.

Status values: `Planned` -> `Specced` -> `In progress` -> `Built` -> `Verified` (or `Deferred`).
`Built` means merged to `main` with unit tests passing. No feature is marked `Verified`: that would need an
acceptance run on a device matrix, which has not been done (`docs/LIMITATIONS.md`).
