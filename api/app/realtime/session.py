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
from contextlib import aclosing
from typing import Any

import httpx
from fastapi import WebSocket, WebSocketDisconnect

from app.models import RunService
from app.realtime import persistence, protocol, providers, registry
from app.realtime.base import SpeechStarted, TranscriptEvent
from app.realtime.interruptions import InterruptionArbiter, Verdict
from app.realtime.latency import latency_stats
from app.realtime.protocol import (
    ERROR,
    GENERATING,
    INPUT_SAMPLE_RATE,
    INTERRUPTED,
    LISTENING,
    PROCESSING,
    RECONNECTING,
    SPEAKING,
    WORKING,
)
from app.realtime.segmenter import SentenceSegmenter
from app.realtime.stt import build_stt
from app.realtime.stt_link import LinkStatus, SttLink
from app.realtime.tts import build_tts
from app.realtime.turns import Turn, TurnManager
from app.settings import Settings
from app.voice import languages
from app.voice.config import TTS_SAMPLE_RATE
from app.voice.prompts import build_system_prompt, language_reminder

log = logging.getLogger(__name__)

HANDSHAKE_TIMEOUT_S = 10.0
MAX_UTTERANCE_BYTES = 60 * INPUT_SAMPLE_RATE * 2
HISTORY_LIMIT = 30
CHUNK_BYTES = TTS_SAMPLE_RATE // 10 * 2  # 100 ms of PCM s16le per binary frame
SEGMENT_QUEUE = 4  # bounded sentence queue between segmenter and audio sender
TTS_WARM_UP_TIMEOUT_S = 5.0
RESUMED_HOLD_S = 1.5  # words kept for a continuation that never produces a transcript
FINAL_WATCHDOG_S = 10.0  # commit sent but no transcript came back
PLAYBACK_SLACK_S = 1.0  # fallback end-of-turn if the client never reports playback.finished
_NOT_BY_USER = frozenset({"error", "stt_error", "shutdown", "client"})
JOB_FINISHED_NOTE = (
    "The test for run {run_id} just finished with status {status}. {how} "
    "Keep it to three short spoken sentences, plain text."
)
HOW_DONE_REPORT = (
    "Call get_report for that run and give the user a short spoken summary: the score, the 1-2 biggest "
    "issues, and offer to explain them, suggest fixes or run deeper tests."
)
HOW_DONE_FALLBACK = (
    "Call get_run_status and list_findings for that run and give the user a short spoken summary: the "
    "score, the 1-2 biggest issues, and offer to explain them, suggest fixes or run deeper tests."
)
HOW_FAILED = (
    "Call get_run_status for that run, then say honestly what failed (use the error you get, do not invent "
    "a cause) and offer to retry."
)
REALTIME_ADDENDUM = """
Realtime voice rules:
- Tests run in the background. start_test only STARTS a test; never say a test has finished, passed or found \
issues unless a job update told you so or get_run_status shows status done. When a job update arrives you will \
be told in the conversation; until then say it is running.
- This is a live conversation, so talk the way a friendly colleague would: one to three short sentences, plain text, spoken numbers ("about 45 percent"), and a natural follow-up question when it genuinely helps. Open with a quick human reaction to what they asked ("Sure, let me look", "Good news", "Hmm, that one didn't go well") instead of a formal preamble, and vary your openers from turn to turn.
- Whatever language you reply in, keep technical terms (ANR, APK, logcat, crash, RAM, API) in English.
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


SEG_QUEUE_CHUNKS = 64  # bounded: a slow client back-pressures synthesis, which back-pressures the LLM


class _Seg:
    __slots__ = ("idx", "queue", "task", "text")

    def __init__(self, idx: int, text: str) -> None:
        self.idx, self.text = idx, text
        self.queue: asyncio.Queue[bytes | Exception | None] = asyncio.Queue(SEG_QUEUE_CHUNKS)
        self.task: asyncio.Task[None] | None = None


class _Speaker:
    """Segments streamed text, synthesizes sentences concurrently (streaming TTS, bounded queues),
    and sends audio strictly in order. Time-to-first-audio is marked on the turn timer."""

    def __init__(self, sess: RealtimeSession, turn: Turn, tts: bool) -> None:
        self.sess, self.turn, self.tts = sess, turn, tts
        self.seg = SentenceSegmenter()
        self.queue: asyncio.Queue[_Seg | None] = asyncio.Queue(SEGMENT_QUEUE)
        self.index = 0
        self.seq = 0
        self.sem = asyncio.Semaphore(2)
        self.tts_error_sent = False
        self.segments: list[_Seg] = []
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
        for seg in self.segments:
            if seg.task is not None:
                seg.task.cancel()
        await asyncio.gather(
            self.ticker, self.worker, *[s.task for s in self.segments if s.task], return_exceptions=True
        )

    async def _tick(self) -> None:
        while True:
            await asyncio.sleep(0.05)
            for text in self.seg.poll(time.monotonic()):
                await self._enqueue(text)

    async def _enqueue(self, text: str) -> None:
        idx = self.index
        self.index += 1
        self.turn.timer.mark("first_segment")
        await self.sess._emit(self.turn, "text.segment", index=idx, text=text)
        seg = _Seg(idx, text)
        if self.tts:
            seg.task = asyncio.create_task(self._synth(seg))
        self.segments.append(seg)
        await self.queue.put(seg)  # bounded: stalls the segmenter (and the LLM read) when TTS lags

    async def _synth(self, seg: _Seg) -> None:
        try:
            async with self.sem:
                self.turn.timer.mark("tts_request")
                stream = self.sess.tts.synthesize(
                    seg.text, language=self.sess.tts_language(self.turn, seg.text)
                )
                async with aclosing(stream) as chunks:
                    async for pcm in chunks:
                        self.turn.timer.mark("tts_first_byte")
                        if pcm:
                            await seg.queue.put(pcm)
        except providers.ProviderError as exc:
            await seg.queue.put(exc)
            return
        except Exception as exc:  # noqa: BLE001 - surfaced as a tts error, the turn goes on
            await seg.queue.put(providers.ProviderError("tts", type(exc).__name__, retryable=True))
            return
        await seg.queue.put(None)

    async def _work(self) -> None:
        sess, turn = self.sess, self.turn
        while (seg := await self.queue.get()) is not None:
            if seg.task is None:
                turn.heard.append(seg.text)
                continue
            announced = False
            seg_bytes = 0
            failed = False
            while (item := await seg.queue.get()) is not None:
                if isinstance(item, Exception):
                    failed = True
                    if not self.tts_error_sent:
                        self.tts_error_sent = True
                        await sess._emit(
                            turn, "pipeline.error", code="tts", message=str(item), retryable=True
                        )
                    break
                if not turn.audio_started:
                    turn.audio_started = True
                    if not await sess._emit(
                        turn, "audio.started", sample_rate=sess.tts.sample_rate, encoding="pcm_s16le"
                    ):
                        return
                    await sess._state(turn, SPEAKING)
                if not announced:
                    announced = True
                    if not await sess._emit(
                        turn, "audio.segment", index=seg.idx, text=seg.text, first_seq=self.seq
                    ):
                        return
                for off in range(0, len(item), CHUNK_BYTES):
                    part = item[off : off + CHUNK_BYTES]
                    if not await sess._send_audio(turn, self.seq, part):
                        return
                    self.seq += 1
                    seg_bytes += len(part)
                    turn.audio_bytes += len(part)
                    if not turn.audible:
                        turn.audible = True
                        turn.audio_sent_at = time.monotonic()
                        turn.timer.mark("first_audio_sent")
            turn.sentence_ends.append((seg.text, turn.audio_bytes / max(sess.tts.sample_rate * 2, 1)))
            if announced and not await sess._emit(
                turn, "audio.segment_done", index=seg.idx, samples=seg_bytes // 2
            ):
                return
            if not failed or announced:
                turn.heard.append(seg.text)


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
        self._watchers: set[asyncio.Task[None]] = set()
        self._background: set[asyncio.Task[None]] = set()
        self._llm = providers.StreamingLLM(
            self.http, settings.llm_base_url, settings.llm_model, settings.llm_key or ""
        )
        self.stt = build_stt(settings, self.http)
        self.tts = build_tts(settings, self.http)
        self.link: SttLink | None = None
        self.tm = TurnManager(self._run_turn, self._on_cancelled)
        self.arbiter = InterruptionArbiter(self._contest_expired, timeout_s=settings.contest_timeout_s)
        # What the browser VAD and the STT told us about the user's speech (Oryn engine.py)
        self._user_speaking = False
        self._awaiting_final = False  # commit sent, transcript not back yet
        self._speech_end: float | None = None
        self._prefix = ""  # words of a speculative turn dropped because the user kept talking
        self._prefix_language: str | None = None
        self._prefix_task: asyncio.Task[None] | None = None
        self._watchdog: asyncio.Task[None] | None = None
        self._nodding = False  # the overlap was a backchannel; more segments may follow
        self._finish_pending: list[tuple[str, str]] = []  # (run_id, status) awaiting an idle moment

    # ---------------------------------------------------------------- accessors
    def settings_key(self) -> str:
        return self.settings.sarvam_api_key or ""

    def tts_language(self, turn: Turn, text: str) -> str:
        return providers.pick_language(text, self.language_pref(turn), turn.stt_language, turn.user_text)

    def language_pref(self, turn: Turn) -> str | None:
        lang = turn.language or self.language
        return None if lang in (None, "auto") else lang

    # ---------------------------------------------------------------- sending
    async def _send_text(self, type_: str, turn: Turn | None, fence: bool, **fields: Any) -> bool:
        if fence and turn is not None and not turn.confirmed.is_set():
            await turn.confirmed.wait()  # speculative-turn audio gate (Oryn ENDPOINT_GRACE_MS)
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
        if not turn.confirmed.is_set():
            await turn.confirmed.wait()
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
        if msg.get("language") in languages.SESSION_LANGUAGES:
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
        self._spawn(self._warm_up())  # STT link + TTS connection while the user reads the screen

    def _spawn(self, coro: Any) -> asyncio.Task[None]:
        task = asyncio.create_task(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)
        return task

    async def _warm_up(self) -> None:
        """Open the STT link and TTS connection while the user is still reading the screen."""

        async def tts_warm() -> None:
            try:
                async with asyncio.timeout(TTS_WARM_UP_TIMEOUT_S):
                    await self.tts.warm_up()
            except Exception:  # noqa: BLE001 - the first reply connects on demand instead
                log.warning("tts warm-up failed")

        side = asyncio.create_task(tts_warm())
        if self.mode == "voice":
            self.link = SttLink(
                self.stt,
                self.language,
                on_event=self._on_stt_event,
                on_status=self._on_link_status,
            )
            try:
                await self.link.start()
            except providers.ProviderError as exc:
                self.link = None
                await self._send_global("pipeline.error", code="stt", message=str(exc), retryable=False)
        await side

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
        """Mic frame -> STT link. Never blocks: the link's queue is bounded and drops the oldest."""
        if len(data) > protocol.MAX_AUDIO_FRAME_BYTES or self.link is None:
            return
        self.link.push_audio(data)

    async def _on_message(self, raw: str) -> bool:
        """Handle a client JSON message. True ends the session."""
        try:
            msg = protocol.parse_client_message(raw)
        except ValueError:
            await self._send_global("pipeline.error", code="bad_message", message="Invalid message")
            return False
        kind = msg["type"]
        if kind == "input.speech_started":
            await self._on_speech_started()
        elif kind == "input.speech_ended":
            await self._on_speech_ended()
        elif kind == "user.text":
            text = str(msg.get("text", "")).strip()[: protocol.MAX_TEXT_CHARS]
            if text:
                self._prefix = ""
                self._cancel_prefix_flush()
                self.arbiter.clear()
                await self._start_turn(text, from_voice=False)
        elif kind == "turn.cancel":
            gen = msg.get("generation_id")
            self.arbiter.clear()
            await self.tm.cancel("client", gen if isinstance(gen, int) else None)
        elif kind == "playback.started":
            turn = self.tm.current
            if turn and msg.get("generation_id") == turn.generation_id and turn.playback_at is None:
                turn.playback_at = time.monotonic()
                turn.timer.mark("playback_started")
        elif kind == "playback.finished":
            turn = self.tm.current
            if turn and msg.get("generation_id") == turn.generation_id:
                turn.playback_finished = True  # may arrive before the reply is fully generated
                if turn.generated:
                    await self._complete(turn)
        elif kind == "heartbeat":
            await self._send_global("heartbeat")
        elif kind == "session.end":
            return True
        return False

    # ---------------------------------------------------------------- voice input (Oryn engine.py)
    async def _on_speech_started(self) -> None:
        self._user_speaking = True
        self._speech_end = None
        self._awaiting_final = False
        self._cancel_watchdog()
        self._cancel_prefix_flush()
        self._nodding = False
        turn = self.tm.current
        if turn is not None:
            if turn.speculative:  # never audible: drop it silently, keep its words
                self._prefix = turn.user_text
                await self.tm.cancel("speech_resumed", turn.generation_id)
            elif self.arbiter.contest():
                log.info("turn contested")
        if self.link is not None:
            self.link.begin_utterance()
        self.arbiter.hold()  # the contest cannot lapse while they are still talking

    async def _on_speech_ended(self) -> None:
        self._user_speaking = False
        self.arbiter.touch()  # the transcript is on its way: give it a fresh window
        if self.link is None or not self.link.commit():
            self.arbiter.clear()  # STT is down: nothing will settle the contest
            await self._send_global(
                "pipeline.error", code="stt", message="speech service unavailable", retryable=True
            )
            return
        self._speech_end = time.monotonic()
        self._awaiting_final = True
        self._cancel_watchdog()
        self._watchdog = asyncio.create_task(self._final_watchdog())
        if self._prefix:  # the continuation is over; give its transcript a moment to arrive
            self._schedule_prefix_flush()

    async def _final_watchdog(self) -> None:
        await asyncio.sleep(FINAL_WATCHDOG_S)
        if self._awaiting_final:
            self._awaiting_final = False
            await self._on_final("", None)

    def _cancel_watchdog(self) -> None:
        task = self._watchdog
        if task is not None and task is not asyncio.current_task():
            task.cancel()
        self._watchdog = None

    async def _on_stt_event(self, event: Any) -> None:
        if isinstance(event, TranscriptEvent) and event.is_final:
            self._awaiting_final = False
            self._cancel_watchdog()
            await self._on_final(event.text.strip(), event.language)
        elif isinstance(event, SpeechStarted):
            pass  # the browser VAD drives turns; provider VAD is informational

    async def _on_link_status(self, status: LinkStatus, error: providers.ProviderError | None) -> None:
        self._awaiting_final = False
        if status is LinkStatus.RECONNECTING:
            await self._send_global("pipeline.error", code="stt_error", message=str(error), retryable=True)
            if self._state_name == protocol.LISTENING:
                await self._state(None, RECONNECTING, final=True)
        elif status is LinkStatus.RESTORED:
            if self._state_name == RECONNECTING:
                await self._state(None, LISTENING, final=True)
        else:  # FAILED
            await self._send_global("pipeline.error", code="stt_error", message=str(error), retryable=False)
            await self.tm.cancel("stt_error")
            await self._state(None, ERROR, final=True)

    async def _on_final(self, text: str, language: str | None) -> None:
        arrived = time.monotonic()
        lang = None if self.language == "auto" else self.language
        language = language or lang
        current = self.tm.current
        overlap = self.arbiter.contested or self._nodding
        if overlap and current is not None and not current.speculative:
            # One utterance can arrive as several final segments ("haan", "haan"): each is judged.
            if not text:
                self._nodding = False
                self.arbiter.clear()
                await self._emit(current, "turn.resume")
                return
            await self._send_global("transcript.final", text=text, language=lang)
            if self.arbiter.judge(text, lang) is Verdict.RESUME:
                if not self._nodding:
                    self._nodding = True
                    await self._emit(current, "turn.resume")
                return
            self._nodding = False
            await self.tm.cancel("barge_in", current.generation_id)
            await self._start_turn(
                self._merge_prefix(text), from_voice=True, arrived=arrived, announce=False, stt_language=language
            )
            return
        self._nodding = False
        self.arbiter.clear()
        if not text:
            return
        speculative = self._speech_end is None  # no browser VAD verdict: hold the audio briefly
        if current is not None and current.speculative:
            # The user paused and went on: one utterance, not two.
            self._prefix = current.user_text
            await self.tm.cancel("merged", current.generation_id)
        text = self._merge_prefix(text)
        if self._user_speaking:  # talking again already: wait for the rest
            self._prefix, self._prefix_language = text, language
            self._schedule_prefix_flush()
            return
        await self._start_turn(
            text,
            from_voice=True,
            speculative=speculative,
            arrived=arrived,
            announce=not speculative,
            stt_language=language,
        )

    def _merge_prefix(self, text: str) -> str:
        if self._prefix:
            text = f"{self._prefix} {text}"
            self._prefix = ""
            self._prefix_language = None
        self._cancel_prefix_flush()
        return text

    def _schedule_prefix_flush(self) -> None:
        self._cancel_prefix_flush()
        self._prefix_task = asyncio.create_task(self._flush_prefix())

    def _cancel_prefix_flush(self) -> None:
        task = self._prefix_task
        if task is not None and task is not asyncio.current_task():
            task.cancel()
        self._prefix_task = None

    async def _flush_prefix(self) -> None:
        try:
            await asyncio.sleep(RESUMED_HOLD_S)
            text, self._prefix = self._prefix, ""
            detected, self._prefix_language = self._prefix_language, None
            if text:
                await self._start_turn(text, from_voice=True, stt_language=detected)
        finally:
            if self._prefix_task is asyncio.current_task():
                self._prefix_task = None

    async def _contest_expired(self) -> None:
        turn = self.tm.current
        if turn is not None and not turn.speculative:
            await self._emit(turn, "turn.resume")

    # ---------------------------------------------------------------- turns
    async def _start_turn(
        self,
        text: str,
        *,
        from_voice: bool,
        speculative: bool = False,
        arrived: float | None = None,
        announce: bool = True,
        stt_language: str | None = None,
    ) -> None:
        await self.tm.cancel("superseded")  # a new utterance replaces any reply in flight
        self._flush_notes()
        self.history.append({"role": "user", "content": text})
        language = None if self.language == "auto" else self.language
        if announce and from_voice:
            await self._send_global("transcript.final", text=text, language=language)
        turn = await self.tm.begin(
            text,
            from_voice=from_voice,
            language=language,
            stt_language=stt_language,
            speculative=speculative,
            grace_s=self.settings.endpoint_grace_ms / 1000,
        )
        if speculative:
            turn.pending_transcript = text  # announced once the audio gate opens
        else:
            turn.user_persisted = True
            await self._persist("user", text)
        if from_voice:
            turn.timer.mark("stt_final", arrived)
            if self._speech_end is not None:
                turn.timer.mark("speech_end", self._speech_end)
        self._speech_end = None

    async def _start_job_turn(self, run_id: str, status: str) -> None:
        """A run this session started finished: an LLM turn (no user text) reads the result aloud."""
        if status == "done":
            has_report = any(t["function"]["name"] == "get_report" for t in registry.TOOL_SCHEMAS)
            how = HOW_DONE_REPORT if has_report else HOW_DONE_FALLBACK
        else:
            how = HOW_FAILED
        note = JOB_FINISHED_NOTE.format(run_id=run_id, status=status, how=how)
        self._flush_notes()
        await self.tm.begin("", language=None if self.language == "auto" else self.language, job_note=note)

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

    async def _ready(self, turn: Turn) -> None:
        """Wait for the turn's preamble (transcript.final, PROCESSING, llm.started, GENERATING)."""
        if turn.preamble is not None:
            await turn.preamble

    async def _preamble(self, turn: Turn) -> None:
        if turn.pending_transcript:
            await self._emit(
                turn,
                "transcript.final",
                text=turn.pending_transcript,
                language=None if self.language == "auto" else self.language,
            )
            if not turn.user_persisted:
                turn.user_persisted = True
                await self._persist("user", turn.pending_transcript)
        await self._state(turn, PROCESSING)
        if turn.scripted is None:
            await self._emit(turn, "llm.started")
            await self._state(turn, GENERATING)

    async def _run_turn(self, turn: Turn) -> None:
        speaker: _Speaker | None = None
        turn.preamble = asyncio.create_task(self._preamble(turn))  # runs behind the audio gate
        try:
            speaker = _Speaker(self, turn, tts=self.mode == "voice")
            if turn.scripted is not None:
                await self._ready(turn)
                turn.reply = turn.scripted
                await self._emit(turn, "text.delta", delta=turn.scripted)
                await speaker.feed(turn.scripted)
            else:
                await self._llm_loop(turn, speaker)
            await speaker.finish()
            await self._ready(turn)
            await self._finish_generation(turn)
        except asyncio.CancelledError:
            turn.preamble.cancel()
            if speaker is not None:
                await asyncio.shield(speaker.abort())
            raise
        except providers.ProviderError as exc:
            turn.preamble.cancel()
            if speaker is not None:
                await speaker.abort()
            await self._fail(turn, exc.provider, str(exc), exc.retryable)
        except Exception:
            log.exception("turn failed")
            turn.preamble.cancel()
            if speaker is not None:
                await speaker.abort()
            await self._fail(turn, "internal", "Something went wrong.", True)

    async def _llm_loop(self, turn: Turn, speaker: _Speaker) -> None:
        lang = turn.language or self.language
        stt = turn.stt_language
        system = {
            "role": "system",
            "content": build_system_prompt(self.active_run_id, turn.user_text, lang, stt) + REALTIME_ADDENDUM,
        }
        tail = (
            {"role": "system", "content": turn.job_note}
            if turn.job_note
            else {"role": "system", "content": language_reminder(turn.user_text, lang, stt)}
        )
        msgs: list[dict[str, Any]] = [system, *self.history[-HISTORY_LIMIT:], tail]
        for round_no in range(registry.MAX_TOOL_ROUNDS + 1):
            if self._notes:  # job updates that arrived mid-turn: the model must not contradict them
                msgs.append({"role": "system", "content": "Live job updates: " + " ".join(self._notes)})
            last_round = round_no >= registry.MAX_TOOL_ROUNDS
            if last_round:  # answer from the tool results; tools stay declared (history holds tool calls)
                msgs.append(
                    {
                        "role": "system",
                        "content": "Answer the user now from the tool results above. Do not call more tools.",
                    }
                )
            tools = registry.TOOL_SCHEMAS
            round_text: list[str] = []
            calls: list[providers.ToolCall] = []
            turn.timer.mark("llm_request")
            async for chunk in self._llm.stream(msgs, tools, "none" if last_round else "auto"):
                if chunk.text:
                    turn.timer.mark("llm_first_token")
                await self._ready(turn)
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
                from app.access import scope_service

                scoped = await scope_service(
                    self._get_service(), persistence.user_id(self.user), self.settings
                )
                ok, result, summary = await registry.run_tool(
                    scoped, call.name, call.arguments, registry.ToolContext(self.active_run_id)
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
                elif (
                    ok
                    and call.name in ("get_run_status", "list_findings", "get_report")
                    and call.arguments.get("run_id")
                ):
                    self.active_run_id = self.active_run_id or str(call.arguments["run_id"])
            await self._state(turn, GENERATING)
            turn.reply += " "

    async def _finish_generation(self, turn: Turn) -> None:
        """All text produced and all audio sent. Done now if nothing is left to play, else when the
        browser reports playback.finished (or after the audio's own duration plus slack)."""
        if turn.audio_started:
            await self._emit(turn, "audio.completed")
        await self._emit(turn, "turn.completed", text=turn.reply.strip())
        turn.generated = True
        if not turn.audio_started or turn.playback_finished:
            await self._complete(turn)
        else:
            self._spawn(self._playback_fallback(turn))

    async def _playback_fallback(self, turn: Turn) -> None:
        started = turn.playback_at or turn.audio_sent_at or time.monotonic()
        duration = turn.audio_bytes / max(self.tts.sample_rate * 2, 1)
        await asyncio.sleep(max(0.0, started + duration - time.monotonic()) + PLAYBACK_SLACK_S)
        if self.tm.current is turn:
            await self._complete(turn)

    async def _complete(self, turn: Turn) -> None:
        async with self.tm.ending(turn) as mine:
            if not mine:
                return
            text = turn.reply.strip()
            await self._state(turn, LISTENING, final=True)
            if text:
                self.history.append({"role": "assistant", "content": text})
                del self.history[:-HISTORY_LIMIT]
                await self._persist("assistant", text)
            await self._send_metrics(turn)
        self._schedule_note_drain()

    async def _send_metrics(self, turn: Turn) -> None:
        metrics = turn.timer.metrics()
        if not metrics:
            return
        latency_stats.record(metrics)
        log.info("turn metrics %s", metrics)
        await self._emit_final(
            turn,
            "turn.metrics",
            stt_provider=self.stt.active,
            tts_provider=self.tts.last_used,
            ttft_ms=metrics.get("llm_ttft_ms"),
            **metrics,
        )

    async def _fail(self, turn: Turn, code: str, message: str, retryable: bool) -> None:
        async with self.tm.ending(turn) as mine:
            if not mine:
                return
            await self._ready_quiet(turn)
            await self._emit_final(turn, "pipeline.error", code=code, message=message, retryable=retryable)
            await self._state(turn, ERROR, final=True)
            await self._state(turn, LISTENING, final=True)
        self._schedule_note_drain()

    async def _ready_quiet(self, turn: Turn) -> None:
        if turn.speculative and not turn.confirmed.is_set():
            await turn.confirmed.wait()  # a speculative turn reports nothing the user did not hear

    def _heard(self, turn: Turn) -> tuple[str, bool]:
        """What the user actually received and whether the reply was cut short. For voice, the
        browser's playback start plus the audio duration sent tells which sentences finished playing."""
        full = turn.reply.strip()
        if self.mode == "text":
            return full, True
        started = turn.playback_at or turn.audio_sent_at
        if started is None:
            return "", True
        elapsed = time.monotonic() - started
        if turn.generated and elapsed >= turn.audio_bytes / max(self.tts.sample_rate * 2, 1):
            return full, False
        return " ".join(text for text, end in turn.sentence_ends if end <= elapsed).strip(), True

    async def _on_cancelled(self, turn: Turn, reason: str) -> None:
        if turn.preamble is not None:
            turn.preamble.cancel()
        if turn.speculative:  # never audible: the browser saw nothing, the caller keeps the words
            if self.history and self.history[-1] == {"role": "user", "content": turn.user_text}:
                self.history.pop()
            return
        heard, _cut = self._heard(turn)
        await self._send_metrics(turn)  # before turn.cancelled: nothing of the old generation follows it
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
                    if status == "running":
                        await self._narrate(message)
                    elif status in ("done", "failed"):
                        await self._job_finished(run_id, status)
                    if status in ("done", "failed", "cancelled"):
                        return
        except (LookupError, RuntimeError, OSError) as exc:
            log.warning("job watch for %s ended: %s", run_id, type(exc).__name__)

    def _schedule_note_drain(self) -> None:
        """A job update that landed mid-turn is spoken once the turn ends, so the user never misses it."""
        if (not self._notes and not self._finish_pending) or self._closed:
            return
        task = asyncio.create_task(self._drain_notes())
        self._watchers.add(task)
        task.add_done_callback(self._watchers.discard)

    def _idle(self) -> bool:
        return self.tm.current is None and not self._user_speaking and not self._awaiting_final

    async def _drain_notes(self) -> None:
        if not self._idle():
            return
        if self._finish_pending:
            run_id, status = self._finish_pending.pop(0)
            self._notes.clear()  # the finished-job turn supersedes "running" lines
            await self._start_job_turn(run_id, status)
            return
        message = self._notes[-1]
        self._notes.clear()
        await self._narrate(message)

    async def _job_finished(self, run_id: str, status: str) -> None:
        """done/failed: an LLM turn reads the result (get_report) instead of a scripted line.
        Busy -> queued and started as soon as the session is idle."""
        if self._idle():
            await self._start_job_turn(run_id, status)
        else:
            self._finish_pending.append((run_id, status))

    async def _narrate(self, message: str) -> None:
        """Speak a job update only when idle; otherwise remember it for the model's next turn."""
        if self._idle():
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
        self._cancel_prefix_flush()
        self._cancel_watchdog()
        for task in [*self._watchers, *self._background]:
            task.cancel()
        with contextlib.suppress(Exception):
            await self.arbiter.close()
        with contextlib.suppress(Exception):
            await self.tm.close()
        for task in [*self._watchers, *self._background]:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        if self.link is not None:
            with contextlib.suppress(Exception):
                await self.link.close()
        self._closed = True
        with contextlib.suppress(Exception):
            await self.tts.aclose()
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
