# LLM prompts

Every place the code sends a prompt to an LLM. All use Sarvam's OpenAI-style chat completions unless
`LLM_BASE_URL` points elsewhere (`docs/CONFIG.md`). Line numbers are at the time of writing; search for the symbol
if they moved. Prompt text is code: read it at the pointer, it is not duplicated here.

There are two model settings, and they are not the same variable:
`LLM_MODEL` (default `sarvam-105b`, `api/app/settings.py:18`) is used by explanations, agent tests, the team brief
and the **realtime** voice engine; `SARVAM_CHAT_MODEL` (default `sarvam-105b-conversations`,
`api/app/voice/config.py:10`) is used only by the **REST-era** voice agent (`WS /ws/voice`). See `docs/CONFIG.md`.

| # | Prompt | Where (file:line) | Model / setting | max_tokens, temperature | Purpose | Guardrails |
| -: | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | Voice agent system prompt (`SYSTEM_PROMPT`) with per-turn language rule | `api/app/voice/prompts.py:5` (built by `build_system_prompt` `:53`); sent by `api/app/voice/agent.py:74` | `SARVAM_CHAT_MODEL`, `api/app/voice/sarvam_llm.py:20`; `reasoning_effort` null for `sarvam-105b` (`:26`) | 600, temperature not set (`sarvam_llm.py:21`) | Persona and tool-use rules for the text/REST voice agent | "Never invent results; only report what tools returned"; tools declared from `TOOL_SCHEMAS`, at most `MAX_TOOL_ROUNDS = 4` rounds (`agent.py:17`); no cancel tool (prompt line "Tests always run to completion") |
| 2 | Realtime voice: same system prompt plus `REALTIME_ADDENDUM` | `api/app/realtime/session.py:77` (addendum), assembled at `:775-800` | `LLM_MODEL` via `StreamingLLM` (`session.py:263`, `api/app/realtime/providers.py:174`) | 700, temperature not set (`providers.py:177`) | Short spoken answers, background-job honesty | "never say a test has finished ... unless a job update told you so or get_run_status shows status done"; last tool round is forced `tool_choice: none` (`session.py:788-800`); `MAX_TOOL_ROUNDS = 4` and 20 s tool timeout (`api/app/realtime/registry.py:12-13`) |
| 3 | Realtime job-finished notes (`JOB_FINISHED_NOTE`, `HOW_DONE_REPORT`, `HOW_DONE_FALLBACK`, `HOW_FAILED`) | `api/app/realtime/session.py:61-76` | as row 2 | as row 2 | Make the agent summarise a run when a job update arrives | Failure note: "say honestly what failed (use the error you get, do not invent a cause)" |
| 4 | Language reminder (`language_reminder`) and reply rule (`reply_rule`) | `api/app/voice/prompts.py:63`, `api/app/voice/languages.py:114` | as rows 1-2 | n/a (part of the prompt) | Pin the reply language per message (11 supported languages plus Hinglish) | Keeps technical terms in English |
| 5 | Finding explanation (`SYSTEM_PROMPT`) | `api/app/analyzer/explain.py:29`; request body `:103-112` | `LLM_MODEL`, `LLM_BASE_URL` (`explain.py:55-56`) | 700, 0.2 | One-sentence cause, fix, plain explanation for the top 8 findings | Input is only that finding's JSON; strict-JSON output; output rejected if it names a URL or dotted identifier absent from the input (`validate_grounded`, `:85`); 25 s per call, 30 s total budget; failure keeps deterministic text |
| 6 | Initial agent test suggestions (`SYSTEM_PROMPT`) | `api/app/agent_tests.py:23`; request `:130-139` | `LLM_MODEL` | 900, 0.3 | Propose 3-5 app-specific UI tests from manifest facts | "Use ONLY the app facts given"; output validated by `validate` (`:46`: supported conditions only, unique ids, max 5, `low_storage` excluded); falls back to the deterministic planner on any failure (`:82`) |
| 7 | Custom tests from the user's words (`CUSTOM_SYSTEM_PROMPT`) | `api/app/agent_tests.py:158`; request `:181-190` | `LLM_MODEL` | 900, 0.3 | Turn the user's request (via the `write_custom_tests` tool) into 1-5 tests | Request truncated to 600 chars; never falls back to invented tests; returns an error the agent must read out |
| 8 | Spoken team brief (`_brief_prompt`) | `api/app/insights.py:121`; request `:143-154` | `LLM_MODEL` | 900, 0.3 | 60-second briefing for a non-technical reader, in a chosen language | "Use ONLY the JSON facts provided; never invent numbers, issues or causes"; must state results come from the test lab, not real users; 40 s timeout (`BRIEF_TIMEOUT_S`); LLM failure returns 502, TTS failure returns text only |
| 9 | Device-side agent driver (`SYSTEM_PROMPT`) | `harness/harness/agent.py:37`; request `:91` | harness `LLM_MODEL` / `LLM_BASE_URL` / `LLM_API_KEY` (`harness/harness/settings.py:34-36`) | 300, 0.1 | One UI action per reply (tap, fill, back, done, fail) to check one test | "Never use real personal data; never pay, buy, delete or log out"; taps on denylisted labels are vetoed in code (`is_denied`, `agent.py:166`); test-account password is tokenised before the prompt (`harness/harness/secrets.py:43`, applied at `agent.py:141`); at most `MAX_STEPS = 8` actions, 25 s per call; no key means the tests are skipped with a note |

## Cross-cutting guardrails

- Every LLM call is best-effort and bounded by a timeout; none can fail a run (explanations, agent tests) or they
  surface an honest error (brief, custom tests).
- `<think>...</think>` blocks are stripped before parsing (`explain.py` `parse_output`, `insights.py` `_clean_llm_text`).
- `reasoning_effort` is set to null only when the model is exactly `sarvam-105b` (for latency); every call above
  applies this check (row 9 at `harness/harness/agent.py:93`).
- API keys are read server-side only (`api/app/settings.py`); they are never sent to the browser.
- The quality of the model outputs is **not measured** by any test in this repo; tests mock the LLM and check
  parsing, validation and fallback behaviour.
