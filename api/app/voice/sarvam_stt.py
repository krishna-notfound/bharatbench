"""Sarvam speech-to-text (Saaras v4) over REST. Audio is 16 kHz mono PCM16, wrapped as WAV in memory."""

from __future__ import annotations

import io
import wave

import httpx

from app.voice.config import HTTP_TIMEOUT, SARVAM_BASE_URL, STT_MODEL

SAMPLE_RATE = 16000
BYTES_PER_SECOND = SAMPLE_RATE * 2
CHUNK_SECONDS = 30  # REST limit per request
MAX_UTTERANCE_SECONDS = 60


class SarvamError(RuntimeError):
    """A Sarvam API call failed."""


def pcm_to_wav(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    return buf.getvalue()


def split_pcm(pcm: bytes) -> list[bytes]:
    """Cap at 60 s and split into <=30 s pieces."""
    pcm = pcm[: MAX_UTTERANCE_SECONDS * BYTES_PER_SECOND]
    size = CHUNK_SECONDS * BYTES_PER_SECOND
    return [pcm[i : i + size] for i in range(0, len(pcm), size)]


async def transcribe(pcm: bytes, language: str, api_key: str, client: httpx.AsyncClient | None = None) -> str:
    """Return the transcript of an utterance; `language` is hi-IN, en-IN or auto."""
    code = "unknown" if language == "auto" else language
    owned = client is None
    http = client or httpx.AsyncClient(timeout=HTTP_TIMEOUT)
    try:
        parts: list[str] = []
        for chunk in split_pcm(pcm):
            if len(chunk) < BYTES_PER_SECOND // 10:
                continue
            resp = await http.post(
                f"{SARVAM_BASE_URL}/speech-to-text",
                headers={"api-subscription-key": api_key},
                data={"model": STT_MODEL, "mode": "codemix", "language_code": code},
                files={"file": ("utterance.wav", pcm_to_wav(chunk), "audio/wav")},
            )
            if resp.status_code != 200:
                raise SarvamError(f"speech-to-text failed ({resp.status_code})")
            text = str(resp.json().get("transcript", "")).strip()
            if text:
                parts.append(text)
        return " ".join(parts)
    except httpx.HTTPError as exc:
        raise SarvamError(f"speech-to-text unreachable: {type(exc).__name__}") from exc
    finally:
        if owned:
            await http.aclose()
