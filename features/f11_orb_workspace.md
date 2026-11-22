# f11 — Oryn-style orb + welcome

**Status:** Built (merged to main; see docs/FEATURE_MAP.md) | **Owner:** Sonnet `orb-ui`

## Owns
`web/components/orb/**`, `web/components/welcome/**`, `web/app/page.tsx`, `web/app/globals.css` (orb keyframes/tokens only),
`context/ui-context.md`.

## Behavior
- Orb: port the look of Oryn `apps/web/components/Orb.tsx` (+ its globals.css keyframes): outer ring with level-driven stroke,
  glossy gradient body (lavender with soft sage rim), cartoon face (big glossy eyes with highlights, blinking, mouth per state),
  rAF loop reading optional `getLevel()` without React re-renders, breathe/ripple/shimmer.
- Keep existing exports in `web/components/orb/orb.tsx` (`Orb`, `OrbState`, `ORB_LABEL`, `orbStateFromRun`); add optional
  `getLevel?: () => number`. Work states (inspecting/building/starting_emulator/testing/analysing) show a focused working face.
  Respect reduced motion.
- Welcome page: Oryn-like hero (orb, "Hi, I'm BharatBench", warm subcopy, status pill, "Test my app" + "Talk to me").

## Acceptance
lint + tsc + build; visual check at 390 and 1280 px.
