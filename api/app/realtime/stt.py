"""Speech-to-text adapters: Gnani Prisma (WS) -> Sarvam Saaras realtime (WS) -> Sarvam REST.

All three implement `SpeechToTextStream`, so `SttLink` (stt_link.py) drives any of them the same way.
Sarvam realtime protocol verified against https://docs.sarvam.ai/api-reference/speech-to-text/transcribe/realtime/ws.md:
GET wss://api.sarvam.ai/speech-to-text-realtime/ws, header `Api-Subscription-Key`, query
language_code/model/mode/endpointing/stream_type/encoding/sample_rate; client JSON `audio_input` (base64),
`speech_start`, `speech_end` (endpointing=manual), `flush`, `end`; server `transcript.partial|final`, `error`.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any
from urllib.parse import urlencode

import httpx
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidStatus

from app.realtime.base import (
    ProviderError,
    SpeechStarted,
    SpeechToText,
    SpeechToTextStream,
    STTEvent,
    TranscriptEvent,
)
from app.settings import Settings
from app.voice import sarvam_stt
from app.voice.config import STT_MODEL

log = logging.getLogger(__name__)

EVENT_QUEUE_SIZE = 64
CONNECT_TIMEOUT_S = 5.0
RETRYABLE_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
SARVAM_STT_WS_URL = "wss://api.sarvam.ai/speech-to-text-realtime/ws"


class _EventQueueStream(SpeechToTextStream):
    """Shared plumbing: a bounded event queue fed by a reader task, drained by `events()`."""

    def __init__(self) -> None:
        self._events: asyncio.Queue[STTEvent | ProviderError | None] = asyncio.Queue(EVENT_QUEUE_SIZE)
        self._closed = False

    async def events(self) -> AsyncIterator[STTEvent]:
        while (item := await self._events.get()) is not None:
            if isinstance(item, ProviderError):
                raise item
            yield item

    def _end_events(self) -> None:
        """Terminate `events()` even if its consumer left the queue full."""
        while True:
            try:
                self._events.put_nowait(None)
                return
            except asyncio.QueueFull:
                self._events.get_nowait()

    async def _emit(self, item: STTEvent | ProviderError | None) -> None:
        await self._events.put(item)


# ------------------------------------------------------------------ Gnani Prisma (port of Oryn gnani_prisma.py)

PRISMA_NAME = "gnani-prisma"
PRISMA_FRAME_BYTES = 1024  # Prisma wants exactly 512 samples per binary frame
PRISMA_MAX_IDLE_S = 900
PRISMA_ERROR_CLOSE_GRACE_S = 1.0
_ABNORMAL_CLOSE = 1006


class FrameChunker:
    """Re-slices arbitrary PCM chunks into fixed-size frames, keeping the remainder."""

    def __init__(self, size: int = PRISMA_FRAME_BYTES) -> None:
        self._size = size
        self._rest = bytearray()

    def push(self, data: bytes) -> list[bytes]:
        self._rest += data
        end = len(self._rest) - len(self._rest) % self._size
        frames = [bytes(self._rest[i : i + self._size]) for i in range(0, end, self._size)]
        del self._rest[:end]
        return frames

    def flush(self) -> bytes | None:
        """The remainder padded with silence to a full frame, or None if there is none."""
        if not self._rest:
            return None
        frame = bytes(self._rest).ljust(self._size, b"\x00")
        self._rest.clear()
        return frame


def close_error(code: int | None, reason: str, server_message: str | None) -> ProviderError | None:
    """Map how a socket ended to an error, or None for a clean end of stream."""
    detail = server_message or reason or f"closed with code {code}"
    if code == 1008:  # bad handshake header/setting (Prisma) or idle timeout (Sarvam)
        return ProviderError(PRISMA_NAME, detail, retryable=False)
    if code in (None, 1000, 1005):
        return ProviderError(PRISMA_NAME, detail, retryable=False) if server_message else None
    return ProviderError(PRISMA_NAME, detail, retryable=True)  # 1001 = session cap; else connection loss


class GnaniPrismaStream(_EventQueueStream):
    def __init__(self, ws: ClientConnection) -> None:
        super().__init__()
        self._ws = ws
        self._chunker = FrameChunker()
        self._failure: ProviderError | None = None
        self._reader = asyncio.create_task(self._read(), name="prisma-reader")

    async def send_audio(self, chunk: bytes) -> None:
        for frame in self._chunker.push(chunk):
            await self._send(frame)

    async def finish(self) -> None:
        """Flush buffered audio and send `commit`: Prisma closes the utterance at once."""
        if (tail := self._chunker.flush()) is not None:
            await self._send(tail)
        await self._send(json.dumps({"type": "commit"}))

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._reader.cancel()
        try:
            await asyncio.wait({self._reader})
        finally:
            with contextlib.suppress(Exception):
                await self._ws.close()
            self._end_events()

    async def _send(self, message: bytes | str) -> None:
        try:
            await self._ws.send(message)
        except ConnectionClosed as exc:
            raise self._failure or ProviderError(PRISMA_NAME, "stream closed", retryable=True) from exc

    async def _read(self) -> None:
        server_message: str | None = None
        try:
            async for raw in self._ws:
                message = json.loads(raw) if isinstance(raw, str) else None
                if not isinstance(message, dict):
                    continue
                if (event := self.to_event(message)) is not None:
                    await self._emit(event)
                elif message.get("type") == "error":
                    server_message = str(message.get("message", "unknown error"))
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(self._ws.wait_closed(), PRISMA_ERROR_CLOSE_GRACE_S)
                    break
            await self._finish_with(
                close_error(self._ws.close_code, self._ws.close_reason or "", server_message)
            )
        except ConnectionClosed as exc:
            code = exc.rcvd.code if exc.rcvd else _ABNORMAL_CLOSE
            reason = exc.rcvd.reason if exc.rcvd else ""
            await self._finish_with(
                close_error(code, reason, server_message)
                or ProviderError(PRISMA_NAME, "stream closed", retryable=True)
            )
        except json.JSONDecodeError as exc:
            await self._finish_with(ProviderError(PRISMA_NAME, f"malformed message: {exc}", retryable=True))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # a reader that dies silently would leave the call deaf
            log.exception("prisma reader crashed")
            await self._finish_with(ProviderError(PRISMA_NAME, f"reader failed: {exc}", retryable=True))

    @staticmethod
    def to_event(message: dict[str, Any]) -> STTEvent | None:
        match message.get("type"):
            case "speech_start":
                return SpeechStarted()
            case "transcript":
                return TranscriptEvent(
                    text=str(message.get("text", "")),
                    is_final=True,  # Prisma only ever emits finals
                    language=message.get("detected_language_code"),
                )
            case _:
                return None

    async def _finish_with(self, error: ProviderError | None) -> None:
        self._failure = error
        if error is not None:
            await self._emit(error)
        await self._emit(None)


class GnaniPrismaSTT(SpeechToText):
    name = PRISMA_NAME

    def __init__(self, settings: Settings) -> None:
        if not settings.gnani_api_key:
            raise ValueError("GNANI_API_KEY is required for Gnani Prisma")
        self._s = settings

    async def open_stream(self, language: str) -> SpeechToTextStream:
        auto = language == "auto"
        headers = {
            "x-api-key-id": str(self._s.gnani_api_key),
            "language_code": "indic-auto" if auto else language,
            "model": "prisma-v3.0" if auto else self._s.gnani_stt_model,
            "x-sample-rate": "16000",
            "format": self._s.gnani_stt_format,
            "x-idle-timeout-sec": str(PRISMA_MAX_IDLE_S),
        }
        try:
            ws = await connect(
                self._s.gnani_stt_ws_url,
                additional_headers=headers,
                open_timeout=CONNECT_TIMEOUT_S,
                ping_interval=None,
            )
        except InvalidStatus as exc:
            status = exc.response.status_code
            raise ProviderError(
                PRISMA_NAME, f"handshake rejected: HTTP {status}", retryable=status in RETRYABLE_STATUSES
            ) from exc
        except (InvalidHandshake, TimeoutError, OSError) as exc:
            raise ProviderError(PRISMA_NAME, f"cannot connect: {exc}", retryable=True) from exc
        return GnaniPrismaStream(ws)


# ------------------------------------------------------------------ Sarvam Saaras realtime WebSocket

SARVAM_NAME = "sarvam-stt-ws"


class SarvamStreamingStream(_EventQueueStream):
    def __init__(self, ws: ClientConnection) -> None:
        super().__init__()
        self._ws = ws
        self._failure: ProviderError | None = None
        self._reader = asyncio.create_task(self._read(), name="sarvam-stt-reader")

    async def begin_utterance(self) -> None:
        await self._send({"event": "speech_start"})

    async def send_audio(self, chunk: bytes) -> None:
        await self._send({"event": "audio_input", "audio": base64.b64encode(chunk).decode("ascii")})

    async def finish(self) -> None:
        await self._send({"event": "speech_end"})

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._reader.cancel()
        try:
            await asyncio.wait({self._reader})
        finally:
            with contextlib.suppress(Exception):
                await self._ws.close()
            self._end_events()

    async def _send(self, payload: dict[str, Any]) -> None:
        try:
            await self._ws.send(json.dumps(payload))
        except ConnectionClosed as exc:
            raise self._failure or ProviderError(SARVAM_NAME, "stream closed", retryable=True) from exc

    async def _read(self) -> None:
        try:
            async for raw in self._ws:
                if not isinstance(raw, str):
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(msg, dict):
                    continue
                match msg.get("event"):
                    case "transcript.final":
                        await self._emit(
                            TranscriptEvent(
                                text=str(msg.get("text", "")),
                                is_final=True,
                                language=msg.get("language"),
                            )
                        )
                    case "transcript.partial":
                        await self._emit(TranscriptEvent(text=str(msg.get("text", "")), is_final=False))
                    case "error":
                        fatal = bool(msg.get("is_fatal"))
                        detail = f"{msg.get('code')}: {msg.get('message')}"
                        if fatal:
                            await self._fail(
                                ProviderError(
                                    SARVAM_NAME, detail, retryable=msg.get("code") == "inactivity_timeout"
                                )
                            )
                            return
                        log.warning("sarvam stt non-fatal error %s", detail)
            await self._fail(self._closed_error())
        except ConnectionClosed:
            await self._fail(self._closed_error())
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("sarvam stt reader crashed")
            await self._fail(ProviderError(SARVAM_NAME, f"reader failed: {exc}", retryable=True))

    def _closed_error(self) -> ProviderError | None:
        code = self._ws.close_code
        if code in (None, 1000, 1005):
            return None
        return ProviderError(
            SARVAM_NAME, f"closed with code {code}", retryable=True
        )  # 1008 = idle timeout: rotate

    async def _fail(self, error: ProviderError | None) -> None:
        self._failure = error
        if error is not None:
            await self._emit(error)
        await self._emit(None)


class SarvamStreamingSTT(SpeechToText):
    name = SARVAM_NAME

    def __init__(self, api_key: str, url: str = SARVAM_STT_WS_URL) -> None:
        self._key = api_key
        self._url = url

    async def open_stream(self, language: str) -> SpeechToTextStream:
        query = urlencode(
            {
                "language_code": language,  # hi-IN | en-IN | auto
                "model": STT_MODEL,
                "mode": "codemix",  # Hinglish keeps English words in Latin script
                "endpointing": "manual",  # the browser VAD delimits turns
                "stream_type": "fast",
                "encoding": "linear16",
                "sample_rate": "16000",
            }
        )
        try:
            ws = await connect(
                f"{self._url}?{query}",
                additional_headers={"Api-Subscription-Key": self._key},
                open_timeout=CONNECT_TIMEOUT_S,
                ping_interval=20,
            )
        except InvalidStatus as exc:
            status = exc.response.status_code
            raise ProviderError(
                SARVAM_NAME, f"handshake rejected: HTTP {status}", retryable=status in RETRYABLE_STATUSES
            ) from exc
        except (InvalidHandshake, TimeoutError, OSError) as exc:
            raise ProviderError(SARVAM_NAME, f"cannot connect: {exc}", retryable=True) from exc
        return SarvamStreamingStream(ws)


# ------------------------------------------------------------------ Sarvam REST (buffered fallback)

REST_NAME = "sarvam-stt-rest"
MAX_BUFFER_BYTES = 60 * 16_000 * 2


class SarvamRestStream(_EventQueueStream):
    streaming = False  # honest: buffers the utterance, transcribes on finish()

    def __init__(self, client: httpx.AsyncClient, api_key: str, language: str) -> None:
        super().__init__()
        self._client, self._key, self._language = client, api_key, language
        self._buf = bytearray()
        self._tasks: set[asyncio.Task[None]] = set()

    async def begin_utterance(self) -> None:
        self._buf.clear()

    async def send_audio(self, chunk: bytes) -> None:
        if len(self._buf) < MAX_BUFFER_BYTES:
            self._buf += chunk[: MAX_BUFFER_BYTES - len(self._buf)]

    async def finish(self) -> None:
        pcm, self._buf = bytes(self._buf), bytearray()
        task = asyncio.create_task(self._transcribe(pcm))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _transcribe(self, pcm: bytes) -> None:
        if not pcm:
            await self._emit(TranscriptEvent("", True))
            return
        try:
            text = await sarvam_stt.transcribe(pcm, self._language, self._key, self._client)
        except sarvam_stt.SarvamError as exc:
            await self._emit(ProviderError(REST_NAME, str(exc), retryable=True))
            return
        await self._emit(TranscriptEvent(text, True))

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for task in tuple(self._tasks):
            task.cancel()
        self._end_events()


class SarvamRestSTT(SpeechToText):
    name = REST_NAME

    def __init__(self, client: httpx.AsyncClient, api_key: str) -> None:
        self._client, self._key = client, api_key

    async def open_stream(self, language: str) -> SpeechToTextStream:
        return SarvamRestStream(self._client, self._key, language)


# ------------------------------------------------------------------ provider order


class FallbackSTT(SpeechToText):
    """Tries providers in order; the first that opens a stream wins (Gnani -> Sarvam WS -> REST)."""

    def __init__(self, providers: Sequence[SpeechToText]) -> None:
        self._providers = list(providers)
        self.name = "+".join(p.name for p in self._providers)
        self.active: str | None = None

    async def open_stream(self, language: str) -> SpeechToTextStream:
        last: ProviderError | None = None
        for provider in self._providers:
            try:
                stream = await provider.open_stream(language)
            except ProviderError as exc:
                log.warning("stt provider %s unavailable: %s", provider.name, exc)
                last = exc
                continue
            self.active = provider.name
            return stream
        raise last or ProviderError("stt", "no provider configured")


def build_stt(settings: Settings, client: httpx.AsyncClient) -> FallbackSTT:
    key = settings.sarvam_api_key or ""
    chain: list[SpeechToText] = []
    if settings.gnani_api_key:
        chain.append(GnaniPrismaSTT(settings))
    if key and settings.sarvam_stream_stt:
        chain.append(SarvamStreamingSTT(key))
    chain.append(SarvamRestSTT(client, key))
    return FallbackSTT(chain)
