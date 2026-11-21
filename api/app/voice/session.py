"""Per-connection voice session: state, audio buffer, turn task, interruption and run narration."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from app.models import RunService
from app.voice import agent, sarvam_stt
from app.voice.sarvam_stt import BYTES_PER_SECOND, MAX_UTTERANCE_SECONDS, SarvamError
from app.voice.tools import ToolContext

log = logging.getLogger(__name__)

Send = Callable[[dict[str, Any]], Awaitable[None]]
NOT_CONFIGURED = "Voice not configured"
MAX_BUFFER = MAX_UTTERANCE_SECONDS * BYTES_PER_SECOND


class VoiceSession:
    def __init__(self, send: Send, get_service: Callable[[], RunService], api_key: str | None) -> None:
        self._send = send
        self._get_service = get_service
        self._send_lock = asyncio.Lock()
        self.api_key = api_key or ""
        self.configured = bool(api_key)
        self.language = "auto"
        self.active_run_id: str | None = None
        self.history: list[dict[str, Any]] = []
        self.turn_id: str | None = None
        self._turn_task: asyncio.Task[None] | None = None
        self._watchers: set[asyncio.Task[None]] = set()
        self._audio = bytearray()

    # ----- accessors used by the agent -----
    def service(self) -> RunService:
        return self._get_service()

    def tool_context(self) -> ToolContext:
        return ToolContext(self.active_run_id)

    async def _raw_send(self, message: dict[str, Any]) -> None:
        async with self._send_lock:
            await self._send(message)

    async def emit(self, turn_id: str | None, message: dict[str, Any]) -> None:
        """Send a message unless its turn has been interrupted/ended (no orphan audio after turn_end)."""
        if turn_id is not None and turn_id != self.turn_id:
            return
        await self._raw_send(message)

    # ----- client messages -----
    async def handle_start(self, language: str, run_id: str | None) -> None:
        if language in ("auto", "hi-IN", "en-IN"):
            self.language = language
        self.active_run_id = run_id
        if not self.configured:
            await self._raw_send({"type": "error", "message": NOT_CONFIGURED})
            return
        await self._raw_send({"type": "ready"})

    def add_audio(self, chunk: bytes) -> None:
        if len(self._audio) < MAX_BUFFER:
            self._audio += chunk[: MAX_BUFFER - len(self._audio)]

    async def speech_end(self) -> None:
        pcm = bytes(self._audio)
        self._audio.clear()
        if not pcm or not await self._check_configured():
            return
        await self._begin_turn(lambda tid: self._voice_turn(tid, pcm))

    async def handle_text(self, text: str) -> None:
        text = text.strip()
        if not text or not await self._check_configured():
            return
        await self._begin_turn(lambda tid: self._text_turn(tid, text))

    async def interrupt(self) -> None:
        task, old_id = self._turn_task, self.turn_id
        self._audio.clear()
        if task is None or old_id is None:
            return
        self.turn_id = None  # gates emit(): nothing from the cancelled turn is sent after this point
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        self._turn_task = None
        await self._raw_send({"type": "turn_end", "turn_id": old_id})

    async def close(self) -> None:
        self.turn_id = None
        for task in [self._turn_task, *self._watchers]:
            if task is not None:
                task.cancel()
        for task in [self._turn_task, *self._watchers]:
            if task is not None:
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    # ----- turns -----
    async def _check_configured(self) -> bool:
        if not self.configured:
            await self._raw_send({"type": "error", "message": NOT_CONFIGURED})
        return self.configured

    async def _begin_turn(self, make: Callable[[str], Awaitable[None]]) -> None:
        await self.interrupt()
        turn_id = uuid.uuid4().hex[:12]
        self.turn_id = turn_id
        self._turn_task = asyncio.create_task(self._turn_wrapper(turn_id, make(turn_id)))

    async def _turn_wrapper(self, turn_id: str, work: Awaitable[None]) -> None:
        try:
            await work
        except SarvamError as exc:
            await self.emit(turn_id, {"type": "error", "message": str(exc)})
        except (LookupError, ValueError, RuntimeError, OSError) as exc:
            log.exception("voice turn failed")
            await self.emit(turn_id, {"type": "error", "message": f"Turn failed: {type(exc).__name__}"})
        if self.turn_id == turn_id:
            await self._raw_send({"type": "turn_end", "turn_id": turn_id})
            self.turn_id = None

    async def _voice_turn(self, turn_id: str, pcm: bytes) -> None:
        text = await sarvam_stt.transcribe(pcm, self.language, self.api_key)
        if not text:
            return
        await self.emit(turn_id, {"type": "transcript", "text": text, "final": True})
        await agent.run_turn(self, turn_id, text)

    async def _text_turn(self, turn_id: str, text: str) -> None:
        await self.emit(turn_id, {"type": "transcript", "text": text, "final": True})
        await agent.run_turn(self, turn_id, text)

    # ----- run narration -----
    def watch_run(self, run_id: str) -> None:
        self.active_run_id = run_id
        task = asyncio.create_task(self._watch(run_id))
        self._watchers.add(task)
        task.add_done_callback(self._watchers.discard)

    async def _watch(self, run_id: str) -> None:
        seen: set[str] = set()
        try:
            async with self.service().subscribe(run_id) as sub:
                async for event in sub:
                    status = _event_status(event.type, event.data)
                    if status in ("running", "done", "failed") and status not in seen:
                        seen.add(status)
                        await self._narrate(run_id, status)
                    if event.type in ("done", "error") or status in ("done", "failed", "cancelled"):
                        return
        except (LookupError, RuntimeError, OSError) as exc:
            log.warning("run watch for %s ended: %s", run_id, type(exc).__name__)

    async def _narrate(self, run_id: str, status: str) -> None:
        message = await self._narration_text(run_id, status)
        await self._raw_send({"type": "run_update", "run_id": run_id, "status": status, "message": message})
        if self.turn_id is None and self.configured:
            self.history.append({"role": "assistant", "content": message})
            await self._begin_turn(lambda tid: agent.speak(self, tid, message, []))

    async def _narration_text(self, run_id: str, status: str) -> str:
        if status == "running":
            return "The test is now running."
        run = await self.service().get_run(run_id)
        if status == "failed":
            return f"The test failed: {run.error}." if run and run.error else "The test failed."
        if run and run.summary:
            critical = run.summary.counts.get("critical", 0)
            return (
                f"Test complete: {critical} critical issues, {run.summary.total_findings} findings in total. "
                "Ask me about the top one."
            )
        return "Test complete. Ask me about the findings."


def _event_status(event_type: str, data: dict[str, Any] | None) -> str | None:
    if event_type == "status" and data:
        return str(data.get("status"))
    if event_type == "done":
        return "done"
    if event_type == "error":
        return "failed"
    return None
