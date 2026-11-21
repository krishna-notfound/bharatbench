# Code Standards

## General

- Keep modules small and single-purpose. Fix root causes. No dead/commented-out code, no TODOs for core functionality.
- Respect the boundaries in `architecture-context.md`. Match surrounding style.

## Language — Python (api/, harness/)

- Python ≥ 3.12, `uv` for deps, type hints everywhere, pydantic v2 models for all I/O.
- `ruff` defaults; no bare `except:` — catch specific exceptions, log, convert to a recorded error.
- Async in FastAPI; blocking work (androguard, subprocess waits) via `asyncio.to_thread` or `asyncio.create_subprocess_exec`.
- Subprocess: argument lists only, never `shell=True`, always a timeout.
- Config from env via a single `settings.py` per app (pydantic-settings).

## Language — TypeScript (web/)

- `strict` mode; no `any`; types from `web/lib/types.ts` (mirror of `api/app/models.py`).
- Validate API responses at the boundary in `web/lib/api.ts`.

## Framework

- Next.js: server components by default; `"use client"` only for interactive parts (upload, live timeline, voice).
- All API calls go through `web/lib/api.ts`; WS through `web/lib/ws.ts`.
- FastAPI: routers in `app/routes/`; no business logic in route functions.

## Styling

- Tokens only (see `ui-context.md`). No hardcoded colors. `web/components/ui/` never edited.

## Data and State

- API: all persistence via `Storage`. Web: server fetch for lists, client WS for live run state.

## Naming and File Organization

- Files named after responsibility (`rules_security.py`, `findings-table.tsx`). Python snake_case, TS kebab-case files, PascalCase components.

## Testing

- api/harness: pytest (`tests/`), `pytest-asyncio` for async. Analyzer rules tested on synthetic manifests/strings; harness parsers tested on fixture logcat/UI-dump text with `subprocess` mocked.
- web: type-check + lint + build; manual check at 390 px and 1280 px.
- A feature is not done until tests pass **and** the result was observed.

## Definition of Done (per unit of work)

1. Works end to end within the feature file's scope.
2. `uv run pytest -q` / `npm run lint && npx tsc --noEmit && npm run build` pass — real output seen.
3. No invariant in `architecture-context.md` violated.
4. Feature file *Status Log* and `progress-tracker.md` updated.
