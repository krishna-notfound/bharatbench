# f09 — Realtime voice engine (Oryn port): server (voice-server) + client (voice-client)

**Status:** In progress | **Depends on:** contracts/v2-voice-and-users.md | **Owners:** Sonnet `voice-server`, Sonnet `voice-client`

Purpose: Oryn-quality voice — streaming STT, streaming LLM, clause-level TTS, scheduled playback, smart barge-in
(duck → contest → cancel), generation fence — plus BharatBench tool events and async test jobs.

## voice-server owns
`api/app/realtime/**` (new; port Oryn `websocket/protocol.py`, `session.py`, `conversation/turns.py`, `pipeline.py`,
`streams.py`, `voice/segmenter.py`, `tools/registry.py`, provider base, Sarvam LLM streaming, STT/TTS providers),
`api/tests/realtime/**`, one guarded `include_router` line in `api/app/main.py`, new settings fields in `api/app/settings.py`
(`llm_base_url`, `llm_model`, `llm_api_key` defaulting to Sarvam `https://api.sarvam.ai/v1` / `sarvam-105b` / sarvam key).

- Providers: Sarvam only. Use Sarvam streaming STT/TTS if `api/app/voice/SARVAM_NOTES.md` + https://docs.sarvam.ai confirm
  them; else REST with clause chunking. LLM via an OpenAI-compatible streaming client so DeepSeek is a config swap.
- Tools: reuse `api/app/voice/tools.py` dispatch (7 tools) through the registry; emit `tool.started`/`tool.finished`;
  subscribe to runs started in-session and push `job.update`.
- Persistence: `app.conversations.store.get_conversation_store()` (f10) — guarded import with in-memory fallback.
  Auth: `app.auth.supabase.verify_token` (f10) — guarded likewise.
- Keep the old `/ws/voice` working until the client switches.

## voice-client owns
`web/lib/realtime/**`, `web/lib/audio/**`, `web/public/mic-worklet.js`, `web/components/voice/**`.
Port Oryn `mic-worklet.js`, `MicCapture`, `vadCore`/VAD, `AudioScheduler` + `schedulerCore`, `InterruptionController`,
`GenerationGate`, `RealtimeClient`, `protocol.ts` (+ BharatBench additions), `Captions`/`CaptionTrack`.
Expose `useRealtime()` per contract §4. Rebuild the agent drawer on it: shared voice+text thread, tool chips from
`tool.started`/`tool.finished`, job cards from `job.update`, orb bound to `orbState` + `getLevel`.
Token from `getAccessToken()` (f10) — guarded: if `@/lib/supabase` is missing, send null.

## Acceptance
pytest + ruff (api); lint + tsc + build (web). Barge-in stops playback locally within 300 ms. A text turn over `/ws/realtime`
produces tool.started/finished + streamed text + audio in tests (Sarvam mocked).
