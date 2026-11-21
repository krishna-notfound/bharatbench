# Oryn pipeline parity (f15 section A)

Reference: `dost-ai/backend/app` (read-only). Provider decision (user): **Sarvam for STT and TTS**; Gnani Prisma is
implemented but inert unless `GNANI_API_KEY` is set; Gnani Timbre is **not used (user chose Sarvam)**.

| Oryn feature | BharatBench status | Where |
| --- | --- | --- |
| Streaming STT while the user speaks (mic frames forwarded live, commit on speech end) | DONE (was: buffer + REST on speech_ended). Sarvam Saaras realtime WS, `endpointing=manual`, `speech_start`/`audio_input`/`speech_end`; verified live | `stt.py` `SarvamStreamingSTT`, `stt_link.py` |
| STT provider order Gnani -> Sarvam WS -> Sarvam REST | DONE. Gnani only when `GNANI_API_KEY` set (mock-tested, never run live: no key); REST buffers the utterance and says so (`streaming=False`) | `stt.py` `build_stt`, `FallbackSTT` |
| `SttLink`: bounded ingress, pump/reader, supervisor reconnect + backoff, RECONNECTING/RESTORED/FAILED | DONE (port). Idle-timeout rotation counts as retryable | `stt_link.py` |
| Bounded queues / back-pressure | DONE: link ingress drops oldest (never blocks WS receive); per-segment audio queues (64 chunks) + sentence queue (4) stall segmenter -> LLM read | `stt_link.py`, `session.py` `_Speaker` |
| Streaming TTS, first audio fast | DONE. Sarvam `POST /text-to-speech/stream` (`linear16`, 24 kHz, chunked); REST fallback before first byte. Sarvam TTS WebSocket NOT used: HTTP stream already gives first-byte audio and cancels by closing the response | `tts.py` |
| Gnani Timbre TTS (keep-alive pool, account semaphore) | NOT USED (user chose Sarvam). Shared keep-alive `httpx` client; sentence concurrency semaphore (2) | - |
| Warm-up on session.start (STT link, TTS connection, history) | DONE: STT link opens and TTS TLS connection warms in the background after `session.ready`; history loads in handshake | `session.py` `_warm_up` |
| Speculative turn on final transcript + endpoint grace (180 ms) | DONE: a final with no browser speech-end verdict starts a turn behind an audio gate (`endpoint_grace_ms`); the LLM request runs during the grace, nothing client-visible is sent until confirmed | `turns.py` `confirm`, `session.py` `_send_text` gate, `_preamble` |
| Merge if the user keeps talking | DONE: speech_started while speculative drops the turn silently (no `turn.cancelled`, history popped), words kept as prefix and merged into the next transcript; prefix flush after 1.5 s | `session.py` `_on_speech_started`, `_on_final` |
| Contest / backchannel logic | DONE (was present); empty transcript while contested -> `turn.resume`; contest timeout configurable; commit-without-transcript watchdog (10 s) | `interruptions.py`, `session.py` |
| `heard_text` from playback timing (playback.started/finished) | DONE: `playback.started` stamps the turn; heard = sentences whose audio duration <= elapsed; turn stays open until `playback.finished` (fallback: audio duration + 1 s); interrupted turns recorded with what was heard | `session.py` `_heard`, `_finish_generation` |
| Turn lifecycle / generation fence | DONE (was present) | `turns.py` |
| `turn.metrics` (stt, llm ttft, segmentation, tts ttfb, first audio, end-to-end, interrupt->stop) | DONE, additive: also `ttft_ms`, `stt_provider`, `tts_provider`. Sent before `turn.cancelled` so nothing follows the fence | `latency.py`, `session.py` `_send_metrics` |
| Rolling p50 aggregates | DONE in-process (`latency_stats`); no `/metrics` endpoint (not in scope) | `latency.py` |
| Server-side crisis detector, memories, rolling summary, per-user voice catalog, long-form length detector | NOT PORTED: out of scope for BharatBench (no memory store / persona) | - |
| Provider-side partial transcripts to the client | NOT SENT: Sarvam partials are parsed but the client protocol has no event for them (additive-only rule) | `stt.py` |
| BharatBench additions kept | `tool.*`, `job.update`, WORKING. Finished/failed job now starts an LLM turn (reads `get_report`) instead of a scripted line; last tool round uses `tool_choice:"none"` with tools still declared (fixes HTTP 400) | `session.py` |

Gaps: Gnani paths are untested live (no key). Sarvam WS STT in manual endpointing was verified live for hi/en;
codemix output returns Latin script for Hindi speech. Pre-`speech_start` preroll frames are forwarded as-is.
