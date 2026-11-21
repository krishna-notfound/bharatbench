<!-- BEGIN:framework-agent-rules -->

# Framework version warning

Next.js (version pinned in `web/package.json`) may have breaking changes — APIs, conventions, and file
structure may differ from your training data. Before writing code, read the relevant guide in
`web/node_modules/next/dist/docs/`. Heed deprecation notices. Same for Tailwind (v4: CSS-first config in
`web/app/globals.css`, no `tailwind.config.js`) and shadcn/ui.

Python: FastAPI/pydantic v2 APIs only. Sarvam: check https://docs.sarvam.ai before every API call you write.

<!-- END:framework-agent-rules -->

## Application Building Context

Read in order before implementing or making any architectural decision:

1. `context/project-overview.md`
2. `context/architecture-context.md`
3. `context/ui-context.md`
4. `context/code-standards.md`
5. `context/ai-workflow-rules.md`
6. `context/progress-tracker.md`
7. `contracts/README.md`
8. `features/README.md`, then only the `features/fNN_*.md` file(s) for the current task

Update `context/progress-tracker.md` after each meaningful implementation change.

## Verified scaffold facts (2026-11-21, from web/package.json)

- next 16.4.6, react 19.3.0, tailwindcss 4.3.3, shadcn 4.23 — shadcn components in `web/components/ui/`
  are built on **@base-ui/react**, NOT Radix: there is no `asChild`; read each component file for its
  props (Base UI uses a `render` prop for composition). Read the file before using a component.
- Components installed: badge button card checkbox dialog input progress scroll-area separator sheet
  skeleton sonner table tabs tooltip. Icons: lucide-react.
