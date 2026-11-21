"""f15 providers with mocks: Sarvam realtime STT (local WS server speaking the documented protocol),
Gnani Prisma (inert without a key; protocol against a local server), STT link reconnect/back-pressure,
Sarvam streaming TTS (respx), fallbacks, speculative turn + merge, finished-job LLM turn."""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
import websockets

from app.realtime import session as session_mod
from app.realtime import stt as stt_mod
from app.realtime import tts as tts_mod
from app.realtime.base import (
    ProviderError,
    SpeechToText,
    SpeechToTextStream,
    STTEvent,
    TranscriptEvent,
)
from app.realtime.stt_link import LinkStatus, SttLink
from app.settings import Settings
from tests.realtime.test_realtime_ws import SARVAM, FakeService, _client, _llm_handler, _start, _text, _until

# ------------------------------------------------------------------ Sarvam realtime STT


async def test_sarvam_streaming_stt_protocol() -> None:
    seen: dict[str, Any] = {"messages": []}

    async def handler(ws: Any) -> None:
        seen["path"] = ws.request.path
        seen["key"] = ws.request.headers.get("Api-Subscription-Key")
        async for raw in ws:
            msg = json.loads(raw)
            seen["messages"].append(msg["event"])
            if msg["event"] == "speech_end":
                await ws.send(json.dumps({"event": "transcript.partial", "text": "hel"}))
                await ws.send(
                    json.dumps(
                        {
                            "event": "transcript.final",
                            "utterance_idx": 0,
                            "text": "hello",
                            "language": "en-IN",
                        }
                    )
                )

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        provider = stt_mod.SarvamStreamingSTT(
            "sk_test", url=f"ws://127.0.0.1:{port}/speech-to-text-realtime/ws"
        )
        stream = await provider.open_stream("hi-IN")
        await stream.begin_utterance()
        await stream.send_audio(b"\x01\x00" * 320)
        await stream.finish()
        events: list[STTEvent] = []
        async for ev in stream.events():
            events.append(ev)
            if isinstance(ev, TranscriptEvent) and ev.is_final:
                break
        await stream.close()
    q = parse_qs(urlparse(seen["path"]).query)
    assert (
        q["language_code"] == ["hi-IN"] and q["endpointing"] == ["manual"] and q["sample_rate"] == ["16000"]
    )
    assert q["model"] == ["saaras:v4"] and q["encoding"] == ["linear16"]
    assert seen["key"] == "sk_test"
    assert seen["messages"] == ["speech_start", "audio_input", "speech_end"]
    assert events[-1] == TranscriptEvent("hello", True, "en-IN")
    assert events[0] == TranscriptEvent("hel", False, None)


async def test_sarvam_streaming_stt_fatal_error_is_surfaced() -> None:
    async def handler(ws: Any) -> None:
        await ws.recv()
        await ws.send(
            json.dumps(
                {"event": "error", "code": "invalid_subscription_key", "is_fatal": True, "message": "bad key"}
            )
        )

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        stream = await stt_mod.SarvamStreamingSTT("x", url=f"ws://127.0.0.1:{port}/").open_stream("en-IN")
        await stream.begin_utterance()
        with pytest.raises(ProviderError) as err:
            async for _ in stream.events():
                pass
        assert err.value.retryable is False
        await stream.close()


# ------------------------------------------------------------------ Gnani Prisma (inert without key)


def test_gnani_is_inert_without_key_and_first_with_key() -> None:
    client = httpx.AsyncClient()
    off = stt_mod.build_stt(Settings(_env_file=None, sarvam_api_key="k"), client)  # type: ignore[call-arg]
    assert [p.name for p in off._providers] == ["sarvam-stt-ws", "sarvam-stt-rest"]
    on = stt_mod.build_stt(Settings(_env_file=None, sarvam_api_key="k", gnani_api_key="g"), client)  # type: ignore[call-arg]
    assert [p.name for p in on._providers] == ["gnani-prisma", "sarvam-stt-ws", "sarvam-stt-rest"]
    rest_only = stt_mod.build_stt(
        Settings(_env_file=None, sarvam_api_key="k", sarvam_stream_stt=False),
        client,  # type: ignore[call-arg]
    )
    assert [p.name for p in rest_only._providers] == ["sarvam-stt-rest"]


