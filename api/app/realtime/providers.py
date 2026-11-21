"""Providers: Sarvam STT (REST on commit), OpenAI-compatible streaming LLM, Sarvam TTS (per clause -> PCM).

STT: Sarvam also offers a streaming WebSocket (docs.sarvam.ai llms.txt); we send one buffered utterance per
`input.speech_ended` over REST (client VAD already segments) - see api/app/voice/SARVAM_NOTES.md.
"""

from __future__ import annotations

import base64
import io
import json
import re
import wave
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.voice import sarvam_stt
from app.voice.config import SARVAM_BASE_URL, TTS_SAMPLE_RATE, tts_model, tts_speaker

TTS_TIMEOUT = 30.0
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


class ProviderError(RuntimeError):
    def __init__(self, provider: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.retryable = retryable


# ------------------------------------------------------------------ STT


async def transcribe(client: httpx.AsyncClient, pcm: bytes, language: str, api_key: str) -> str:
    try:
        return await sarvam_stt.transcribe(pcm, language, api_key, client)
    except sarvam_stt.SarvamError as exc:
        raise ProviderError("stt", str(exc), retryable=True) from exc


# ------------------------------------------------------------------ TTS


def wav_to_pcm(data: bytes) -> tuple[bytes, int]:
    """Decode a WAV into (PCM s16le mono, sample_rate)."""
    with wave.open(io.BytesIO(data), "rb") as w:
        if w.getsampwidth() != 2:
            raise ProviderError("tts", "unexpected sample width")
        pcm = w.readframes(w.getnframes())
        if w.getnchannels() == 2:  # downmix by taking the left channel
            pcm = b"".join(pcm[i : i + 2] for i in range(0, len(pcm), 4))
        return pcm, w.getframerate()


def pick_language(text: str, preference: str | None) -> str:
    if preference in ("hi-IN", "en-IN"):
        return str(preference)
    return "hi-IN" if _DEVANAGARI.search(text) else "en-IN"


async def synthesize(
    client: httpx.AsyncClient, text: str, language: str | None, api_key: str
) -> tuple[bytes, int]:
    body = {
        "text": text[:2500],
        "language_code": pick_language(text, language),
        "model": tts_model(),
        "speaker": tts_speaker(),
        "speech_sample_rate": TTS_SAMPLE_RATE,
        "output_audio_codec": "wav",
    }
    try:
        resp = await client.post(
            f"{SARVAM_BASE_URL}/text-to-speech",
            headers={"api-subscription-key": api_key},
            json=body,
            timeout=TTS_TIMEOUT,
        )
        if resp.status_code != 200:
            raise ProviderError("tts", f"HTTP {resp.status_code}", retryable=resp.status_code >= 500)
        return wav_to_pcm(base64.b64decode(resp.json()["audios"][0]))
    except (httpx.HTTPError, KeyError, IndexError, ValueError, wave.Error) as exc:
        raise ProviderError("tts", f"error {type(exc).__name__}", retryable=True) from exc


# ------------------------------------------------------------------ LLM (OpenAI-compatible SSE)


@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class LLMChunk:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)  # set on the final chunk only
    done: bool = False


@dataclass(slots=True)
class _Pending:
    id: str = ""
    name: str = ""
    args: list[str] = field(default_factory=list)

    def build(self) -> ToolCall:
        try:
            parsed = json.loads("".join(self.args) or "{}")
        except json.JSONDecodeError:
            parsed = {}
        return ToolCall(self.id, self.name, parsed if isinstance(parsed, dict) else {})


class ThinkFilter:
    """Strips <think>...</think> reasoning from streamed deltas (tags may be split across deltas)."""

    def __init__(self) -> None:
        self._buf = ""
        self._inside = False

    def feed(self, delta: str) -> str:
        self._buf += delta
        out: list[str] = []
        while True:
            if self._inside:
                end = self._buf.find("</think>")
                if end < 0:
                    self._buf = self._buf[-8:]
                    break
                self._buf = self._buf[end + 8 :]
                self._inside = False
            else:
                start = self._buf.find("<think>")
                if start >= 0:
                    out.append(self._buf[:start])
                    self._buf = self._buf[start + 7 :]
                    self._inside = True
                    continue
                keep = _partial_tag_len(self._buf)
                out.append(self._buf[: len(self._buf) - keep])
                self._buf = self._buf[len(self._buf) - keep :]
                break
        return "".join(out)

    def flush(self) -> str:
        rest = "" if self._inside else self._buf
        self._buf = ""
        return rest


def _partial_tag_len(buf: str) -> int:
    for n in range(min(len("<think>") - 1, len(buf)), 0, -1):
        if "<think>".startswith(buf[-n:]):
            return n
    return 0


class StreamingLLM:
    def __init__(self, client: httpx.AsyncClient, base_url: str, model: str, api_key: str) -> None:
        self._client = client
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._model = model
        self._key = api_key

    async def stream(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None
    ) -> AsyncIterator[LLMChunk]:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": True,
            "max_tokens": 700,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if self._model == "sarvam-105b":
            body["reasoning_effort"] = None  # reasoning off for low latency
        headers = {"api-subscription-key": self._key, "Authorization": f"Bearer {self._key}"}
        pending: dict[int, _Pending] = {}
        think = ThinkFilter()
        try:
            async with self._client.stream(
                "POST", self._url, headers=headers, json=body, timeout=httpx.Timeout(60.0, read=60.0)
            ) as resp:
                if resp.status_code != 200:
                    await resp.aread()
                    raise ProviderError("llm", f"HTTP {resp.status_code}", retryable=resp.status_code >= 500)
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        choice = json.loads(data)["choices"][0]
                    except (ValueError, KeyError, IndexError):
                        continue
                    delta = choice.get("delta") or {}
                    visible = think.feed(str(delta["content"])) if delta.get("content") else ""
                    if visible:
                        yield LLMChunk(text=visible)
                    for frag in delta.get("tool_calls") or []:
                        slot = pending.setdefault(int(frag.get("index", 0)), _Pending())
                        slot.id = frag.get("id") or slot.id
                        fn = frag.get("function") or {}
                        slot.name = fn.get("name") or slot.name
                        if fn.get("arguments"):
                            slot.args.append(str(fn["arguments"]))
        except httpx.HTTPError as exc:
            raise ProviderError("llm", f"error {type(exc).__name__}", retryable=True) from exc
        if tail := think.flush():
            yield LLMChunk(text=tail)
        calls = [p.build() for _, p in sorted(pending.items()) if p.name]
        for i, c in enumerate(calls):
            if not c.id:
                c.id = f"call_{i}"
        yield LLMChunk(tool_calls=calls, done=True)
