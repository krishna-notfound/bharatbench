# Sarvam API notes (researched 2026-11-21 from docs.sarvam.ai; `.md` suffix on any docs URL returns Markdown)

Sources:
- Index: https://docs.sarvam.ai/llms.txt
- STT overview: https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/overview
- STT REST guide: https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/rest-api
- STT reference: https://docs.sarvam.ai/api-reference/speech-to-text/transcribe
- Chat overview: https://docs.sarvam.ai/api/token-factory/chat-completions
- Chat V1 reference: https://docs.sarvam.ai/api-reference/chat/chat-completions-v1
- Sarvam-105B models: https://docs.sarvam.ai/api/token-factory/models/sarvam-105b
- TTS overview: https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/overview
- TTS reference: https://docs.sarvam.ai/api-reference/text-to-speech/convert
- Voices: https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/voices

## Auth
Header `api-subscription-key: <key>` on every endpoint (chat also accepts `Authorization: Bearer`). Base URL `https://api.sarvam.ai`.

## STT (Saaras)
- REST: `POST /speech-to-text`, multipart/form-data: `file`, `model` (`saaras:v4` default/latest), `mode`
  (`transcribe|translate|verbatim|translit|codemix`), `language_code` (`hi-IN`, `en-IN`, ... or `unknown` = auto-detect),
  optional `keyterms` (JSON array, v4 only). Response `{request_id, transcript, language_code, ...}`.
- Limits: REST max 30 s per request (so we chunk utterances into <=30 s WAV pieces, cap 60 s). WAV/MP3/etc accepted; 16 kHz mono recommended.
- Streaming: "Realtime Streaming" WebSocket exists (raw PCM linear16) plus a legacy WS. NOT used: we send one buffered
  utterance per `speech_end` over REST (client VAD already segments), which the spec allows ("else REST").
- We use `mode=codemix` so Hinglish keeps English words in Latin script and Hindi in Devanagari.

## Chat completions
- `POST /v1/chat/completions` (OpenAI-compatible). Models: `sarvam-105b` (128K, reasoning on by default;
  `reasoning_effort: null` turns it off) and `sarvam-105b-conversations` (32K, voice-agent variant, reasoning off).
  `/v2/chat/completions` serves open-weight models (not used).
- **Tool/function calling IS supported**: request `tools: [{type:"function", function:{name, description, parameters(JSON schema)}}]`,
  `tool_choice`; response `choices[0].message.tool_calls[{id, type:"function", function:{name, arguments(JSON string)}}]`,
  `finish_reason: "tool_calls"`; reply with `{role:"tool", tool_call_id, content}` messages. `content` may be null when tool_calls present.
  Therefore the JSON-action fallback is NOT implemented.
- Default model used: `sarvam-105b-conversations` (override with env `SARVAM_CHAT_MODEL`). Docs do not state explicitly that the
  conversations variant honours `tools` (same schema is claimed); if it rejects them set `SARVAM_CHAT_MODEL=sarvam-105b`
  (the code then sends `reasoning_effort: null`). Not verified live (no key during development).
- `max_tokens` default 2048; `n` must be 1. Streaming (SSE) exists but we use non-streaming and split sentences ourselves.

## TTS (Bulbul)
- `POST /text-to-speech` JSON `{text (<=2500 chars), language_code, model, speaker, pace, speech_sample_rate, output_audio_codec}`.
  Response `{request_id, audios: [base64 ...]}`; default codec `wav` (we use wav, 24000 Hz, so the browser's decodeAudioData works).
- Streaming variants: `POST /text-to-speech/stream` (raw audio) and `GET /text-to-speech/ws` (WebSocket, base64 chunks). Not used: we
  synthesize per sentence over REST, which already gives sentence-level latency.
- Models: `bulbul:v3` (API default, 37 named speakers e.g. shubh, priya, simran, kavya, ritu, aditya) and `bulbul:v4-flash`
  (200+ personas like `simran_en_customer`, `shubh_hi_devotional`). We use `bulbul:v3` + speaker `shubh` for hi-IN and en-IN
  (v3 speakers are language-agnostic; both languages accepted). Override with `SARVAM_TTS_MODEL` / `SARVAM_TTS_SPEAKER`.
- Language codes: hi-IN, en-IN, bn-IN, gu-IN, kn-IN, ml-IN, mr-IN, od-IN, pa-IN, ta-IN, te-IN.
- Sample rates (REST): 8000, 16000, 22050 (default), 24000, 32000, 44100, 48000.

## Limits
Rate/concurrency limits are per plan (https://docs.sarvam.ai/api/getting-started/pricing#rate-limits).

## Languages (f17, verified 2026-11-21)
Offered = intersection of STT and TTS. Selector values are BCP-47 codes plus `auto`.

| Language | Code | STT (saaras:v4) | TTS (bulbul:v3) |
| --- | --- | --- | --- |
| English (India) | en-IN | yes | yes |
| Hindi | hi-IN | yes | yes |
| Bengali | bn-IN | yes | yes |
| Tamil | ta-IN | yes | yes |
| Telugu | te-IN | yes | yes |
| Kannada | kn-IN | yes | yes |
| Malayalam | ml-IN | yes | yes |
| Marathi | mr-IN | yes | yes |
| Gujarati | gu-IN | yes | yes |
| Punjabi | pa-IN | yes | yes |
| Odia | od-IN | yes | yes |

- STT supports 23 languages (22 Indian + English): the 11 above plus as-IN, ur-IN, ne-IN, kok-IN, ks-IN, sd-IN, sa-IN,
  sat-IN, mni-IN, brx-IN, mai-IN, doi-IN. They are NOT offered because Bulbul has no voice for them.
  Source: https://docs.sarvam.ai/api/api-guides-tutorials/models/saaras (Language Support table).
- Realtime STT WebSocket takes `language_code` = any of 24 values or `auto` (detected `language` returned on partials/finals only in
  auto). REST takes `unknown` for auto. Source: https://docs.sarvam.ai/api-reference/speech-to-text/realtime
- TTS accepts exactly these 11 codes on both bulbul:v3 and bulbul:v4-flash.
  Sources: https://docs.sarvam.ai/api-reference/text-to-speech/convert and
  https://docs.sarvam.ai/api/api-guides-tutorials/models/bulbul (Language Support).
- bulbul:v3 speakers are not locked to a language; the docs recommend shubh for hi/te/kn/od, rehan for bn, ratan for ta
  (https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/bulbul-v3-best-practices#speaker-selection-by-language).
  We use `shubh` everywhere except bn-IN (`rehan`) and ta-IN (`ratan`); `SARVAM_TTS_SPEAKER` overrides all.
- Chat model sarvam-105b(-conversations): 10 most-spoken Indian languages + English, native script, romanised and code-mixed input
  (https://docs.sarvam.ai/api/token-factory/models/sarvam-105b).