def test_frame_chunker_exact_frames() -> None:
    c = stt_mod.FrameChunker()
    assert c.push(b"a" * 1500) == [b"a" * 1024]
    assert c.push(b"b" * 600) == [(b"a" * 476 + b"b" * 548)]
    tail = c.flush()
    assert tail is not None and len(tail) == 1024 and tail.endswith(b"\x00")


async def test_gnani_prisma_protocol_with_mock_server() -> None:
    got: dict[str, Any] = {"frames": [], "cmds": []}

    async def handler(ws: Any) -> None:
        got["headers"] = dict(ws.request.headers)
        async for raw in ws:
            if isinstance(raw, bytes):
                got["frames"].append(len(raw))
            else:
                got["cmds"].append(json.loads(raw)["type"])
                await ws.send(
                    json.dumps({"type": "transcript", "text": "namaste", "detected_language_code": "hi-IN"})
                )

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        s = Settings(  # type: ignore[call-arg]
            _env_file=None, gnani_api_key="gk", gnani_stt_ws_url=f"ws://127.0.0.1:{port}/stt"
        )
        stream = await stt_mod.GnaniPrismaSTT(s).open_stream("auto")
        await stream.send_audio(b"\x01\x00" * 700)  # 1400 B -> one 1024 frame, rest buffered
        await stream.finish()
        ev = await anext(stream.events())
        await stream.close()
    assert got["frames"] == [1024, 1024] and got["cmds"] == ["commit"]
    assert got["headers"]["x-api-key-id"] == "gk" and got["headers"]["language_code"] == "indic-auto"
    assert ev == TranscriptEvent("namaste", True, "hi-IN")


# ------------------------------------------------------------------ STT link


class _ScriptedStream(SpeechToTextStream):
    def __init__(self, fail_after: float | None, log: list[Any]) -> None:
        self.fail_after, self.log = fail_after, log
        self.q: asyncio.Queue[Any] = asyncio.Queue()

    async def send_audio(self, chunk: bytes) -> None:
        self.log.append(("audio", len(chunk)))

    async def begin_utterance(self) -> None:
        self.log.append("begin")

    async def finish(self) -> None:
        self.log.append("finish")
        await self.q.put(TranscriptEvent("done", True))

    async def events(self) -> AsyncIterator[STTEvent]:
        if self.fail_after is not None:
            await asyncio.sleep(self.fail_after)
            raise ProviderError("fake", "boom", retryable=True)
        while (item := await self.q.get()) is not None:
            yield item

    async def close(self) -> None:
        await self.q.put(None)


class _ScriptedSTT(SpeechToText):
    name = "fake"

    def __init__(self) -> None:
        self.opens = 0
        self.log: list[Any] = []

    async def open_stream(self, language: str) -> SpeechToTextStream:
        self.opens += 1
        return _ScriptedStream(0.05 if self.opens == 1 else None, self.log)


async def test_stt_link_reconnects_with_status_and_orders_commit_after_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.realtime.stt_link.REOPEN_BACKOFF_S", 0.01)
    stt = _ScriptedSTT()
    events: list[Any] = []
    statuses: list[LinkStatus] = []

    async def on_status(s: LinkStatus, e: ProviderError | None) -> None:
        statuses.append(s)

    async def on_event(e: STTEvent) -> None:
        events.append(e)

    link = SttLink(stt, "en-IN", on_event=on_event, on_status=on_status)
    await link.start()
    await asyncio.sleep(0.3)  # first stream fails at 50 ms; second is up
    assert stt.opens == 2 and statuses == [LinkStatus.RECONNECTING, LinkStatus.RESTORED]
    link.begin_utterance()
    link.push_audio(b"\x00" * 640)
    assert link.commit() is True
    await asyncio.sleep(0.1)
    assert stt.log == ["begin", ("audio", 640), "finish"]
    assert events == [TranscriptEvent("done", True)]
    await link.close()


