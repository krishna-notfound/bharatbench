# f13 — Sign-in pages (Google + guest) and onboarding

**Status:** In progress | **Depends on:** f10, f11 | **Owner:** Sonnet `onboarding`

## Purpose
Oryn-quality first-run experience on phone and web: a proper sign-in page (Continue with Google / Continue as guest),
then a short onboarding that explains what BharatBench does and how the test lab (harness) works, ending in the first
real action (upload an APK or talk to the agent). Honest about what the lab simulates.

## Owns
`web/app/login/**`, `web/app/onboarding/**`, `web/app/auth/callback/**` (only if needed for OAuth code exchange),
`web/components/onboarding/**`, `web/components/auth/**` (incl. `account-button.tsx`, `auth-card.tsx`, `use-session.ts`),
`web/lib/onboarding.ts`.

## Behavior
- `/login`: Oryn-like (reference: live https://oryn.app.builtbykrishna.dev and `D:\Project\ganai-ai-project\dost-ai\apps\web` login
  components — read-only, never read `.env*`/`*.pem`): orb (xl, idle) with ring, "Your cheap-phone test lab" headline, one-line
  subcopy, status pill, **Continue with Google** (white, Google "G" mark as inline SVG), **Continue as guest** (soft lavender),
  privacy note. Full-height centered, perfect at 360–430 px phones and desktop. Errors in plain language (e.g. Google not configured
  → "Google sign-in isn't set up yet — continue as guest"). `?next=` honoured after sign-in.
- Gating: browsing `/` and `/runs/[id]` stays public. Starting a test (`/new` submit), "Talk to me", and `/runs` require a session →
  redirect to `/login?next=...`. Remove the silent auto-guest sign-in from `AccountButton`; header shows "Sign in" when signed out,
  "Guest · Sign in with Google" upgrade when anonymous (use `linkIdentity` for Google if supported by installed supabase-js so guest data
  is kept; else plain OAuth), avatar/email + sign out when signed in.
- `/onboarding` (shown once after first sign-in; completion stored in localStorage `bb.onboarded.v1`, guarded try/catch; skippable):
  3 swipeable/stepped cards with the orb reacting per step:
  1. "Meet your testing buddy" — what BharatBench does in one sentence; talk or type, Hindi/English/Hinglish.
  2. "How the test lab works" — simple 4-step visual: Upload APK → real Android in our cloud lab with budget-phone limits
     (2 GB RAM cap, slow/flaky network, low storage, battery saver, app restarts) → we tap through your app and collect screenshots + logs
     → ranked issues with fixes. One honest line: "We can't simulate heat throttling or brand-specific battery killers — we'll say so."
  3. "Let's start" — primary "Upload my APK" (→ /new), secondary "Talk to the agent" (dispatch `bb:open-agent`).
  Progress dots, Back/Next, Skip. Keyboard + reduced-motion friendly.
- Mobile-first: no horizontal scroll at 360 px, tap targets ≥ 44 px, safe-area padding.

## Acceptance
lint + tsc + build pass; screenshots at 390 and 1280 of /login and each onboarding step checked; guest sign-in works against live
Supabase (anonymous sign-ins are enabled).
