# UI Context

## Theme

Dark only. A focused engineering console — dense, calm, evidence-first — with saffron as the single
brand accent and a status palette for severity. No gradients-for-decoration, no stock illustrations.

All colors are CSS custom properties in `web/app/globals.css` (Tailwind v4 `@theme inline` mapping).
Components use tokens only — no hex values and no raw palette classes (`zinc-*`, `red-500`).

| Role | CSS Variable | Value |
| ---- | ------------ | ----- |
| Page background | `--background` | `#0B0D10` |
| Surface (cards) | `--card` | `#12161B` |
| Raised surface | `--muted` | `#1A1F26` |
| Primary text | `--foreground` | `#E6E8EB` |
| Muted text | `--muted-foreground` | `#8A94A3` |
| Border | `--border` | `#232A33` |
| Brand (saffron) | `--primary` | `#FF9933` (text on it `#0B0D10`) |
| Accent (info) | `--accent-info` | `#38BDF8` |
| Critical | `--sev-critical` | `#F43F5E` |
| High | `--sev-high` | `#FB923C` |
| Medium | `--sev-medium` | `#FACC15` |
| Low | `--sev-low` | `#94A3B8` |
| Success | `--success` | `#22C55E` |
| Destructive | `--destructive` | `#F43F5E` |

Tailwind names: `bg-background`, `bg-card`, `bg-muted`, `text-foreground`, `text-muted-foreground`,
`border-border`, `bg-primary text-primary-foreground`, `text-sev-critical`, `bg-sev-high/15`, `text-success`, `text-accent-info`.

## Typography

| Role | Font | CSS Variable |
| ---- | ---- | ------------ |
| UI text | Geist Sans (next/font) | `--font-geist-sans` |
| Mono (logs, ids, YAML, scores) | Geist Mono | `--font-geist-mono` |

Scale: page title `text-2xl font-semibold tracking-tight`; section `text-sm font-medium uppercase tracking-wider text-muted-foreground`;
body `text-sm`; caption `text-xs text-muted-foreground`; big score `text-5xl font-semibold font-mono tabular-nums`.

## Spacing, Radius, Shadow

| Context | Class / Value |
| ------- | ------------- |
| Inline / small (badges, inputs) | `rounded-md` |
| Cards | `rounded-xl` |
| Sheets / dialogs | `rounded-2xl` |
| Shadow | none on cards (borders instead); `shadow-lg` only on floating voice panel |
| Page padding | `px-4 md:px-8`, max width `max-w-6xl mx-auto` |

## Component Library

shadcn/ui in `web/components/ui/` — **protected**. App components in `web/components/<area>/`.

## Layout Patterns

- One app shell: top bar (logo "BharatBench", nav: New test · Runs, harness status dot from `/api/health`), content below.
- Voice panel: floating mic button bottom-right on every page; expands into a panel (transcript + state).
- Run page: left column timeline (live), right column summary score + profile cards; findings table full width below; finding detail in a right `Sheet`.
- Mobile: single column, sheet becomes full-screen. Breakpoints: Tailwind defaults (`md` 768, `lg` 1024).

## Required UI States

Every data-driven view: loading skeleton, empty state, error state (with retry), success toast (sonner),
confirm dialog for cancel run. Runtime skipped → explicit banner with `runtime_skipped_reason`.

## Accessibility

Keyboard reachable controls, visible focus ring (`ring-primary`), WCAG AA contrast, `aria-label` on icon
buttons, mic button announces state (`aria-pressed`, live region for transcript).

## Icons

lucide-react, `size-4` inline, `size-5` in buttons, stroke default.

## Content / Copy Rules

- Plain, direct, developer tone. Severity words: Critical / High / Medium / Low.
- Always label fidelity: "Controlled", "Approximated", "Not simulated".
- Never say "AI found" for runtime issues — say "Observed on emulator" with the evidence.
- Hero copy: "The Cheap Phone Test" / "Test your app where your users actually are."
