# Configuration

Full variable tables: `README.md` (Environment variables), `api/.env.example`, `harness/.env.example`,
`web/.env.example`. This page covers the easily confused LLM settings.

| Variable | Default | Read at | Used by |
| :--- | :--- | :--- | :--- |
| `LLM_BASE_URL` | `https://api.sarvam.ai/v1` | `api/app/settings.py:17` | explanations, agent tests, team brief, realtime voice |
| `LLM_MODEL` | `sarvam-105b` | `api/app/settings.py:18` | same as above |
| `LLM_API_KEY` | empty, falls back to `SARVAM_API_KEY` | `api/app/settings.py:19,43` | same as above |
| `SARVAM_CHAT_MODEL` | `sarvam-105b-conversations` | `api/app/voice/config.py:10,42` (read from the process environment, not `Settings`) | REST-era voice agent only (`api/app/voice/sarvam_llm.py:20`) |
| `SARVAM_TTS_MODEL`, `SARVAM_TTS_SPEAKER` | `bulbul:v3`, `shubh` | `api/app/voice/config.py` | TTS |
| harness `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` | Sarvam, `sarvam-105b`, unset | `harness/harness/settings.py:34-36` | device-side agent tests; unset key means agent tests are skipped |

Note: `SARVAM_CHAT_MODEL` is read with `os.environ`, so it is set in the process environment; `LLM_MODEL` goes through
pydantic settings and `api/.env`. The two paths use different default models; this is current behaviour, not a
recommendation. `reasoning_effort` is nulled only for the exact model `sarvam-105b`.
