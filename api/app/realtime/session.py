"""One WebSocket connection = one RealtimeSession (Oryn protocol v2 + BharatBench tool/job events).

Lifecycle: accept -> session.start (deadline) -> auth -> conversation -> session.ready -> route frames.
Turns run under TurnManager (generation fence). Every outbound turn event is checked against the live
generation *inside* the send lock, so nothing from a cancelled turn reaches the client.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections.abc import Callable
from typing import Any

import httpx
from fastapi import WebSocket, WebSocketDisconnect

from app.models import RunService
from app.realtime import persistence, protocol, providers, registry
from app.realtime.interruptions import InterruptionArbiter, Verdict
from app.realtime.protocol import (
    ERROR,
    GENERATING,
    INPUT_SAMPLE_RATE,
    INTERRUPTED,
    LISTENING,
    PROCESSING,
    SPEAKING,
    WORKING,
)
from app.realtime.segmenter import SentenceSegmenter
from app.realtime.turns import Turn, TurnManager
from app.settings import Settings
from app.voice.config import TTS_SAMPLE_RATE
from app.voice.prompts import build_system_prompt

log = logging.getLogger(__name__)

HANDSHAKE_TIMEOUT_S = 10.0
MAX_UTTERANCE_BYTES = 60 * INPUT_SAMPLE_RATE * 2
HISTORY_LIMIT = 30
CHUNK_BYTES = TTS_SAMPLE_RATE // 10 * 2  # 100 ms of PCM s16le per binary frame
REALTIME_ADDENDUM = """
Realtime voice rules:
- Tests run in the background. start_test only STARTS a test; never say a test has finished, passed or found \
issues unless a job update told you so or get_run_status shows status done. When a job update arrives you will \
be told in the conversation; until then say it is running.
- Keep replies short and conversational, one to three sentences, plain text.
"""
PROGRESS = {
    "queued": 0.05,
    "analyzing": 0.2,
    "provisioning": 0.35,
    "running": 0.6,
    "scoring": 0.85,
    "done": 1.0,
}


class _CloseSession(Exception):
    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


class _Speaker:
    """Segments streamed text, synthesizes clauses concurrently, and sends audio strictly in order."""

    def __init__(self, sess: RealtimeSession, turn: Turn, tts: bool) -> None:
        self.sess, self.turn, self.tts = sess, turn, tts
        self.seg = SentenceSegmenter()
        self.queue: asyncio.Queue[tuple[int, str, asyncio.Task[tuple[bytes, int]] | None] | None] = (
            asyncio.Queue()
        )
        self.index = 0
        self.seq = 0
        self.sem = asyncio.Semaphore(2)
        self.tts_error_sent = False
        self.worker = asyncio.create_task(self._work())
        self.ticker = asyncio.create_task(self._tick())

    async def feed(self, delta: str) -> None:
        for text in self.seg.feed(delta, time.monotonic()):
            await self._enqueue(text)

    async def flush(self) -> None:
        if text := self.seg.flush():
            await self._enqueue(text)

    async def finish(self) -> None:
        self.ticker.cancel()
        await self.flush()
        await self.queue.put(None)
        await self.worker

    async def abort(self) -> None:
        self.ticker.cancel()
        self.worker.cancel()
        while not self.queue.empty():
            item = self.queue.get_nowait()
            if item is not None and item[2] is not None:
                item[2].cancel()
        await asyncio.gather(self.ticker, self.worker, return_exceptions=True)

    async def _tick(self) -> None:
        while True:
            await asyncio.sleep(0.05)
            for text in self.seg.poll(time.monotonic()):
                await self._enqueue(text)

    async def _enqueue(self, text: str) -> None:
        idx = self.index
        self.index += 1
        await self.sess._emit(self.turn, "text.segment", index=idx, text=text)
        task = asyncio.create_task(self._synth(text)) if self.tts else None
        await self.queue.put((idx, text, task))

    async def _synth(self, text: str) -> tuple[bytes, int]:
        async with self.sem:
            return await providers.synthesize(
                self.sess.http, text, self.sess.language_pref(self.turn), self.sess.settings_key()
            )

    async def _work(self) -> None:
        sess, turn = self.sess, self.turn
        while (item := await self.queue.get()) is not None:
            idx, text, task = item
            if task is None:
                turn.heard.append(text)
                continue
            try:
                pcm, rate = await task
            except providers.ProviderError as exc:
                if not self.tts_error_sent:
                    self.tts_error_sent = True
                    await sess._emit(turn, "pipeline.error", code="tts", message=str(exc), retryable=True)
                turn.heard.append(text)
                continue
            if not turn.audio_started:
                turn.audio_started = True
                if not await sess._emit(turn, "audio.started", sample_rate=rate, encoding="pcm_s16le"):
                    return
                await sess._state(turn, SPEAKING)
            if not await sess._emit(turn, "audio.segment", index=idx, text=text, first_seq=self.seq):
                return
            for off in range(0, len(pcm), CHUNK_BYTES):
                if not await sess._send_audio(turn, self.seq, pcm[off : off + CHUNK_BYTES]):
                    return
                self.seq += 1
                turn.audible = True
            if not await sess._emit(turn, "audio.segment_done", index=idx, samples=len(pcm) // 2):
                return
            turn.heard.append(text)


class RealtimeSession:
    def __init__(self, ws: WebSocket, settings: Settings, get_service: Callable[[], RunService]) -> None:
        self.ws = ws
        self.settings = settings
        self._get_service = get_service
        self.session_id = uuid.uuid4().hex
        self.http = httpx.AsyncClient(timeout=30.0)
        self.store: Any = persistence.get_store()
        self.conversation_id = ""
        self.user: Any = None
        self.mode = "voice"
        self.language = "auto"
        self.history: list[dict[str, Any]] = []
        self.active_run_id: str | None = None
        self._notes: list[str] = []
        self._seq = 0
        self._send_lock = asyncio.Lock()
        self._closed = False
        self._state_name = ""
        self._audio = bytearray()
        self._stt_task: asyncio.Task[None] | None = None
        self._watchers: set[asyncio.Task[None]] = set()
        self._llm = providers.StreamingLLM(
            self.http, settings.llm_base_url, settings.llm_model, settings.llm_key or ""
        )
        self.tm = TurnManager(self._run_turn, self._on_cancelled)
        self.arbiter = InterruptionArbiter(self._contest_expired)

    # ---------------------------------------------------------------- accessors
    def settings_key(self) -> str:
        return self.settings.sarvam_api_key or ""

    def language_pref(self, turn: Turn) -> str | None:
        lang = turn.language or self.language
        return None if lang in (None, "auto") else lang

    # ---------------------------------------------------------------- sending
    async def _send_text(self, type_: str, turn: Turn | None, fence: bool, **fields: Any) -> bool:
        async with self._send_lock:
            if self._closed:
                return False
            if fence and (turn is None or turn.generation_id != self.tm.live_generation):
                return False
            self._seq += 1
            text = protocol.encode_event(
                type_,
                session_id=self.session_id,
                seq=self._seq,
                turn_id=turn.turn_id if turn else None,
                generation_id=turn.generation_id if turn else None,
                **fields,
            )
            try:
                await self.ws.send_text(text)
            except (RuntimeError, WebSocketDisconnect):
                self._closed = True
                return False
            return True

    async def _emit(self, turn: Turn, type_: str, **fields: Any) -> bool:
        """Turn event, dropped unless the turn's generation is still live."""
        return await self._send_text(type_, turn, True, **fields)

    async def _emit_final(self, turn: Turn, type_: str, **fields: Any) -> bool:
        """Turn event sent while ending/cancelling a turn (the fence is already cleared)."""
        return await self._send_text(type_, turn, False, **fields)

    async def _send_global(self, type_: str, **fields: Any) -> bool:
        return await self._send_text(type_, None, False, **fields)

    async def _send_audio(self, turn: Turn, seq: int, pcm: bytes) -> bool:
        async with self._send_lock:
            if self._closed or turn.generation_id != self.tm.live_generation:
                return False
            try:
                await self.ws.send_bytes(protocol.pack_audio_frame(turn.generation_id, seq, pcm))
            except (RuntimeError, WebSocketDisconnect):
                self._closed = True
                return False
            return True

    async def _state(self, turn: Turn | None, state: str, *, final: bool = False) -> None:
        """Announce a state. Mid-turn states are fenced to the turn's generation; end-of-turn
        states (final=True) carry no generation so the client never drops them as stale."""
        if state == self._state_name:
            return
        if turn is None or final:
            sent = await self._send_global("state", state=state)
        else:
            sent = await self._send_text("state", turn, True, state=state)
        if sent:
            self._state_name = state

    # ---------------------------------------------------------------- run loop
    async def run(self) -> None:
        code = 1000
        try:
            await self.ws.accept()
            await self._handshake()
            await self._route_frames()
        except _CloseSession as stop:
            code = stop.code
        except WebSocketDisconnect:
            pass
        except Exception:
            log.exception("realtime session crashed")
            await self._send_global(
                "pipeline.error", code="internal", message="Something went wrong.", retryable=True
            )
            code = 1011
        finally:
            await self._shutdown(code)

    async def _handshake(self) -> None:
        try:
            raw = await asyncio.wait_for(self.ws.receive_text(), HANDSHAKE_TIMEOUT_S)
            msg = protocol.parse_client_message(raw)
        except TimeoutError as exc:
            raise _CloseSession(4408) from exc
        except (ValueError, RuntimeError) as exc:
            raise _CloseSession(4400) from exc
        if msg["type"] != "session.start":
            raise _CloseSession(4400)
        token = msg.get("token") or None
        if msg.get("language") in ("auto", "hi-IN", "en-IN"):
            self.language = msg["language"]
        if msg.get("mode") in ("voice", "text"):
            self.mode = msg["mode"]
        _available, user = await persistence.verify_token(token)
        required = bool(getattr(self.settings, "auth_required", False))
        if user is None and required:
            raise _CloseSession(4401)
        self.user = user
        uid = persistence.user_id(user)
        cid = msg.get("conversation_id")
        try:
            owner_ok = bool(cid) and (await self.store.get_owner(cid)) in (uid, None)
            if cid and owner_ok:
                self.conversation_id = cid
                rows = await self.store.history(cid, HISTORY_LIMIT)
                self.history = [
                    {"role": r["role"], "content": r["content"]}
                    for r in rows
                    if r.get("role") in ("user", "assistant") and r.get("content")
                ]
            else:
                self.conversation_id = await self.store.create(uid, self.mode)
        except Exception:
            log.exception("conversation store failed; using in-memory")
            self.store = persistence.InMemoryStore()
            self.conversation_id = await self.store.create(uid, self.mode)
        await self._send_global(
            "session.ready",
            conversation_id=self.conversation_id,
            input_sample_rate=INPUT_SAMPLE_RATE,
            output_sample_rate=TTS_SAMPLE_RATE,
            protocol=2,
        )
        await self._state(None, LISTENING)

    async def _route_frames(self) -> None:
        while True:
            frame = await self.ws.receive()
            if frame["type"] == "websocket.disconnect":
                return
            if frame.get("bytes") is not None:
                self._on_audio(frame["bytes"])
            elif frame.get("text") is not None and await self._on_message(frame["text"]):
                return

    def _on_audio(self, data: bytes) -> None:
        if len(data) > protocol.MAX_AUDIO_FRAME_BYTES:
            return
        if len(self._audio) < MAX_UTTERANCE_BYTES:
            self._audio += data[: MAX_UTTERANCE_BYTES - len(self._audio)]

    async def _on_message(self, raw: str) -> bool:
        """Handle a client JSON message. True ends the session."""
        try:
            msg = protocol.parse_client_message(raw)
        except ValueError:
            await self._send_global("pipeline.error", code="bad_message", message="Invalid message")
            return False
        kind = msg["type"]
        if kind == "input.speech_started":
            if self.tm.current is not None and self.arbiter.contest() or self.arbiter.contested:
                self.arbiter.hold()
        elif kind == "input.speech_ended":
            self.arbiter.touch()
            pcm = bytes(self._audio)
            self._audio.clear()
            if pcm:
                self._stt_task = asyncio.create_task(self._voice_input(pcm))
        elif kind == "user.text":
            text = str(msg.get("text", "")).strip()[: protocol.MAX_TEXT_CHARS]
            if text:
                self.arbiter.clear()
                await self._start_turn(text, from_voice=False)
        elif kind == "turn.cancel":
            gen = msg.get("generation_id")
            self.arbiter.clear()
            await self.tm.cancel("client", gen if isinstance(gen, int) else None)
        elif kind == "heartbeat":
            await self._send_global("heartbeat")
        elif kind == "session.end":
            return True
        return False

    # ---------------------------------------------------------------- voice input / contest
    async def _voice_input(self, pcm: bytes) -> None:
        try:
            text = await providers.transcribe(self.http, pcm, self.language, self.settings_key())
        except providers.ProviderError as exc:
            self.arbiter.clear()
            await self._send_global("pipeline.error", code="stt", message=str(exc), retryable=True)
            return
        if not text:
            if self.arbiter.contested:
                self.arbiter.clear()
                await self._send_global("turn.resume")
            return
        lang = None if self.language == "auto" else self.language
        await self._send_global("transcript.final", text=text, language=lang)
        if self.arbiter.contested:
            if self.arbiter.judge(text, lang) is Verdict.RESUME:
                turn = self.tm.current
                if turn is not None:
                    await self._emit(turn, "turn.resume")
                return
            await self.tm.cancel("barge_in")
        await self._start_turn(text, from_voice=True)

    async def _contest_expired(self) -> None:
        turn = self.tm.current
        if turn is not None:
            await self._emit(turn, "turn.resume")

    # ---------------------------------------------------------------- turns
    async def _start_turn(self, text: str, *, from_voice: bool) -> None:
        self._flush_notes()
        self.history.append({"role": "user", "content": text})
        await self._persist("user", text)
        await self.tm.begin(
            text, from_voice=from_voice, language=None if self.language == "auto" else self.language
        )

    def _flush_notes(self) -> None:
        for note in self._notes:
            self.history.append({"role": "assistant", "content": note})
        self._notes.clear()

    async def _persist(
        self, role: str, content: str, *, interrupted: bool = False, meta: dict[str, Any] | None = None
    ) -> None:
        try:
            await self.store.append(self.conversation_id, role, content, interrupted=interrupted, meta=meta)
        except Exception:  # noqa: BLE001
            log.warning("conversation persist failed")

    async def _run_turn(self, turn: Turn) -> None:
        speaker: _Speaker | None = None
        try:
            await self._state(turn, PROCESSING)
            speaker = _Speaker(self, turn, tts=self.mode == "voice")
            if turn.scripted is not None:
                turn.reply = turn.scripted
                await self._emit(turn, "text.delta", delta=turn.scripted)
                await speaker.feed(turn.scripted)
            else:
                await self._llm_loop(turn, speaker)
            await speaker.finish()
            await self._complete(turn)
        except asyncio.CancelledError:
            if speaker is not None:
                await asyncio.shield(speaker.abort())
            raise
        except providers.ProviderError as exc:
            if speaker is not None:
                await speaker.abort()
            await self._fail(turn, exc.provider, str(exc), exc.retryable)
        except Exception:
            log.exception("turn failed")
            if speaker is not None:
                await speaker.abort()
            await self._fail(turn, "internal", "Something went wrong.", True)

    async def _llm_loop(self, turn: Turn, speaker: _Speaker) -> None:
        system = {"role": "system", "content": build_system_prompt(self.active_run_id, turn.user_text, turn.language or self.language) + REALTIME_ADDENDUM}
        msgs: list[dict[str, Any]] = [system, *self.history[-HISTORY_LIMIT:]]
        await self._emit(turn, "llm.started")
        for round_no in range(registry.MAX_TOOL_ROUNDS + 1):
            await self._state(turn, GENERATING)
            tools = registry.TOOL_SCHEMAS if round_no < registry.MAX_TOOL_ROUNDS else None
            round_text: list[str] = []
            calls: list[providers.ToolCall] = []
            async for chunk in self._llm.stream(msgs, tools):
                if chunk.text:
                    round_text.append(chunk.text)
                    turn.reply += chunk.text
                    await self._emit(turn, "text.delta", delta=chunk.text)
                    await speaker.feed(chunk.text)
                if chunk.done:
                    calls = chunk.tool_calls
            await speaker.flush()
            if not calls:
                return
            msgs.append(
                {
                    "role": "assistant",
                    "content": "".join(round_text) or None,
                    "tool_calls": [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                        }
                        for c in calls
                    ],
                }
            )
            await self._state(turn, WORKING)
            for call in calls:
                await self._emit(
                    turn,
                    "tool.started",
                    call_id=call.id,
                    name=call.name,
                    label=registry.label_for(call.name),
                    args=call.arguments,
                )
                ok, result, summary = await registry.run_tool(
                    self._get_service(), call.name, call.arguments, registry.ToolContext(self.active_run_id)
                )
                await self._emit(
                    turn, "tool.finished", call_id=call.id, name=call.name, ok=ok, summary=summary
                )
                await self._persist(
                    "tool", summary, meta={"name": call.name, "args": call.arguments, "ok": ok}
                )
                msgs.append(
                    {"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, default=str)}
                )
                if ok and call.name == "start_test" and result.get("run_id"):
                    self.watch_run(str(result["run_id"]))
                elif ok and call.name in ("get_run_status", "list_findings") and call.arguments.get("run_id"):
                    self.active_run_id = self.active_run_id or str(call.arguments["run_id"])
            turn.reply += " "

    async def _complete(self, turn: Turn) -> None:
        async with self.tm.ending(turn) as mine:
            if not mine:
                return
            text = turn.reply.strip()
            if turn.audio_started:
                await self._emit_final(turn, "audio.completed")
            await self._emit_final(turn, "turn.completed", text=text)
            await self._state(turn, LISTENING, final=True)
            if text:
                self.history.append({"role": "assistant", "content": text})
                del self.history[:-HISTORY_LIMIT]
                await self._persist("assistant", text)

    async def _fail(self, turn: Turn, code: str, message: str, retryable: bool) -> None:
        async with self.tm.ending(turn) as mine:
            if not mine:
                return
            await self._emit_final(turn, "pipeline.error", code=code, message=message, retryable=retryable)
            await self._state(turn, ERROR, final=True)
            await self._state(turn, LISTENING, final=True)

    async def _on_cancelled(self, turn: Turn, reason: str) -> None:
        heard = " ".join(turn.heard).strip()
        await self._emit_final(turn, "turn.cancelled", reason=reason, heard_text=heard)
        await self._state(turn, INTERRUPTED, final=True)
        await self._state(turn, LISTENING, final=True)
        if heard:
            self.history.append({"role": "assistant", "content": heard})
            await self._persist("assistant", heard, interrupted=True)

    # ---------------------------------------------------------------- jobs
    def watch_run(self, run_id: str) -> None:
        self.active_run_id = run_id
        task = asyncio.create_task(self._watch(run_id))
        self._watchers.add(task)
        task.add_done_callback(self._watchers.discard)

    async def _watch(self, run_id: str) -> None:
        last: str | None = None
        try:
            async with self._get_service().subscribe(run_id) as sub:
                async for event in sub:
                    status = _event_status(event.type, event.data)
                    if status is None or status == last:
                        continue
                    last = status
                    message = await self._job_message(run_id, status)
                    await self._send_global(
                        "job.update",
                        run_id=run_id,
                        status=status,
                        message=message,
                        progress=PROGRESS.get(status),
                    )
                    if status in ("running", "done", "failed"):
                        await self._narrate(message)
                    if status in ("done", "failed", "cancelled"):
                        return
        except (LookupError, RuntimeError, OSError) as exc:
            log.warning("job watch for %s ended: %s", run_id, type(exc).__name__)

    async def _narrate(self, message: str) -> None:
        """Speak a job update only when idle; otherwise remember it for the model's next turn."""
        stt_busy = self._stt_task is not None and not self._stt_task.done()
        if self.tm.current is None and not stt_busy:
            self.history.append({"role": "assistant", "content": message})
            await self._persist("assistant", message, meta={"job_update": True})
            await self.tm.begin(
                "", scripted=message, language=None if self.language == "auto" else self.language
            )
        else:
            self._notes.append(message)

    async def _job_message(self, run_id: str, status: str) -> str:
        if status == "running":
            return "The test is now running."
        if status in ("queued", "analyzing", "provisioning", "scoring"):
            return f"Test {status}."
        if status == "cancelled":
            return "The test was cancelled."
        try:
            run = await self._get_service().get_run(run_id)
        except (LookupError, RuntimeError, OSError):
            run = None
        if status == "failed":
            return f"The test failed: {run.error}." if run and run.error else "The test failed."
        if run and run.summary:
            critical = run.summary.counts.get("critical", 0)
            return (
                f"Test complete: {critical} critical issues, {run.summary.total_findings} findings in total. "
                "Ask me about the top one."
            )
        return "Test complete. Ask me about the findings."

    # ---------------------------------------------------------------- shutdown
    async def _shutdown(self, code: int) -> None:
        for task in [self._stt_task, *self._watchers]:
            if task is not None:
                task.cancel()
        with contextlib.suppress(Exception):
            await self.arbiter.close()
        with contextlib.suppress(Exception):
            await self.tm.close()
        for task in [self._stt_task, *self._watchers]:
            if task is not None:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        self._closed = True
        await self.http.aclose()
        with contextlib.suppress(Exception):
            await self.ws.close(code=code)


def _event_status(event_type: str, data: dict[str, Any] | None) -> str | None:
    if event_type == "status" and data:
        return str(data.get("status"))
    if event_type == "done":
        return "done"
    if event_type == "error":
        return "failed"
    return None
