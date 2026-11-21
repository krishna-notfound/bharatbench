"""Sarvam text-to-speech (Bulbul) over REST; returns base64 WAV per sentence."""

from __future__ import annotations

import re

import httpx

from app.voice.config import HTTP_TIMEOUT, SARVAM_BASE_URL, TTS_SAMPLE_RATE, tts_model, tts_speaker
from app.voice.sarvam_stt import SarvamError

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
MAX_CHARS = 2500


def pick_language(text: str, preference: str) -> str:
    if preference in ("hi-IN", "en-IN"):
        return preference
    return "hi-IN" if _DEVANAGARI.search(text) else "en-IN"


async def synthesize(
    text: str, language: str, api_key: str, client: httpx.AsyncClient | None = None
) -> tuple[str, int]:
    """Return (base64 wav, sample_rate) for the text."""
    body = {
        "text": text[:MAX_CHARS],
        "language_code": pick_language(text, language),
        "model": tts_model(),
        "speaker": tts_speaker(),
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
