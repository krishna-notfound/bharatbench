# f10 — Users + shared conversation history

**Status:** Built (merged to main; see docs/FEATURE_MAP.md) | **Depends on:** contracts/v2-voice-and-users.md | **Owner:** Sonnet `users`

Purpose: Oryn-style auth (Supabase anonymous guest + Google), one persistent conversation shared by voice and text,
history UI, runs owned by users.

## Owns
- `supabase/migrations/20261121010000_users_conversations.sql`: profiles, conversations, messages with RLS (users read own
  rows; backend writes with service role). `runs.user_id` already exists. **Do not apply to the live DB** — orchestrator applies it.
- `api/app/auth/**` (`verify_token` per contract §2; JWKS via `{SUPABASE_URL}/auth/v1/.well-known/jwks.json` for ES256/RS256,
  optional HS256 `supabase_jwt_secret`; like Oryn `backend/app/auth/supabase.py`), `api/app/conversations/**`,
  `api/app/routes/conversations.py` (+ one guarded include line in `main.py`), user scoping in `api/app/routes/runs.py`
  (optional Bearer → `user_id` on create, filter list), settings `auth_required: bool = False`, `supabase_jwt_secret`.
- `api/tests/auth/**`, `api/tests/conversations/**`.
- `web/lib/supabase/**`, `web/components/auth/**` (Oryn-style "Continue with Google" / "Continue as guest"),
  `web/components/history/**` (conversation list + messages view component). Add `@supabase/supabase-js` + `@supabase/ssr`.
  Web env: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`.

## Acceptance
pytest + ruff; lint + tsc + build. Guest sign-in works against live Supabase once anonymous sign-ins are enabled.
