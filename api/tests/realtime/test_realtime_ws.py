"""WS /ws/realtime end to end with Sarvam mocked (respx) and a fake RunService."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import struct
import wave
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, Self

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from app.models import Run, RunEvent
from app.realtime import router as rt_router
from app.realtime.providers import ThinkFilter
from app.settings import Settings

SARVAM = "https://api.sarvam.ai"
NOW = datetime(2026, 11, 21, tzinfo=UTC)


def _wav_b64(seconds: float = 0.3, rate: int = 24000) -> str:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * int(rate * seconds))
    return base64.b64encode(buf.getvalue()).decode()


def _run(run_id: str, status: str = "done") -> Run:
    return Run(
        id=run_id,
        apk_name="demo.apk",
        status=status,
        profile_ids=["baseline"],
        created_at=NOW,
        updated_at=NOW,  # type: ignore[arg-type]
    )


def _status(run_id: str, seq: int, status: str) -> RunEvent:
    return RunEvent(run_id=run_id, seq=seq, ts=NOW, type="status", message=status, data={"status": status})


class _Sub:
    def __init__(self, events: list[RunEvent], delay: float) -> None:
        self._events, self._delay = list(events), delay

    async def __aenter__(self) -> Self:
        await asyncio.sleep(self._delay)
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> RunEvent:
        if not self._events:
            raise StopAsyncIteration
        await asyncio.sleep(0.05)
        return self._events.pop(0)


class FakeService:
    def __init__(self, hang: bool = False, delay: float = 0.0) -> None:
        self.hang, self.delay = hang, delay
        self.runs = [_run("run1")]

    async def list_runs(self) -> list[Run]:
        if self.hang:
            await asyncio.sleep(3600)
        return list(self.runs)

    async def rerun(self, source: str, profiles: list[str]) -> Run:
        run = _run("run2", "queued")
        self.runs.insert(0, run)
        return run

    async def get_run(self, run_id: str) -> Run | None:
        return next((r for r in self.runs if r.id == run_id), None)

    def subscribe(self, run_id: str) -> _Sub:
        return _Sub([_status(run_id, 1, "running"), _status(run_id, 2, "done")], self.delay)


def _sse(*chunks: dict[str, Any]) -> httpx.Response:
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    return httpx.Response(200, content=body.encode(), headers={"content-type": "text/event-stream"})


def _text(*parts: str) -> httpx.Response:
    return _sse(*[{"choices": [{"delta": {"content": p}}]} for p in parts])


def _tool(name: str, args: dict[str, Any], call_id: str = "c1") -> httpx.Response:
    raw = json.dumps(args)
    return _sse(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "id": call_id, "function": {"name": name, "arguments": ""}}
                        ]
                    }
                }
            ]
        },
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": raw[:3]}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": raw[3:]}}]}}]},
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    )


def _llm_handler(tool_name: str = "list_runs", tool_args: dict[str, Any] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        msgs = json.loads(request.content)["messages"]
        if any(m["role"] == "tool" for m in msgs):
            return _text("Aapka ", "run ready hai, ", "sab theek lag raha hai. ", "Kuch aur poochna hai?")
        last = [m for m in msgs if m["role"] == "user"][-1]["content"]
        if "run" in last or "test" in last:
            return _tool(tool_name, tool_args or {})
        return _text("Namaste, ", "main madad ", "ke liye hoon.")

    return handler


@pytest.fixture
def sarvam() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as mock:
        mock.post(f"{SARVAM}/text-to-speech").mock(
            return_value=httpx.Response(200, json={"audios": [_wav_b64()]})
        )
        mock.post(f"{SARVAM}/speech-to-text").mock(
            return_value=httpx.Response(200, json={"transcript": "list my runs", "language_code": "en-IN"})
        )
        mock.post(f"{SARVAM}/v1/chat/completions").mock(side_effect=_llm_handler())
        yield mock


def _client(monkeypatch: pytest.MonkeyPatch, service: FakeService, **settings: Any) -> TestClient:
    monkeypatch.setattr(rt_router, "resolve_service", lambda: service)
    app = FastAPI()
    app.state.settings = Settings(_env_file=None, sarvam_api_key="sk_test", **settings)  # type: ignore[call-arg]
    app.include_router(rt_router.router)
    return TestClient(app)


def _start(ws: WebSocketTestSession, mode: str = "voice") -> dict[str, Any]:
    ws.send_json(
        {
            "v": 2,
            "type": "session.start",
            "token": None,
            "conversation_id": None,
            "mode": mode,
            "language": "auto",
        }
    )
    ready = ws.receive_json()
    assert ready["type"] == "session.ready", ready
    return ready


def _recv(ws: WebSocketTestSession) -> dict[str, Any]:
    msg = ws.receive()
    if msg.get("bytes") is not None:
        data = msg["bytes"]
        gen, seq = struct.unpack(">II", data[:8])
        return {"type": "<audio-frame>", "generation_id": gen, "seq": seq, "pcm_len": len(data) - 8}
    return json.loads(msg["text"])  # type: ignore[no-any-return]


def _until(ws: WebSocketTestSession, kind: str, limit: int = 80) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []
    for _ in range(limit):
        m = _recv(ws)
        seen.append(m)
        if m["type"] == kind:
            return seen
    raise AssertionError(f"no {kind} in {[m['type'] for m in seen]}")


def test_text_turn_with_tool_streams_text_and_audio(
    monkeypatch: pytest.MonkeyPatch, sarvam: respx.MockRouter
) -> None:
    with _client(monkeypatch, FakeService()).websocket_connect("/ws/realtime") as ws:
        ready = _start(ws)
        assert ready["output_sample_rate"] == 24000
        assert ready["conversation_id"]
        ws.send_json({"v": 2, "type": "user.text", "text": "show my latest run"})
        events = _until(ws, "turn.completed")
        events += _until(ws, "state")  # LISTENING follows turn.completed
    types = [e["type"] for e in events]
    for expected in (
        "state",
        "llm.started",
        "tool.started",
        "tool.finished",
        "text.delta",
        "text.segment",
        "audio.started",
        "audio.segment",
        "<audio-frame>",
        "audio.segment_done",
        "audio.completed",
        "turn.completed",
    ):
        assert expected in types, (expected, types)
    assert types.index("tool.started") < types.index("tool.finished") < types.index("text.delta")
    assert types.index("audio.started") < types.index("<audio-frame>") < types.index("audio.completed")
    started = next(e for e in events if e["type"] == "tool.started")
    assert started["name"] == "list_runs" and started["label"] and started["call_id"] == "c1"
    assert next(e for e in events if e["type"] == "tool.finished")["ok"] is True
    states = [e["state"] for e in events if e["type"] == "state"]
    assert (
        "WORKING" in states and "GENERATING" in states and "SPEAKING" in states and states[-1] == "LISTENING"
    )
    gens = {e["generation_id"] for e in events if "generation_id" in e}
    assert gens == {1}
    assert next(e for e in events if e["type"] == "turn.completed")["text"].startswith("Aapka run ready hai")
    assert [e["seq"] for e in events if e["type"] != "<audio-frame>"] == sorted(
        e["seq"] for e in events if e["type"] != "<audio-frame>"
    )


def test_text_mode_has_no_audio(monkeypatch: pytest.MonkeyPatch, sarvam: respx.MockRouter) -> None:
    with _client(monkeypatch, FakeService()).websocket_connect("/ws/realtime") as ws:
        _start(ws, mode="text")
        ws.send_json({"v": 2, "type": "user.text", "text": "hello"})
        events = _until(ws, "turn.completed")
    types = {e["type"] for e in events}
    assert "text.delta" in types and "audio.started" not in types and "<audio-frame>" not in types
    assert not sarvam.routes[0].called  # no TTS call in text mode


def test_interrupt_mid_tool_cancels_and_no_stale_audio(
    monkeypatch: pytest.MonkeyPatch, sarvam: respx.MockRouter
) -> None:
    with _client(monkeypatch, FakeService(hang=True)).websocket_connect("/ws/realtime") as ws:
        _start(ws)
        ws.send_json({"v": 2, "type": "user.text", "text": "list my runs"})
        before = _until(ws, "tool.started")
        gen = before[-1]["generation_id"]
        ws.send_json({"v": 2, "type": "turn.cancel", "generation_id": gen})
        cancelled = _until(ws, "turn.cancelled")[-1]
        assert cancelled["generation_id"] == gen and cancelled["reason"] == "client"
        assert _until(ws, "state")[-1]["state"] in ("INTERRUPTED", "LISTENING")
        # next turn (plain greeting, no tool) completes with a newer generation and nothing from `gen` after cancel
        ws.send_json({"v": 2, "type": "user.text", "text": "hello"})
        events = _until(ws, "turn.completed")
    assert {e["generation_id"] for e in events if "generation_id" in e} == {gen + 1}
    assert not any(e["type"] == "tool.finished" for e in events)


def test_stale_cancel_generation_is_ignored(
    monkeypatch: pytest.MonkeyPatch, sarvam: respx.MockRouter
) -> None:
    with _client(monkeypatch, FakeService()).websocket_connect("/ws/realtime") as ws:
        _start(ws)
        ws.send_json({"v": 2, "type": "user.text", "text": "hello"})
        _until(ws, "turn.completed")
        ws.send_json({"v": 2, "type": "turn.cancel", "generation_id": 99})
        ws.send_json({"v": 2, "type": "heartbeat"})
        seen = _until(ws, "heartbeat")  # a stale-generation cancel must not produce turn.cancelled
        assert all(e["type"] != "turn.cancelled" for e in seen)


def test_voice_backchannel_resumes_and_real_words_barge_in(
    monkeypatch: pytest.MonkeyPatch, sarvam: respx.MockRouter
) -> None:
    transcripts = iter(["haan", "stop and list my runs please"])
    sarvam.post(f"{SARVAM}/speech-to-text").mock(
        side_effect=lambda req: httpx.Response(
            200, json={"transcript": next(transcripts), "language_code": "en-IN"}
        )
    )
    with _client(monkeypatch, FakeService(hang=True)).websocket_connect("/ws/realtime") as ws:
        _start(ws)
        ws.send_json({"v": 2, "type": "user.text", "text": "list my runs"})
        gen = _until(ws, "tool.started")[-1]["generation_id"]
        # overlapping backchannel
        ws.send_json({"v": 2, "type": "input.speech_started"})
        ws.send_bytes(b"\x01\x00" * 3200)
        ws.send_json({"v": 2, "type": "input.speech_ended"})
        seen = _until(ws, "turn.resume")
        assert seen[-1]["generation_id"] == gen
        # overlapping real words
        ws.send_json({"v": 2, "type": "input.speech_started"})
        ws.send_bytes(b"\x01\x00" * 3200)
        ws.send_json({"v": 2, "type": "input.speech_ended"})
        seen = _until(ws, "turn.cancelled")
        assert seen[-1]["reason"] == "barge_in"
        assert any(e["type"] == "transcript.final" for e in seen)


def test_voice_turn_from_audio(monkeypatch: pytest.MonkeyPatch, sarvam: respx.MockRouter) -> None:
    with _client(monkeypatch, FakeService()).websocket_connect("/ws/realtime") as ws:
        _start(ws)
        ws.send_json({"v": 2, "type": "input.speech_started"})
        ws.send_bytes(b"\x01\x00" * 3200)
        ws.send_json({"v": 2, "type": "input.speech_ended"})
        events = _until(ws, "turn.completed")
    assert next(e for e in events if e["type"] == "transcript.final")["text"] == "list my runs"
    assert any(e["type"] == "<audio-frame>" for e in events)


def test_job_updates_pushed_and_idle_narration(
    monkeypatch: pytest.MonkeyPatch, sarvam: respx.MockRouter
) -> None:
    sarvam.post(f"{SARVAM}/v1/chat/completions").mock(
        side_effect=_llm_handler("start_test", {"profiles": ["baseline"]})
    )
    service = FakeService(delay=0.6)  # job events arrive after the turn has finished -> idle narration
    with _client(monkeypatch, service).websocket_connect("/ws/realtime") as ws:
        _start(ws)
        ws.send_json({"v": 2, "type": "user.text", "text": "start a test"})
        first = _until(ws, "turn.completed")
        assert any(e["type"] == "tool.finished" and e["ok"] for e in first)
        running = _until(ws, "job.update")[-1]
        assert (
            running["run_id"] == "run2" and running["status"] == "running" and running["progress"] is not None
        )
        narration = _until(ws, "turn.completed")[-1]
        assert narration["text"] == "The test is now running."
        done = _until(ws, "job.update")[-1]
        assert done["status"] == "done"
        assert _until(ws, "turn.completed")[-1]["text"].startswith("Test complete")


def test_auth_required_rejects_missing_token(
    monkeypatch: pytest.MonkeyPatch, sarvam: respx.MockRouter
) -> None:
    client = _client(monkeypatch, FakeService(), auth_required=True)
    with client.websocket_connect("/ws/realtime") as ws:
        ws.send_json(
            {
                "v": 2,
                "type": "session.start",
                "token": None,
                "conversation_id": None,
                "mode": "text",
                "language": "auto",
            }
        )
        msg = ws.receive()
        assert msg["type"] == "websocket.close" and msg["code"] == 4401


def test_conversation_is_reused(monkeypatch: pytest.MonkeyPatch, sarvam: respx.MockRouter) -> None:
    client = _client(monkeypatch, FakeService())
    with client.websocket_connect("/ws/realtime") as ws:
        cid = _start(ws, "text")["conversation_id"]
        ws.send_json({"v": 2, "type": "user.text", "text": "hello"})
        _until(ws, "turn.completed")
    with client.websocket_connect("/ws/realtime") as ws:
        ws.send_json(
            {
                "v": 2,
                "type": "session.start",
                "token": None,
                "conversation_id": cid,
                "mode": "text",
                "language": "auto",
            }
        )
        assert ws.receive_json()["conversation_id"] == cid


def test_think_filter_strips_reasoning_across_deltas() -> None:
    f = ThinkFilter()
    out = "".join(f.feed(d) for d in ["Hi <thi", "nk>secret", " stuff</th", "ink> there", "!"]) + f.flush()
    assert out == "Hi  there!"
