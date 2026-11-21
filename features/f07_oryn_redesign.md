# f07 — Oryn-inspired redesign (welcome, connect, agent, results)

**Status:** In progress  |  **Depends on:** f05, f06  |  **Owner:** Sonnet `journey` (A) + Sonnet `agent-results` (B)

## Purpose

Make BharatBench feel welcoming and effortless (Oryn philosophy): one primary action per screen, the agent
orb as the product's identity, progressive disclosure, evidence over decoration. Light lavender theme.

## Design system (already built — consume, do not edit)

- Tokens in `web/app/globals.css` (light lavender: `bg-background` #faf8ff, `bg-card` white, `bg-primary` #7c5cff,
  `bg-accent`, `bg-muted`, severity `text-sev-*`, `text-success`, `--orb-a/b/c`). Radius base 0.875rem.
- Cards: `rounded-3xl border border-border bg-card shadow-[0_1px_2px_rgba(30,27,46,0.04),0_8px_24px_rgba(124,92,255,0.06)]`.
  Inputs/buttons `rounded-full` or `rounded-2xl`. Generous whitespace: sections `py-12 md:py-20`, `max-w-3xl` for flows, `max-w-5xl` for results.
- `web/components/orb/orb.tsx`: `<Orb state size showLabel />`, `OrbState`, `ORB_LABEL`, `orbStateFromRun(status)`. Orb states must come from real events only.
- Copy: warm, short, plain. No jargon on primary screens. Never present fake results. Features the backend lacks are shown as "Coming soon" and disabled — never faked.

## Screen architecture

| Route | Screen | One primary action |
| ----- | ------ | ------------------ |
| `/` | Welcome: big orb (idle; or speaking/listening from voice), "Hi, I'm BharatBench" + 1-line intro, CTA "Test my app" → `/new`, secondary "Talk to me" opens agent panel, "Recent sessions" (max 3 compact rows, hidden if none / API offline shows gentle note) | Test my app |
| `/new` | Connect → Conditions, 2-step flow in one page. Step 1 tabs: **GitHub repo** (input + "Coming soon — repo builds are on the way. Upload an APK for now." disabled), **Upload APK** (default selected, works), **APK link** (Coming soon, disabled). "What happens next" 3-step explainer. Step 2: friendly profile cards (Budget Android = budget_2gb, Weak Network = flaky_network, Low Storage, Battery Saver, App restarts = process_death, Baseline hidden under "Advanced" and auto-included), fidelity shown as small subtle tag; "Advanced" disclosure reveals the `how` text + Not-simulated list. CTA "Start testing" | Start testing |
| `/runs` | Sessions: friendly cards (app name, status with mini orb, date, top issue count) | Open a session |
| `/runs/[id]` | Agent run: orb at top bound to `orbStateFromRun(run.status)` + `ORB_LABEL`, one-line "what I'm doing now" (latest event message), compact progress steps; when done: summary sentence ("Found 2 critical issues that affect ~45% of users"), score, then **issue cards** sorted by impact (severity pill, title, plain-language impact, "Observed on emulator"/"Found in APK scan"), card click → detail sheet (screenshots first, repro steps, cause, fix, Maestro YAML copy, raw evidence collapsed under "Technical details"). Full event log collapsed under "Activity log". Runtime-skipped → gentle banner | Read top issue |
| Agent panel (global) | Right-side drawer (desktop) / bottom sheet (mobile) launched by floating orb button (mini `<Orb size="sm">` reflecting voice state). Shared voice+text thread, streaming assistant text, tool calls as small chips ("Started a test", "Checked findings"), mic toggle, interrupt by speaking or tapping orb while speaking. Thread persisted per browser in localStorage (labelled convenience), "New conversation" button | Talk / type |

## Owned files

**A `journey`:** `web/app/page.tsx`, `web/app/new/**`, `web/app/runs/page.tsx`, `web/app/not-found.tsx`, `web/components/shell/**`,
`web/components/upload/**`, `web/components/welcome/**`, `web/components/runs/runs-list.tsx`, `context/ui-context.md` (rewrite Theme/Tokens/Layout to match this file).
**B `agent-results`:** `web/app/runs/[id]/**`, `web/components/runs/run-detail.tsx`, `timeline.tsx`, `score-panel.tsx`, `status-badge.tsx`,
`web/components/findings/**`, `web/components/voice/voice-panel.tsx` (+ new UI files in `web/components/voice/`; keep `use-voice-session.ts`/`audio.ts` protocol behaviour, you may add an `orbState` derived value and localStorage persistence of transcript).

**Read-only for both:** `web/app/globals.css`, `web/app/layout.tsx`, `web/components/orb/**`, `web/components/ui/**`, `web/lib/**`.
To open the agent panel from the welcome page, B exports `openAgentPanel()` from `web/components/voice/agent-events.ts`
(dispatches `window` CustomEvent `"bb:open-agent"`); A calls `window.dispatchEvent(new CustomEvent("bb:open-agent"))` directly so there is no import race.

## Acceptance Criteria

- [ ] `npm run lint && npx tsc --noEmit && npm run build` pass.
- [ ] Screens render at 390 px and 1280 px; API offline → gentle offline states, no crashes, no fake data.
- [ ] Orb states on `/runs/[id]` change with real run status; agent orb reflects voice state.

## Status Log

- 2026-11-21 — Tokens + Orb built by orchestrator; A and B dispatched.
