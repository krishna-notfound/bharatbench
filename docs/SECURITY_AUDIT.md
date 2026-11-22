# Security audit

Scope: API, harness, GitHub import, voice/realtime WebSockets, web, Supabase migrations, secrets. Done from code and
local tests only (no requests to production). Tests: `api/tests/test_security_audit.py`,
`harness/tests/test_shell_injection.py`, `harness/tests/test_forms.py::test_adb_text_neutralises_every_shell_metacharacter`.

## Access model (the "smallest safe change")

- Run ids are now 128-bit (`uuid4().hex`, 32 chars; was 12 hex). A run id is the share capability for read links
  (report, findings, artifacts, live view), so those stay open to anyone holding the link.
- A run created with a verified token is owned by that user (`runs.user_id`). Only the owner may `cancel`, `retry`,
  answer live `input`, or request a `brief`; others get 404.
- `GET /api/runs` lists only the caller's runs. Without a valid token it returns `[]` when accounts are configured
  (`SUPABASE_URL` set). With no `SUPABASE_URL` (local dev) it still lists everything.
- Guests are Supabase anonymous users with a token, so they own and list their runs like anyone else. A run made with
  no token at all has no owner and its id is the capability.
- Voice/realtime tools (`list_runs`, name lookup, finding lookup) only see runs the session's user may list.

## Findings

| # | Sev | Where | Finding | Status |
| -: | :-- | :--- | :--- | :--- |
| 1 | High | `api/app/routes/runs.py` `list_runs` | Anonymous `GET /api/runs` listed ALL runs and ids, making every run enumerable and then cancellable/retryable/readable | Fixed (owner-scoped list, `app/access.py`) |
| 2 | High | `routes/runs.py` cancel/retry, `routes/live.py` input, `routes/insights.py` brief | State-changing and costly calls were unauthenticated by run id | Fixed (owner gate, 404 on mismatch) |
| 3 | High | `api/app/voice/tools.py` `list_runs`, `_resolve_run`, `_find_finding` via `/ws/voice` and `/ws/realtime` | The voice agent could list and read every user's runs over an unauthenticated socket | Fixed (`ScopedService`) |
| 4 | High | `harness/harness/forms.py` `adb_text` | `adb shell` joins args into one device shell line; only space and `%` were escaped, so `;`, `$()`, backticks, quotes and newlines in typed text (user answers, LLM `fill` text, test credentials) ran as device commands | Fixed (`shlex.quote`) |
| 5 | Medium | `harness/harness/crawler.py`, `security.py` | Activity/component names (from the APK manifest or `resolve-activity` output) went unquoted into `am start -n` etc.; a malicious manifest could inject device shell commands | Fixed (quoted). Impact limited to the disposable test device |
| 6 | Medium | `routes/runs.py` `artifact` | Any file under the artifacts dir was served with a guessed content type (a `.html` from the device would render as HTML on the API origin) | Fixed: extension allow-list, `text/plain` for xml/txt/log, `nosniff`, `CSP: sandbox`, `attachment` for non-media |
| 7 | Medium | `api/app/github_import.py` `download_apk` | `follow_redirects=True` on the asset URL: no host check on redirects (SSRF to internal hosts/metadata) | Fixed: manual redirects, https and GitHub hosts only, token sent only to `api.github.com`, max 4 hops |
| 8 | Medium | `github_import.py` `parse_repo_url`/`find_apk` | Release tag from the URL was interpolated into an `api.github.com` path (`..` segments reach other API paths with the server token) | Fixed (reject `.`/`..`/`%`/`\`, `quote` the tag) |
| 9 | Medium | `routes/runs.py` create, `imports.py`, `insights.py` brief | No rate limits on run creation, import and the LLM+TTS brief | Fixed: per-IP sliding window (10 runs/10 min, 10 imports, 10 retries, 20 briefs). In-memory, single process |
| 10 | Medium | `api/app/analyzer/apk.py` | Zip bomb: androguard inflated a 200 MB upload with no entry/size/ratio cap | Fixed: central-directory check (20k entries, 1.5 GiB, ratio 200) before parsing |
| 11 | Low | run id length | 12 hex ids (48 bits) | Fixed (128-bit). Existing runs keep their short ids; they are no longer listable by others |
| 12 | Low | `main.py` CORS | `allow_methods/headers=*`, no credentials, origins from `CORS_ORIGINS` | Accepted: no cookies are used, so no CSRF/credential exposure. Keep `CORS_ORIGINS` to the Vercel origin in production |
| 13 | Low | `routes/ws_runs.py`, `/ws/voice` | No Origin check on WebSockets; `/ws/voice` has no sign-in | Accepted/deferred: no cookies, so cross-site hijack gains nothing beyond what a direct client has; voice audio buffer is capped (`MAX_BUFFER`), realtime frames capped (`MAX_AUDIO_FRAME_BYTES`) |
| 14 | Low | voice `start_test`/`write_custom_tests` | Voice can start runs with no owner and no rate limit | Deferred (needs the user threaded into `ToolContext`; only the list/read side was scoped) |
| 15 | Low | share-by-link reads | Anyone with a run id can read its report/findings/artifacts | Accepted by design (share links); ids are now unguessable |
| 16 | Info | `web/` | No `dangerouslySetInnerHTML`; `?next=` goes through `safeNext` (rejects `//`, `/\`, absolute URLs); only `NEXT_PUBLIC_*` env read; the Supabase session token lives in the Supabase client's localStorage | No issue / accepted |
| 17 | Info | Supabase migrations | RLS enabled on `runs`, `findings`, `events` (no policies: service role only), and on `profiles`, `conversations`, `messages` with own-row policies. Service-role key is read only in the API (`settings.py`, `storage/supabase.py`) | No issue (policies not exercised against a live database here) |
| 18 | Info | harness | Token compared with `hmac.compare_digest` on every route, bound to 127.0.0.1 (systemd unit), job ids 32-hex, package name regex-validated, artifact path resolved and checked, argv lists (no host shell). The tcpdump sudoers rule is a fixed invocation; `tc` sudo is NOPASSWD for the whole binary (accepted: the harness user is single-purpose) | No issue / accepted |
| 19 | Info | secrets | Searched the tree and git history for `eyJ`, `sb_secret_`, `sk_`, private-key headers, `.pem`/`.env` files: only a test fixture string (`test_rules_security.py`) matches. root `.gitignore` covers `.env*`, `*.pem`, `secrets/`, `data/`; `web/.gitignore` covers `.env*` (there is no `.vercelignore`) | No issue |
| 20 | Info | prompt injection from app screen text | The crawler/agent denylist (`parsers.is_denied`) is applied in code to every tap, including those the LLM asks for (`harness/agent.py`), so on-screen text cannot make the agent press a denied control. Text typed is fixed data or user/credential tokens | No issue |

## Not verified

- Supabase RLS and the token path against a live project; GitHub import against real GitHub; real device behaviour of
  the quoted `input text`/`am start` (tests use mock adb that unquotes like a shell).
- The web app was not rebuilt (no web source changed).
- A reverse proxy must keep appending the true peer to `X-Forwarded-For` (Caddy does); the limiter uses its last entry.
