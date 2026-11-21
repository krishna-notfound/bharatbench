# Features

One file per feature: `fNN_<about_it>.md`, numbered in build order. **A feature file must exist and be
filled in before any code for that feature is written.**

## Index

| ID | File | Area | Depends on | Status |
| -- | ---- | ---- | ---------- | ------ |
| f01 | (foundation — no file) contracts, context, scaffolds | all | — | Built |
| f02 | `f02_api_core.md` | api | f01 | Specced |
| f03 | `f03_analyzer.md` | api/analyzer | f01 | Specced |
| f04 | `f04_harness.md` | harness (EC2) | f01 | Specced |
| f05 | `f05_voice_agent.md` | api/voice + web/voice | f01, f02 | Specced |
| f06 | `f06_web_ui.md` | web | f01 | Built |
| f07 | `f07_oryn_redesign.md` | web redesign | f05, f06 | Built |
| f09 | `f09_realtime_voice.md` | realtime voice | contracts v2 | In progress |
| f10 | `f10_users_conversations.md` | auth + conversations | contracts v2 | In progress |
| f11 | `f11_orb_workspace.md` | orb + welcome | f07 | In progress |
| f12 | `f12_explanations.md` | AI explanations | f03 | In progress |

Deferred: GitHub build pipeline, Supabase storage/auth, Resend emails.

Status values: `Planned` → `Specced` → `In progress` → `Built` → `Verified` (or `Deferred`).
