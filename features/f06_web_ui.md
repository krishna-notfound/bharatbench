# f06 — Web UI: upload, runs, live run, findings report

**Status:** Implemented  |  **Depends on:** f01  |  **Owner:** Sonnet agent `web`

## Purpose

The developer-facing Next.js app: upload an APK with profiles, watch the run live, read ranked findings
with evidence and repro, export the report.

## Scope

**In:** theme tokens, app shell, `/`, `/runs`, `/runs/[id]`, API + WS clients, all UI states.
**Out:** voice panel internals (f05 — just mount it), auth.

## Routes / Files

**Owned files:**
- `web/app/globals.css` (tokens from `context/ui-context.md`), `web/app/layout.tsx`, `web/app/page.tsx`,
  `web/app/runs/page.tsx`, `web/app/runs/[id]/page.tsx`, `web/app/not-found.tsx`
- `web/lib/api.ts` (`API_URL` from `NEXT_PUBLIC_API_URL`, default `http://localhost:8000`; typed fetchers for every REST route), `web/lib/ws.ts` (`useRunEvents(runId)` hook with reconnect + `after_seq` resume), `web/lib/format.ts`
- `web/components/shell/**`, `web/components/upload/**`, `web/components/runs/**`, `web/components/findings/**`
- `web/.env.example`

**Read-only:** `web/lib/types.ts` (frozen), `web/components/ui/**` (shadcn, protected),
`web/components/voice/voice-panel.tsx` (f05; exports `VoicePanel`). A placeholder exists; mount `<VoicePanel />` in `layout.tsx`.

## User-facing Behavior

- **Shell:** top bar: logo mark + "BharatBench", nav "New test" (`/`), "Runs" (`/runs`); right side harness status
  dot from `GET /api/health` (green "Emulator online" / grey "Runtime offline — static scan only").
- **`/` New test:** hero "The Cheap Phone Test" + "Test your app where your users actually are." Drag-and-drop
  APK zone (accept `.apk`, show name + size, reject others inline), profile checklist from `GET /api/profiles`
  each with name, description, fidelity badge (Controlled = success, Approximated = sev-medium, Not simulated not listed),
  expandable "How" text; defaults baseline + budget_2gb + flaky_network. "Not simulated" note listing thermal/slow CPU/OEM killers.
  Submit "Run the Cheap Phone Test" → POST → navigate `/runs/{id}`. Upload progress (XHR) + error toast.
- **`/runs`:** table: app (apk name / package), status badge, profiles, critical/high counts, reliability score, created (relative). Empty state CTA. Polls every 5 s while any run non-terminal.
- **`/runs/[id]`:** header (app name, package, version, size, status badge, Cancel button with confirm dialog while non-terminal, "Download report" → `/api/runs/{id}/report.md`).
  Left: live timeline from `useRunEvents` (icon per event type, time, message; auto-scroll; status stepper analyzing → provisioning → running → scoring → done).
  Right: big reliability score (font-mono), severity counts, runtime banner if `runtime_executed=false` with reason.
  Below: findings table sorted by score: severity badge, title, category, profile, impact score bar, source ("Static scan" / "Observed on emulator"). Filters: severity, category, source.
  Row click → `Sheet` finding detail: description, impact breakdown (users exposed × severity × flow usage = score, labelled "assumptions"), evidence list (screenshots as images from artifacts route, logcat/manifest excerpts in mono `pre`), probable cause, suggested fix, repro steps, Maestro YAML with copy button.
  Refetch run + findings on `finding`/`done` events.
- States: skeletons, empty (no findings → "No issues found under these profiles"), error with retry, toasts.

## Data and Interfaces

All types from `web/lib/types.ts`. API functions: `getHealth, getProfiles, createRun(file, profiles, onProgress), listRuns, getRun, getFindings, getEvents, cancelRun, artifactUrl(runId, path), reportUrl(runId)`.

## Rules and Edge Cases

1. Tokens only; no raw palette classes. 2. Works at 390 px and 1280 px. 3. WS reconnect with backoff, resume from last seq, dedupe by seq. 4. Never display data the API did not return.

## Tasks

- [x] tokens + shell + api/ws clients
- [x] new test page
- [x] runs list
- [x] run detail + finding sheet

## Acceptance Criteria

- [x] `npm run lint`, `npx tsc --noEmit`, `npm run build` pass.
- [x] Against a running api: upload → live timeline → findings visible.

## Verification

`cd web && npm run lint && npx tsc --noEmit && npm run build`.

## Status Log

- 2026-11-21 — Specced.
- 2026-11-21 — Implemented by `web` agent on `feat/f06-web`: tokens, shell, `/`, `/runs`, `/runs/[id]`, api/ws clients, finding sheet. lint, tsc, build pass; `/` and `/runs` render with API down (error/offline states). Live upload -> timeline -> findings NOT verified against a running API (f02 unavailable). No shadcn components added. Notes: `/runs/[id]` wraps `await params` in Suspense (Cache Components enabled); `LayoutProps`/`PageProps` types need `next typegen` or a build before `tsc`.
