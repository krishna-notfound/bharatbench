# Live phone + sellable report — Implementation Plan (1-hour sprint)

> For agentic workers: 4 parallel Sonnet agents in worktrees; orchestrator (Opus) tests, merges, pushes.

**Goal:** Make BharatBench feel real and sellable: a live phone that slides in from the right and shows the agent tapping through the app, a step replay, a Play Store risk score, before/after comparison, a "Brief my team" voice summary, GitHub-link import, upload-first home, and Oryn-style README/env.
**Spec:** this file + user messages of 2026-11-22 (voice secondary; phone slides in from right with clean animation; agent visibly acting on the live screen; import from GitHub link; README/env like Oryn's).

## Global constraints
- Never the word "cheap". Light lavender tokens only. Next 16.4 / React 19 / Tailwind 4; shadcn is Base UI (no asChild).
- No fake data: live frames/steps come from the real device; if unavailable say so.
- Existing tests must stay green; each agent adds tests for its backend code.

## Tasks (parallel; disjoint files)
| Task | Agent | Owns |
|---|---|---|
| A Live phone + replay | Sonnet `live-phone` | `harness/**`, `api/app/routes/live.py`, `api/app/live.py`, `api/app/pipeline.py` (persist steps.json per profile only), `api/tests/test_live.py`, `web/components/live/**`, `web/components/runs/run-detail.tsx`, `web/lib/live.ts`, contracts/README.md §7 (append) |
| B Report insights | Sonnet `insights` | `api/app/insights.py`, `api/app/routes/insights.py`, `api/tests/test_insights.py`, `web/components/report/**` (replace placeholder `ReportInsights`) |
| C GitHub import + upload-first home | Sonnet `import-home` | `api/app/github_import.py`, `api/app/routes/imports.py`, `api/tests/test_github_import.py`, `web/app/page.tsx`, `web/components/home/**`, `web/components/welcome/**`, `web/app/new/**`, `web/components/upload/**`, `web/components/voice/voice-panel.tsx` (visibility rules only), contracts/README.md §8 (append) |
| D README + env | Haiku `docs` | `README.md`, `api/.env.example`, `web/.env.example`, `harness/.env.example`, `docs/SETUP.md` |
Shared single-line edits to `api/app/main.py` (include_router, guarded import) are allowed for A, B, C; orchestrator resolves merge.

## Review focus
1. Live view when the harness is busy/offline → panel shows an honest "Phone not live" state, no spinner forever.
2. App with FLAG_SECURE (black screenshots) → show "This app hides its screen from capture" note.
3. GitHub repo with no release APK / private repo / >200 MB asset → clear 4xx message, nothing started.
4. Brief-my-team when Sarvam fails → text summary still shown.
5. Compare with no earlier run of the same package → card hidden, not an error.