async def test_stt_link_backpressure_drops_oldest_never_blocks() -> None:
    link = SttLink(
        _ScriptedSTT(), "en-IN", on_event=lambda e: asyncio.sleep(0), on_status=lambda s, e: asyncio.sleep(0)
    )
    link._connected = True  # no pump running: the queue must absorb, then drop
    for _ in range(250):
        link.push_audio(b"\x00" * 640)
    assert link._ingress.qsize() == 100 and link.dropped_frames == 150
    assert link.commit() is True


# ------------------------------------------------------------------ TTS


async def test_sarvam_stream_tts_aligns_samples_and_strips_header() -> None:
    wav_header = b"RIFF" + b"\x00" * 4 + b"WAVEfmt " + b"\x00" * 20 + b"data" + b"\x00\x00\x00\x00"
    body = wav_header + b"\x01\x02\x03\x04\x05"  # 5 bytes: odd tail must be carried

    async def chunks() -> AsyncIterator[bytes]:
        yield body[: len(wav_header) + 3]
        yield body[len(wav_header) + 3 :]

    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(f"{SARVAM}/text-to-speech/stream").mock(
            return_value=httpx.Response(200, content=chunks())
        )
        async with httpx.AsyncClient() as client:
            out = [
                c async for c in tts_mod.SarvamStreamTTS(client, "k").synthesize("hello", language="en-IN")
            ]
    req = json.loads(route.calls[0].request.content)
    assert req["output_audio_codec"] == "linear16" and req["speech_sample_rate"] == 24000
    assert b"".join(out) == b"\x01\x02\x03\x04" and all(len(c) % 2 == 0 for c in out)


async def test_tts_falls_back_to_rest_before_first_byte() -> None:
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\x01\x00" * 100)
    with respx.mock() as mock:
        mock.post(f"{SARVAM}/text-to-speech/stream").mock(return_value=httpx.Response(503))
        mock.post(f"{SARVAM}/text-to-speech").mock(
            return_value=httpx.Response(200, json={"audios": [base64.b64encode(buf.getvalue()).decode()]})
        )
        async with httpx.AsyncClient() as client:
            tts = tts_mod.build_tts(Settings(_env_file=None, sarvam_api_key="k"), client)  # type: ignore[call-arg]
            out = [c async for c in tts.synthesize("hello", language="en-IN")]
    assert len(b"".join(out)) == 200 and tts.last_used == "sarvam-tts-rest"


async def test_stt_chain_falls_back_to_next_provider() -> None:
    class Down(SpeechToText):
        name = "down"

        async def open_stream(self, language: str) -> SpeechToTextStream:
            raise ProviderError("down", "no", retryable=True)

    working = _ScriptedSTT()
    chain = stt_mod.FallbackSTT([Down(), working])
    await chain.open_stream("en-IN")
    assert chain.active == "fake"


# ------------------------------------------------------------------ session: speculative turn + merge


class _OneShotStream(SpeechToTextStream):
    """Provider-side endpointing: emits the next scripted final as soon as it hears audio."""

    def __init__(self, finals: list[str]) -> None:
        self.finals = finals
        self.q: asyncio.Queue[Any] = asyncio.Queue()

    async def send_audio(self, chunk: bytes) -> None:
        if self.finals:
            await self.q.put(TranscriptEvent(self.finals.pop(0), True))

    async def finish(self) -> None:
        return None

    async def events(self) -> AsyncIterator[STTEvent]:
        while (item := await self.q.get()) is not None:
            yield item

    async def close(self) -> None:
        await self.q.put(None)


