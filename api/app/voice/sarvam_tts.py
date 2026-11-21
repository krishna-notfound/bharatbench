"""Sarvam text-to-speech (Bulbul) over REST; returns base64 WAV per sentence."""

from __future__ import annotations

import httpx

from app.voice import languages
from app.voice.config import HTTP_TIMEOUT, SARVAM_BASE_URL, TTS_SAMPLE_RATE, tts_model, tts_speaker
from app.voice.sarvam_stt import SarvamError

MAX_CHARS = 2500


def pick_language(text: str, preference: str) -> str:
    return languages.tts_language(text, preference)


async def synthesize(
    text: str, language: str, api_key: str, client: httpx.AsyncClient | None = None
) -> tuple[str, int]:
    """Return (base64 wav, sample_rate) for the text."""
    code = pick_language(text, language)
    body = {
        "text": text[:MAX_CHARS],
        "language_code": code,
        "model": tts_model(),
        "speaker": languages.tts_speaker(code, tts_speaker()),
        "speech_sample_rate": TTS_SAMPLE_RATE,
        "output_audio_codec": "wav",
    }
    owned = client is None
    http = client or httpx.AsyncClient(timeout=HTTP_TIMEOUT)
    try:
        resp = await http.post(
            f"{SARVAM_BASE_URL}/text-to-speech", headers={"api-subscription-key": api_key}, json=body
        )
        if resp.status_code != 200:
            raise SarvamError(f"text-to-speech failed ({resp.status_code})")
        return str(resp.json()["audios"][0]), TTS_SAMPLE_RATE
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        raise SarvamError(f"text-to-speech error: {type(exc).__name__}") from exc
    finally:
        if owned:
            await http.aclose()
