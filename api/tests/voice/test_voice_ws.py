"""WS /ws/voice end to end with Sarvam mocked (respx) and a fake RunService."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession
from voice_fakes import SARVAM, WAV_B64, FakeRunService, chat_reply, status_event, tool_call

from app.models import Run
from app.voice import router as voice_router


class HangingRunService(FakeRunService):
    """list_runs never returns: simulates a slow tool so a turn can be interrupted mid tool call."""

    async def list_runs(self) -> list[Run]:
        await asyncio.sleep(3600)
        return []


def _client(
    monkeypatch: pytest.MonkeyPatch, service: FakeRunService, key: str | None = "sk_test"
) -> TestClient:
    monkeypatch.setattr(voice_router, "resolve_service", lambda: service)
    monkeypatch.setattr(voice_router, "get_sarvam_key", lambda: key)
    app = FastAPI()
    app.include_router(voice_router.router)
    return TestClient(app)


@pytest.fixture
def sarvam() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as mock:
        mock.post(f"{SARVAM}/text-to-speech").mock(
            return_value=httpx.Response(200, json={"audios": [WAV_B64]})
        )
        mock.post(f"{SARVAM}/speech-to-text").mock(
            return_value=httpx.Response(200, json={"transcript": "list my runs", "language_code": "en-IN"})
        )
        yield mock


def _recv_until(ws: WebSocketTestSession, kind: str, limit: int = 60) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []
    for _ in range(limit):
        msg = ws.receive_json()
        seen.append(msg)
        if msg["type"] == kind:
            return seen
    raise AssertionError(f"no {kind} in {seen}")


def test_text_turn_tool_call_text_audio_turn_end(
    monkeypatch: pytest.MonkeyPatch, sarvam: respx.MockRouter, service: FakeRunService
) -> None:
    sarvam.post(f"{SARVAM}/v1/chat/completions").mock(
        side_effect=[
            httpx.Response(200, json=chat_reply(None, [tool_call("list_runs", "{}")])),
            httpx.Response(200, json=chat_reply("You have one run. It scored 61.")),
        ]
    )
    with _client(monkeypatch, service).websocket_connect("/ws/voice") as ws:
        ws.send_json({"type": "start", "language": "en-IN", "run_id": None})
        assert ws.receive_json() == {"type": "ready"}
        ws.send_json({"type": "text", "text": "list my runs"})
        msgs = _recv_until(ws, "turn_end")

    assert [m["type"] for m in msgs] == [
        "transcript",
        "tool_call",
        "tool_result",
        "assistant_text",
        "audio",
        "assistant_text",
        "audio",
        "turn_end",
    ]
    assert msgs[1]["name"] == "list_runs"
    assert msgs[2]["ok"] is True and "run1" in msgs[2]["summary"]
    assert msgs[3]["text"] == "You have one run."
    assert msgs[4]["format"] == "wav" and msgs[4]["sample_rate"] == 24000 and msgs[4]["data"] == WAV_B64
    assert len({m["turn_id"] for m in msgs if "turn_id" in m}) == 1


def test_slow_network_request_starts_test_with_flaky_and_budget_profiles(
    monkeypatch: pytest.MonkeyPatch, sarvam: respx.MockRouter, service: FakeRunService
) -> None:
    args = json.dumps({"profiles": ["flaky_network", "budget_2gb"]})
    chat = sarvam.post(f"{SARVAM}/v1/chat/completions").mock(
        side_effect=[
            httpx.Response(200, json=chat_reply(None, [tool_call("start_test", args)])),
            httpx.Response(200, json=chat_reply("Started run run2.")),
        ]
    )
    service.events = [status_event("run2", 1, "running"), status_event("run2", 2, "done")]
    with _client(monkeypatch, service).websocket_connect("/ws/voice") as ws:
        ws.send_json({"type": "start", "language": "auto", "run_id": "run1"})
        ws.receive_json()
        ws.send_json({"type": "text", "text": "test my app on slow network"})
        msgs = _recv_until(ws, "turn_end")
        updates = []
        while not any(u["status"] == "done" for u in updates):
            msg = ws.receive_json()
            if msg["type"] == "run_update":
                updates.append(msg)

    assert service.rerun_calls == [("run1", ["flaky_network", "budget_2gb"])]
    assert [m["type"] for m in msgs if m["type"] == "tool_call"] == ["tool_call"]
    assert [u["status"] for u in updates][-1] == "done"
    assert "Test complete: 2 critical issues" in updates[-1]["message"]
    second_request = json.loads(chat.calls[1].request.content)
    assert second_request["messages"][-1]["role"] == "tool"  # tool result fed back to the LLM
    assert "Active run id: run2" in second_request["messages"][0]["content"]


def test_voice_utterance_is_transcribed_then_answered(
    monkeypatch: pytest.MonkeyPatch, sarvam: respx.MockRouter, service: FakeRunService
) -> None:
    sarvam.post(f"{SARVAM}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=chat_reply("Ek run mila."))
    )
    with _client(monkeypatch, service).websocket_connect("/ws/voice") as ws:
        ws.send_json({"type": "start", "language": "auto", "run_id": None})
        ws.receive_json()
        for _ in range(3):
            ws.send_bytes(b"\x01\x00" * 1600)
        ws.send_json({"type": "speech_end"})
        msgs = _recv_until(ws, "turn_end")
    assert msgs[0] == {"type": "transcript", "text": "list my runs", "final": True}
    assert [m["type"] for m in msgs][-3:] == ["assistant_text", "audio", "turn_end"]


def test_interrupt_during_tool_call_cancels_turn_and_sends_no_orphan_audio(
    monkeypatch: pytest.MonkeyPatch, sarvam: respx.MockRouter
) -> None:
    chat = sarvam.post(f"{SARVAM}/v1/chat/completions").mock(
        side_effect=[
            httpx.Response(200, json=chat_reply(None, [tool_call("list_runs", "{}")])),
            httpx.Response(200, json=chat_reply("Second turn answer.")),
        ]
    )
    with _client(monkeypatch, HangingRunService()).websocket_connect("/ws/voice") as ws:
        ws.send_json({"type": "start", "language": "en-IN", "run_id": None})
        ws.receive_json()
        ws.send_json({"type": "text", "text": "list my runs"})
        first = _recv_until(ws, "tool_call")
        first_turn = first[-1]["turn_id"]
        ws.send_json({"type": "interrupt"})
        end = ws.receive_json()
        assert end == {"type": "turn_end", "turn_id": first_turn}

        ws.send_json({"type": "text", "text": "never mind"})
        msgs = _recv_until(ws, "turn_end")

    # nothing from the interrupted turn after its turn_end; new turn is fully separate
    assert all(m.get("turn_id", msgs[-1]["turn_id"]) == msgs[-1]["turn_id"] for m in msgs)
    assert msgs[-1]["turn_id"] != first_turn
    assert [m["type"] for m in msgs if m["type"] == "audio"] == ["audio"]
    # history was rewritten: the cancelled turn left no dangling assistant tool_calls without results
    second_request = json.loads(chat.calls[1].request.content)
    roles = [m["role"] for m in second_request["messages"]]
    assert roles == ["system", "user", "user"]


def test_missing_key_reports_voice_not_configured(
    monkeypatch: pytest.MonkeyPatch, service: FakeRunService
) -> None:
    with _client(monkeypatch, service, key=None).websocket_connect("/ws/voice") as ws:
        ws.send_json({"type": "start", "language": "auto", "run_id": None})
        assert ws.receive_json() == {"type": "error", "message": "Voice not configured"}
        ws.send_json({"type": "text", "text": "hello"})
        assert ws.receive_json() == {"type": "error", "message": "Voice not configured"}


def test_sarvam_failure_surfaces_error_then_turn_end(
    monkeypatch: pytest.MonkeyPatch, sarvam: respx.MockRouter, service: FakeRunService
) -> None:
    sarvam.post(f"{SARVAM}/v1/chat/completions").mock(return_value=httpx.Response(500))
    with _client(monkeypatch, service).websocket_connect("/ws/voice") as ws:
        ws.send_json({"type": "start", "language": "auto", "run_id": None})
        ws.receive_json()
        ws.send_json({"type": "text", "text": "hi"})
        msgs = _recv_until(ws, "turn_end")
    assert [m["type"] for m in msgs] == ["transcript", "error", "turn_end"]
    assert "sk_test" not in msgs[1]["message"]
