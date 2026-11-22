# f08 - Supabase storage backend

**Status:** Built (merged to main) | **Written after build (retro-spec)** | **Commits:** 4c0b656

> This spec was written after the code, from the code and git history, on 2026-11-22. It records what exists, not
> what was planned. Anything not listed under Verified is not verified.

## What it does
A second implementation of the `Storage` interface that keeps runs, findings and events in Supabase Postgres through PostgREST, selected by `STORAGE_BACKEND=supabase`. SQLite stays the default. APK and artifact files stay on local disk.

## Owned files
`api/app/storage/supabase.py`, `supabase/migrations/20261121000000_bharatbench_core.sql`, `api/tests/test_storage_supabase.py`

## Behaviour and invariants
- Only `api/app/storage/` touches the database. Models are stored as JSON in a `data` column.
- RLS is enabled on `runs`, `findings`, `events` with no public policies: only the server-side service-role key reads or writes them.
- NUL characters are stripped from APK strings before Postgres writes (commit 597ec3f).
- No new dependency: httpx against PostgREST.

## Tests
`api/tests/test_storage_supabase.py` (4 tests, respx mocks); the shared interface is also covered by `api/tests/test_storage.py` for SQLite.

## Verified / not verified
Verified: unit tests with mocked HTTP. A live round-trip was recorded in `context/progress-tracker.md` (2026-11-21). Not verified here: RLS behaviour against a live project.

## Status Log
- 2026-11-22 - retro-spec written; code and tests were already merged.
