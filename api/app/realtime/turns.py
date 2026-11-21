"""Turn lifecycle (ported from Oryn conversation/turns.py): one owner of turn_id/generation_id and cancel.

Hard rule: `live_generation` (the fence every outbound send checks) is cleared synchronously when a turn
is cancelled or ended, with no await in between, so a late send of the old generation is impossible.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

from app.realtime.latency import TurnTimer

log = logging.getLogger(__name__)
CANCEL_GRACE_S = 2.0


@dataclass(eq=False, slots=True)
class Turn:
    turn_id: int
    generation_id: int
    user_text: str
    from_voice: bool = False
    language: str | None = None  # explicit user selection only (None = auto)
    stt_language: str | None = None  # language the STT reported for this voice turn
    scripted: str | None = None  # spoken verbatim, no LLM
    job_note: str | None = None  # system note that triggers an LLM turn with no user text (job finished)
    task: asyncio.Task[None] | None = None
    reply: str = ""  # everything the model has produced
    heard: list[str] = field(default_factory=list)  # segments whose audio was fully sent
    audio_started: bool = False
    audible: bool = False  # first audio frame has been sent
    pending_transcript: str | None = None  # transcript.final to announce once the audio gate opens
    user_persisted: bool = False
    preamble: asyncio.Task[None] | None = None
    timer: TurnTimer = field(default_factory=TurnTimer)
    speculative: bool = False  # started on a final transcript; audio is held until confirmed
    confirmed: asyncio.Event = field(default_factory=asyncio.Event)  # the audio gate
    grace: asyncio.TimerHandle | None = None
    generated: bool = False  # all text produced and all audio sent
    playback_finished: bool = False  # the browser reported it played everything
    audio_bytes: int = 0
    audio_sent_at: float | None = None
    playback_at: float | None = None  # when the browser said audio became audible
    sentence_ends: list[tuple[str, float]] = field(default_factory=list)  # (text, audio secs)


Runner = Callable[[Turn], Coroutine[Any, Any, None]]
CancelHandler = Callable[[Turn, str], Awaitable[None]]


class TurnManager:
    def __init__(self, run: Runner, on_cancelled: CancelHandler) -> None:
        self._run = run
        self._on_cancelled = on_cancelled
        self._turn: Turn | None = None
        self._live_generation: int | None = None
        self._turn_count = 0
        self._generation_count = 0
        self._begin_lock = asyncio.Lock()
        self._settled = asyncio.Event()
        self._settled.set()

    @property
    def live_generation(self) -> int | None:
        return self._live_generation

    @property
    def current(self) -> Turn | None:
        return self._turn

    async def begin(
        self,
        text: str,
        *,
        from_voice: bool = False,
        language: str | None = None,
        stt_language: str | None = None,
        scripted: str | None = None,
        speculative: bool = False,
        grace_s: float = 0.0,
        job_note: str | None = None,
    ) -> Turn:
        async with self._begin_lock:
            await self.cancel("superseded")
            await self._settled.wait()
            self._turn_count += 1
            self._generation_count += 1
            turn = Turn(
                self._turn_count,
                self._generation_count,
                text,
                from_voice=from_voice,
                language=language,
                stt_language=stt_language,
                scripted=scripted,
                speculative=speculative,
            )
            turn.job_note = job_note
            turn.timer.mark("turn_started")
            if speculative:
                turn.grace = asyncio.get_running_loop().call_later(grace_s, self.confirm, turn)
            else:
                turn.confirmed.set()
            self._turn = turn
            self._live_generation = turn.generation_id
            turn.task = asyncio.create_task(self._run(turn), name=f"turn-{turn.turn_id}")
            return turn

    def confirm(self, turn: Turn) -> None:
        """Open the audio gate (idempotent; no-op for a turn that already ended)."""
        self._disarm(turn)
        if self._turn is turn:
            turn.speculative = False
            turn.confirmed.set()

    @staticmethod
    def _disarm(turn: Turn) -> None:
        if turn.grace is not None:
            turn.grace.cancel()
            turn.grace = None

    async def cancel(self, reason: str, generation_id: int | None = None) -> bool:
        turn = self._turn
        if turn is None or (generation_id is not None and generation_id != turn.generation_id):
            return False
        # ---- the fence: synchronous up to the first await
        self._turn = None
        self._live_generation = None
        self._settled.clear()
        self._disarm(turn)
        turn.timer.mark("cancel_requested")
        # ----
        try:
            await self._reap(turn)
            turn.timer.mark("cancel_completed")
            await self._on_cancelled(turn, reason)
        finally:
            self._settled.set()
        return True

    @contextlib.asynccontextmanager
    async def ending(self, turn: Turn) -> AsyncIterator[bool]:
        """Claim the normal end of `turn`. Yields False when a cancel already ended it."""
        if self._turn is not turn:
            yield False
            return
        self._turn = None
        self._live_generation = None
        self._settled.clear()
        self._disarm(turn)
        try:
            yield True
        finally:
            self._settled.set()

    async def close(self) -> None:
        await self.cancel("shutdown")
        await self._settled.wait()

    @staticmethod
    async def _reap(turn: Turn) -> None:
        task = turn.task
        if task is None or task is asyncio.current_task():
            return
        task.cancel()
        _, pending = await asyncio.wait({task}, timeout=CANCEL_GRACE_S)
        if pending:
            log.error("turn did not stop in time", extra={"turn_id": turn.turn_id})