def test_speculative_turn_is_dropped_silently_and_merged(monkeypatch: pytest.MonkeyPatch) -> None:
    finals = ["list my", "runs please"]

    class Fake(SpeechToText):
        name = "fake"

        async def open_stream(self, language: str) -> SpeechToTextStream:
            return _OneShotStream(finals)

    monkeypatch.setattr(session_mod, "build_stt", lambda s, c: Fake())
    users: list[str] = []

    import respx as _respx

    with _respx.mock(assert_all_called=False) as mock:
        mock.post(f"{SARVAM}/text-to-speech").mock(return_value=httpx.Response(500))
        mock.post(f"{SARVAM}/text-to-speech/stream").mock(return_value=httpx.Response(500))

        def llm(req: httpx.Request) -> httpx.Response:
            msgs = json.loads(req.content)["messages"]
            users.append([m for m in msgs if m["role"] == "user"][-1]["content"])
            return _text("Sure, ", "here you go.")

        mock.post(f"{SARVAM}/v1/chat/completions").mock(side_effect=llm)
        client = _client(monkeypatch, FakeService(), endpoint_grace_ms=1500)
        with client.websocket_connect("/ws/realtime") as ws:
            _start(ws)
            import time

            time.sleep(0.3)  # warm-up opens the STT link
            ws.send_json({"v": 2, "type": "input.speech_started"})
            ws.send_bytes(b"\x01\x00" * 320)  # fake endpoints on its own: speculative turn "list my"
            time.sleep(0.3)  # still inside the grace window: nothing may have reached the client
            ws.send_json({"v": 2, "type": "input.speech_started"})  # user keeps talking -> silent drop
            ws.send_bytes(b"\x01\x00" * 320)
            ws.send_json({"v": 2, "type": "input.speech_ended"})
            events = _until(ws, "turn.completed", limit=120)
    types = [e["type"] for e in events]
    assert "turn.cancelled" not in types
    assert [e["text"] for e in events if e["type"] == "transcript.final"] == ["list my runs please"]
    assert users and users[-1] == "list my runs please" and len(users) == 1


# ------------------------------------------------------------------ session: finished job -> LLM turn with get_report


def test_finished_job_note_prefers_get_report_when_tool_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    schema = {
        "type": "function",
        "function": {
            "name": "get_report",
            "description": "d",
            "parameters": {"type": "object", "properties": {}},
        },
    }
    monkeypatch.setattr(session_mod.registry, "TOOL_SCHEMAS", [*session_mod.registry.TOOL_SCHEMAS, schema])
    base = _llm_handler("start_test", {"profiles": ["baseline"]})
    notes: list[str] = []

    class Svc(FakeService):
        def subscribe(self, run_id: str):  # type: ignore[no-untyped-def]
            sub = super().subscribe(run_id)
            sub._events = sub._events[1:]  # straight to done
            return sub

    with respx.mock(assert_all_called=False) as mock:

        def llm(req: httpx.Request) -> httpx.Response:
            msgs = json.loads(req.content)["messages"]
            found = [m["content"] for m in msgs if m["role"] == "system" and "just finished" in m["content"]]
            if found:
                notes.append(found[-1])
                return _text("Done. ", "Score is 40.")
            return base(req)

        mock.post(f"{SARVAM}/v1/chat/completions").mock(side_effect=llm)
        client = _client(monkeypatch, Svc(delay=0.2))
        with client.websocket_connect("/ws/realtime") as ws:
            _start(ws, "text")
            ws.send_json({"v": 2, "type": "user.text", "text": "start a test"})
            _until(ws, "turn.completed")
            assert _until(ws, "job.update")[-1]["status"] == "done"
            assert _until(ws, "turn.completed")[-1]["text"] == "Done. Score is 40."
    assert "run2" in notes[0] and "Call get_report" in notes[0] and "failed" not in notes[0]
