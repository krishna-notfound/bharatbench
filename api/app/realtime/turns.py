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

log = logging.getLogger(__name__)
CANCEL_GRACE_S = 2.0


@dataclass(eq=False, slots=True)
class Turn:
    turn_id: int
    generation_id: int
    user_text: str
    from_voice: bool = False
    language: str | None = None
    scripted: str | None = None  # spoken verbatim, no LLM (idle job narration)
    task: asyncio.Task[None] | None = None
    reply: str = ""  # everything the model has produced
    heard: list[str] = field(default_factory=list)  # segments whose audio was fully sent
    audio_started: bool = False
    audible: bool = False  # first audio frame has been sent


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
        scripted: str | None = None,
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
                scripted=scripted,
            )
            self._turn = turn
            self._live_generation = turn.generation_id
            turn.task = asyncio.create_task(self._run(turn), name=f"turn-{turn.turn_id}")
            return turn

    async def cancel(self, reason: str, generation_id: int | None = None) -> bool:
        turn = self._turn
        if turn is None or (generation_id is not None and generation_id != turn.generation_id):
            return False
        # ---- the fence: synchronous up to the first await
        self._turn = None
        self._live_generation = None
        self._settled.clear()
        # ----
        try:
            await self._reap(turn)
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
