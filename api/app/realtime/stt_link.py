"""The conversation's connection to speech-to-text (port of Oryn conversation/stt_link.py).

Audio enters through a bounded, non-blocking queue (the WebSocket receive loop never waits on the
provider); a pump task writes it in order; a reader task hands provider events to the session; a
supervisor reopens the stream when it fails or ends, with backoff. While the stream is down audio is
dropped (it is real time and stale a second later) and the session is told through `on_status`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from enum import StrEnum

from app.realtime.base import ProviderError, SpeechToText, SpeechToTextStream, STTEvent

log = logging.getLogger(__name__)

INGRESS_FRAMES = 100  # ~2 s of 20 ms frames; beyond that the oldest audio is dropped
STABLE_AFTER_S = 5.0
MAX_QUICK_FAILURES = 3
REOPEN_BACKOFF_S = 0.5
_COMMIT = object()
_BEGIN = object()


class LinkStatus(StrEnum):
    RECONNECTING = "reconnecting"
    RESTORED = "restored"
    FAILED = "failed"


EventHandler = Callable[[STTEvent], Awaitable[None]]
StatusHandler = Callable[[LinkStatus, ProviderError | None], Awaitable[None]]


class SttLink:
    def __init__(
        self, stt: SpeechToText, language: str, *, on_event: EventHandler, on_status: StatusHandler
    ) -> None:
        self._stt = stt
        self._language = language
        self._on_event = on_event
        self._on_status = on_status
        self._ingress = asyncio.Queue[object](INGRESS_FRAMES)
        self._connected = False
        self._closed = False
        self._stream: SpeechToTextStream | None = None
        self._supervisor: asyncio.Task[None] | None = None
        self.dropped_frames = 0

    @property
    def connected(self) -> bool:
        return self._connected

    async def start(self) -> None:
        """Open the first stream. Raises ProviderError so the caller can degrade cleanly."""
        self._stream = await self._stt.open_stream(self._language)
        self._connected = True
        self._supervisor = asyncio.create_task(self._supervise(self._stream), name="stt-link")

    def begin_utterance(self) -> None:
        self._enqueue(_BEGIN)

    def push_audio(self, chunk: bytes) -> None:
        self._enqueue(chunk)

    def commit(self) -> bool:
        """The user stopped speaking. Ordered after every frame already pushed. False if the
        link is down (no transcript will come)."""
        if not self._connected:
            return False
        self._enqueue(_COMMIT)
        return True

    async def close(self) -> None:
        self._closed = True
        if self._supervisor is not None:
            self._supervisor.cancel()
            await asyncio.wait({self._supervisor})
        if self._stream is not None:
            await self._close_stream(self._stream)
            self._stream = None

    def _enqueue(self, item: object) -> None:
        if not self._connected:
            self.dropped_frames += isinstance(item, bytes)
            return
        if self._ingress.full():  # back-pressure: drop the oldest audio, never block the receive loop
            self._ingress.get_nowait()
            self.dropped_frames += 1
        self._ingress.put_nowait(item)

    async def _supervise(self, stream: SpeechToTextStream | None) -> None:
        loop = asyncio.get_running_loop()
        quick_failures = 0
        while stream is not None:
            started = loop.time()
            error = await self._serve(stream)
            if self._closed:
                return
            lifetime = loop.time() - started
            broke_early = lifetime <= STABLE_AFTER_S and (error is not None or lifetime < 1.0)
            quick_failures = quick_failures + 1 if broke_early else 0
            if (error is not None and not error.retryable) or quick_failures > MAX_QUICK_FAILURES:
                await self._on_status(LinkStatus.FAILED, error)
                return
            visible = error is not None and lifetime <= STABLE_AFTER_S
            if visible:
                await self._on_status(LinkStatus.RECONNECTING, error)
            stream = await self._reopen()
            if stream is None:
                return
            if visible:
                await self._on_status(LinkStatus.RESTORED, None)

    async def _reopen(self) -> SpeechToTextStream | None:
        await asyncio.sleep(REOPEN_BACKOFF_S)
        try:
            self._stream = await self._stt.open_stream(self._language)
            self._connected = True
        except ProviderError as exc:
            log.warning("stt reopen failed: %s", exc)
            await self._on_status(LinkStatus.FAILED, exc)
            return None
        return self._stream

    async def _serve(self, stream: SpeechToTextStream) -> ProviderError | None:
        self._stream = stream
        reader = asyncio.create_task(self._read(stream), name="stt-reader")
        pump = asyncio.create_task(self._pump(stream), name="stt-pump")
        try:
            done, _ = await asyncio.wait({reader, pump}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            self._connected = False
            while not self._ingress.empty():  # stale audio must not leak into the next stream
                self._ingress.get_nowait()
            for task in (reader, pump):
                task.cancel()
            await asyncio.wait({reader, pump})
        await self._close_stream(stream)
        return next((error for task in done if (error := _failure(task))), None)

    async def _read(self, stream: SpeechToTextStream) -> None:
        async for event in stream.events():
            await self._on_event(event)

    async def _pump(self, stream: SpeechToTextStream) -> None:
        while True:
            item = await self._ingress.get()
            if item is _COMMIT:
                await stream.finish()
            elif item is _BEGIN:
                await stream.begin_utterance()
            else:
                assert isinstance(item, bytes)
                await stream.send_audio(item)

    @staticmethod
    async def _close_stream(stream: SpeechToTextStream) -> None:
        try:
            await stream.close()
        except Exception:
            log.exception("closing stt stream failed")


def _failure(task: asyncio.Task[None]) -> ProviderError | None:
    with contextlib.suppress(asyncio.CancelledError):
        exc = task.exception()
        if isinstance(exc, ProviderError):
            return exc
        if exc is not None:
            log.error("stt task crashed", exc_info=exc)
            return ProviderError("stt", f"internal error: {exc}", retryable=True)
    return None
