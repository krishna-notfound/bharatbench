"""In-memory pub/sub per run, persisted through Storage. Subscriptions replay history then go live."""

import asyncio
from datetime import UTC, datetime
from typing import Any, Self

from app.models import EventType, RunEvent
from app.storage.base import Storage


class EventSubscription:
    def __init__(self, bus: "EventBus", run_id: str) -> None:
        self._bus = bus
        self._run_id = run_id
        self._queue: asyncio.Queue[RunEvent] = asyncio.Queue()
        self._history: list[RunEvent] = []
        self._last_seq = 0

    async def __aenter__(self) -> Self:
        # Subscribe first, then read history, so no event falls in the gap; dedupe by seq on read.
        self._bus.register(self._run_id, self._queue)
        self._history = await self._bus.storage.list_events(self._run_id, 0)
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._bus.unregister(self._run_id, self._queue)

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> RunEvent:
        while self._history:
            event = self._history.pop(0)
            if event.seq > self._last_seq:
                self._last_seq = event.seq
                return event
        while True:
            event = await self._queue.get()
            if event.seq > self._last_seq:
                self._last_seq = event.seq
                return event


class EventBus:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage
        self._subscribers: dict[str, set[asyncio.Queue[RunEvent]]] = {}
        self._lock = asyncio.Lock()

    def register(self, run_id: str, queue: "asyncio.Queue[RunEvent]") -> None:
        self._subscribers.setdefault(run_id, set()).add(queue)

    def unregister(self, run_id: str, queue: "asyncio.Queue[RunEvent]") -> None:
        subs = self._subscribers.get(run_id)
        if subs is not None:
            subs.discard(queue)
            if not subs:
                self._subscribers.pop(run_id, None)

    async def publish(
        self, run_id: str, type: EventType, message: str, data: dict[str, Any] | None = None
    ) -> RunEvent:
        async with self._lock:
            seq = await self.storage.next_seq(run_id)
            event = RunEvent(
                run_id=run_id, seq=seq, ts=datetime.now(UTC), type=type, message=message, data=data
            )
            await self.storage.add_event(event)
        for queue in list(self._subscribers.get(run_id, ())):
            queue.put_nowait(event)
        return event

    def subscribe(self, run_id: str) -> EventSubscription:
        return EventSubscription(self, run_id)
