# f05 — Voice agent (Sarvam STT + LLM tools + TTS, barge-in)

**Status:** Built (merged to main; see docs/FEATURE_MAP.md)  |  **Depends on:** f01, f02 (`get_run_service()`)  |  **Owner:** Sonnet agent `voice`

## Purpose

A real-time voice assistant (Hindi / English / Hinglish) that can start tests, watch progress and explain
findings by calling real tools — not a chatbot that describes what it would do.

## Scope

**In:** `WS /ws/voice` per `contracts/README.md` §5, Sarvam clients, agent loop with tools §6, run
progress narration, interruption, text fallback; browser voice panel (mic capture via AudioWorklet,
VAD, playback queue, barge-in).
**Out:** file upload by voice, auth, Resend.

## Step 0 — research (mandatory, before code)

Read https://docs.sarvam.ai (API reference) and record in `api/app/voice/SARVAM_NOTES.md` with links:
STT model + REST and streaming/WebSocket endpoints and audio format; chat completions endpoint, current
model id(s), whether `tools`/function calling is supported; TTS model (bulbul) endpoint, streaming support,
voices/speakers for hi-IN and en-IN, output format; auth header name (`api-subscription-key`?); limits.
Implement only what the docs confirm. If chat tool calling is not supported, use a JSON-action protocol:
system prompt asks for `{"tool": name, "args": {...}}` or `{"say": "..."}` and parse it strictly.

## Routes / Files

**Owned files:**
- `api/app/voice/__init__.py`, `router.py` (exports `router`), `session.py` (per-connection state + turn
  task), `agent.py` (LLM loop, max 4 tool rounds per turn), `tools.py` (tool schemas + dispatch to
  `RunService`), `sarvam_stt.py`, `sarvam_llm.py`, `sarvam_tts.py`, `prompts.py`, `SARVAM_NOTES.md`
- `api/tests/voice/**` (Sarvam mocked with respx; tool dispatch tests with a fake RunService)
- `web/components/voice/voice-panel.tsx`, `web/components/voice/use-voice-session.ts`,
  `web/components/voice/audio.ts` (capture, resample to 16 kHz PCM16, VAD, playback queue), `web/public/pcm-worklet.js`

**Read-only:** `api/app/models.py` (`RunService`), `api/app/settings.py` (f02; `sarvam_api_key`), `api/app/services.py`
(`get_run_service()`), `web/lib/types.ts`, `web/lib/api.ts` (`API_URL`), `web/components/ui/**`.
f06 mounts `<VoicePanel />` from `@/components/voice/voice-panel` in the root layout.
Until f02 merges, `from app.services import get_run_service` may not exist — import inside the WS handler.

## Behavior

- Session: on `start`, send `ready`; keep conversation history (last 20 messages) + `active_run_id`.
- Audio: buffer PCM until `speech_end`; send to Sarvam STT (streaming endpoint if documented, else REST with a WAV built in memory); emit `transcript` final.
- Turn: LLM with system prompt (`prompts.py`): BharatBench persona, reply in the user's language/script
  mix, short spoken sentences (≤ 2 sentences unless explaining), never invent results — only report tool
  output; when asked to test, call `start_test`; to re-run, use active/most recent run's APK.
- Stream: split LLM output into sentences; for each, emit `assistant_text` then TTS → `audio` (base64) so playback starts after the first sentence.
- Interrupt: `interrupt` cancels the turn task (`asyncio.Task.cancel`), sends `turn_end`; partial assistant text is kept in history marked "(interrupted)".
- Narration: after `start_test` the session subscribes to the run (`RunService.subscribe`) in a background task; on status changes `running`, `done`, `failed` emit `run_update` and, if no turn is active, speak one short sentence (e.g. done → "Test complete: 2 critical issues. Ask me about the top one.").
- Text fallback: `{"type":"text"}` skips STT. If `SARVAM_API_KEY` missing → `error` "Voice not configured" (UI shows text input still works only if LLM key present; otherwise disabled).

Browser panel:
- Floating mic button bottom-right; panel with transcript list, state chip (Idle / Listening / Thinking / Speaking), language select (Auto / हिन्दी / English), text input.
- AudioWorklet captures mic, downsamples to 16 kHz PCM16, 100 ms frames; energy-based VAD (threshold + 600 ms hangover) sends `speech_end`.
- Playback: queue `audio` chunks via Web Audio; if user speech detected while speaking → send `interrupt`, stop all sources, clear queue (barge-in).
- Uses tokens from `context/ui-context.md`; `shadow-lg` allowed on the floating panel.

## Rules and Edge Cases

1. Tool errors are returned to the LLM as `{"error": ...}` and spoken honestly.
2. `cancel_run` only if the user explicitly said cancel/stop/ruko for that run.
3. Max 60 s audio per utterance; drop beyond.
4. Never log raw audio or the API key.

## Tasks

- [ ] Sarvam research notes
- [ ] Sarvam clients (mocked tests)
- [ ] tools + agent loop (fake RunService tests: "test my app on slow network" → start_test called with flaky/budget profiles)
- [ ] WS router + session + interrupt (TestClient websocket test with mocked Sarvam)
- [ ] web voice panel + worklet

## Acceptance Criteria

- [ ] `uv run pytest -q tests/voice` passes.
- [ ] With a real key: typed "list my runs" returns a spoken + text answer from real data; voice utterance in Hindi transcribes and answers; interrupt stops playback.

## Verification

`cd api && uv run pytest -q tests/voice`; web: `cd web && npx tsc --noEmit && npm run lint`.

## Status Log

- 2026-11-21 — Specced.
- 2026-11-21 — Implemented. Sarvam docs researched (`api/app/voice/SARVAM_NOTES.md`): STT `saaras:v4` REST `/speech-to-text`
  (codemix, <=30 s chunks), chat `/v1/chat/completions` with native `tools` (model `sarvam-105b-conversations`,
  override `SARVAM_CHAT_MODEL`), TTS `/text-to-speech` `bulbul:v3` speaker `shubh` wav 24 kHz; auth `api-subscription-key`.
  Tool calling supported, so no JSON-action fallback. `pytest -q tests/voice`: 24 passed (clients, tools, WS turn,
  slow-network start_test, voice utterance, interrupt without orphan audio, missing key, Sarvam failure).
  Web: tsc, lint, build clean. NOT verified against live Sarvam or a real browser/mic (no key/device in dev).
