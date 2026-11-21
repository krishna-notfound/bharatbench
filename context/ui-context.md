# UI Context

## Theme

Light lavender, Oryn-inspired. Warm, calm, one primary action per screen, generous whitespace. The agent
orb (`web/components/orb/orb.tsx`) is the product identity. Evidence over decoration; features the backend
lacks are shown as "Coming soon" and disabled, never faked.

All colors are CSS custom properties in `web/app/globals.css` (Tailwind v4 `@theme inline` mapping).
Components use tokens only: no hex values and no raw palette classes (`zinc-*`, `red-500`).
The only literals allowed in components are the rgba shadow values in `web/components/shell/surface.ts`.

| Role | CSS Variable | Value |
| ---- | ------------ | ----- |
| Page background | `--background` | `#faf8ff` |
| Surface (cards) | `--card` | `#ffffff` |
| Raised / quiet surface | `--muted` | `#f3f0fa` |
| Accent surface | `--accent` | `#efe9ff` |
| Primary text | `--foreground` | `#1e1b2e` |
| Muted text | `--muted-foreground` | `#6b6880` |
| Border / input | `--border` / `--input` | `#e8e4f3` / `#e3ddf2` |
| Brand (lavender) | `--primary` | `#7c5cff` (text on it `#ffffff`) |
| Orb gradient | `--orb-a/b/c` | `#c4b5fd` / `#f0abfc` / `#a5b4fc` |
| Info | `--accent-info` | `#5b8def` |
| Critical / High / Medium / Low | `--sev-*` | `#e11d48` / `#ea580c` / `#ca8a04` / `#64748b` |
| Success | `--success` | `#16a34a` |
| Destructive | `--destructive` | `#e11d48` |

Tailwind names: `bg-background`, `bg-card`, `bg-muted`, `bg-accent`, `text-foreground`, `text-muted-foreground`,
`border-border`, `bg-primary text-primary-foreground`, `text-sev-critical`, `bg-sev-high/15`, `text-success`.

## Typography

| Role | Font | CSS Variable |
| ---- | ---- | ------------ |
| UI text | Geist Sans (next/font) | `--font-geist-sans` |
| Mono (logs, ids, YAML, scores) | Geist Mono | `--font-geist-mono` |

Scale: page title `text-2xl font-semibold tracking-tight`; section `text-sm font-medium uppercase tracking-wider text-muted-foreground`;
body `text-sm`; caption `text-xs text-muted-foreground`; big score `text-5xl font-semibold font-mono tabular-nums`.

## Spacing, Radius, Shadow

Shared classes live in `web/components/shell/surface.ts` (`CARD`, `CARD_HOVER`, `PRIMARY_CTA`, `SECONDARY_CTA`).

| Context | Class / Value |
| ------- | ------------- |
| Radius base | `--radius` 0.875rem |
| Cards | `rounded-3xl border border-border bg-card shadow-[0_1px_2px_rgba(30,27,46,0.04),0_8px_24px_rgba(124,92,255,0.06)]` |
| Buttons, inputs, pills | `rounded-full` (or `rounded-2xl` for inset panels) |
| Sections | `py-12 md:py-20`; flows `max-w-3xl`, results `max-w-5xl` |
| Page padding | `px-4 md:px-8`, shell max width `max-w-5xl mx-auto` |

## Component Library

shadcn/ui in `web/components/ui/` — **protected**. App components in `web/components/<area>/`.

## Layout Patterns

- Shell: minimal translucent top bar: lavender gradient dot + "BharatBench", links "New test" (`/new`) and "Sessions" (`/runs`), subtle runtime status text from `/api/health`. No heavy borders.
- Routes: `/` Welcome (orb, "Hi, I'm BharatBench", Test my app, Talk to me, up to 3 recent sessions), `/new` Connect then Conditions (2 steps), `/runs` Sessions (friendly cards with mini orb), `/runs/[id]` agent run + issue cards.
- "Talk to me" dispatches `window` CustomEvent `bb:open-agent`; the global agent panel (right drawer desktop, bottom sheet mobile) listens.
- Mobile first at 390 px: single column, full-width CTAs. Breakpoints: Tailwind defaults (`md` 768, `lg` 1024).

## Required UI States

Every data-driven view: loading skeleton, empty state, error state (with retry), success toast (sonner),
confirm dialog for cancel run. Runtime skipped → explicit banner with `runtime_skipped_reason`.

## Accessibility

Keyboard reachable controls, visible focus ring (`ring-primary`), WCAG AA contrast, `aria-label` on icon
buttons, mic button announces state (`aria-pressed`, live region for transcript).

## Icons

lucide-react, `size-4` inline, `size-5` in buttons, stroke default.

## Content / Copy Rules

- Warm, short, plain. No jargon on primary screens. Severity words: Critical / High / Medium / Low.
- Always label fidelity: "Controlled", "Approximated", "Not simulated".
- Never say "AI found" for runtime issues — say "Observed on emulator" with the evidence.
- Welcome: "Hi, I'm BharatBench". Offline API: gentle message, never a crash or fake data.
