"""Text-to-speech adapters: Sarvam REST-stream (chunked raw PCM, first audio fast) -> Sarvam REST.

Verified against https://docs.sarvam.ai/api-reference/text-to-speech/convert-stream.md:
POST /text-to-speech/stream, `output_audio_codec: linear16` returns a chunked `audio/pcm` body,
sample rates 8000/16000/22050/24000. (Sarvam's TTS WebSocket exists; the HTTP stream already gives
first-byte audio and cancels cleanly by closing the response, so the WS is not used.)
Gnani Timbre: not used (user chose Sarvam).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import aclosing

import httpx

from app.realtime import providers
from app.realtime.base import ProviderError, TextToSpeech
from app.settings import Settings
from app.voice.config import SARVAM_BASE_URL, TTS_SAMPLE_RATE, tts_model, tts_speaker

log = logging.getLogger(__name__)
STREAM_TIMEOUT = httpx.Timeout(30.0, connect=5.0)


def strip_wav_header(data: bytes) -> bytes:
    if not data.startswith(b"RIFF"):
        return data
    marker = data.find(b"data", 12)
    return data[marker + 8 :] if marker != -1 else b""


class SampleAligner:
    """Re-aligns arbitrary byte chunks to whole 16-bit samples, carrying the odd byte over."""

    def __init__(self) -> None:
        self._spare = b""

    def push(self, data: bytes) -> bytes:
        data = self._spare + data
        cut = len(data) - len(data) % 2
        data, self._spare = data[:cut], data[cut:]
        return data


class SarvamStreamTTS(TextToSpeech):
    name = "sarvam-tts-stream"
    sample_rate = TTS_SAMPLE_RATE

    def __init__(self, client: httpx.AsyncClient, api_key: str) -> None:
        self._client, self._key = client, api_key

    async def warm_up(self) -> None:
        """Open the TLS connection now (HEAD-ish): the first reply then skips the handshake."""
        try:
            await self._client.get(SARVAM_BASE_URL, timeout=3.0)
        except httpx.HTTPError:
            pass

    async def synthesize(self, text: str, *, language: str, voice: str | None = None) -> AsyncIterator[bytes]:
        body = {
            "text": text[:3500],
            "language_code": providers.pick_language(text, language),
            "model": tts_model(),
            "speaker": voice or tts_speaker(),
            "speech_sample_rate": self.sample_rate,
            "output_audio_codec": "linear16",
        }
        aligner = SampleAligner()
        first = True
        try:
            async with self._client.stream(
                "POST",
                f"{SARVAM_BASE_URL}/text-to-speech/stream",
                headers={"api-subscription-key": self._key},
                json=body,
                timeout=STREAM_TIMEOUT,
            ) as resp:
                if resp.status_code != 200:
                    await resp.aread()
                    raise ProviderError(
                        self.name, f"HTTP {resp.status_code}", retryable=resp.status_code >= 500
                    )
                async for chunk in resp.aiter_bytes():
                    if first:
                        chunk, first = strip_wav_header(chunk), False
                    if pcm := aligner.push(chunk):
                        yield pcm
        except httpx.HTTPError as exc:
            raise ProviderError(self.name, f"error {type(exc).__name__}", retryable=True) from exc


class SarvamRestTTS(TextToSpeech):
    name = "sarvam-tts-rest"
    sample_rate = TTS_SAMPLE_RATE

    def __init__(self, client: httpx.AsyncClient, api_key: str) -> None:
        self._client, self._key = client, api_key

    async def synthesize(self, text: str, *, language: str, voice: str | None = None) -> AsyncIterator[bytes]:
        pcm, rate = await providers.synthesize(self._client, text, language, self._key)
        self.sample_rate = rate
        yield pcm


class FallbackTTS(TextToSpeech):
    """Tries providers in order per sentence. A provider that fails before its first byte hands
    over to the next; one that fails mid-stream surfaces the error (audio already played)."""

    def __init__(self, providers_: Sequence[TextToSpeech]) -> None:
        self._providers = list(providers_)
        self.name = "+".join(p.name for p in self._providers)
        self.sample_rate = self._providers[0].sample_rate
        self.last_used: str | None = None

    async def synthesize(self, text: str, *, language: str, voice: str | None = None) -> AsyncIterator[bytes]:
        last: ProviderError | None = None
        for provider in self._providers:
            started = False
            try:
                async with aclosing(provider.synthesize(text, language=language, voice=voice)) as chunks:
                    async for pcm in chunks:
                        started = True
                        self.last_used = provider.name
                        yield pcm
                return
            except ProviderError as exc:
                if started:
                    raise
                log.warning("tts provider %s failed: %s", provider.name, exc)
                last = exc
        raise last or ProviderError("tts", "no provider configured")

    async def warm_up(self) -> None:
        await self._providers[0].warm_up()


def build_tts(settings: Settings, client: httpx.AsyncClient) -> FallbackTTS:
    key = settings.sarvam_api_key or ""
    chain: list[TextToSpeech] = []
    if key and settings.sarvam_stream_tts:
        chain.append(SarvamStreamTTS(client, key))
    chain.append(SarvamRestTTS(client, key))
    return FallbackTTS(chain)
