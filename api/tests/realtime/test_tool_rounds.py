"""Regression: chained tool rounds must still end in a spoken answer."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from app.realtime import session as session_mod
from tests.realtime.test_realtime_ws import SARVAM, FakeService, _client, _start, _text, _tool, _until


def test_chained_tool_rounds_end_in_spoken_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """After MAX_TOOL_ROUNDS tool rounds the last request keeps the tool schemas (the history holds
    tool_calls) with tool_choice "none" - never tools=None (Sarvam answered HTTP 400) - and answers."""
    bodies: list[dict[str, Any]] = []

    def llm(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        bodies.append(body)
        if body.get("tool_choice") == "none":
            return _text("Here is what I found. ", "The screen was stuck for ten seconds.")
        return _tool("list_runs", {}, call_id=f"c{len(bodies)}")

    rounds = session_mod.registry.MAX_TOOL_ROUNDS
    with respx.mock(assert_all_called=False) as mock:
        mock.post(f"{SARVAM}/v1/chat/completions").mock(side_effect=llm)
        with _client(monkeypatch, FakeService()).websocket_connect("/ws/realtime") as ws:
            _start(ws, "text")
            ws.send_json({"v": 2, "type": "user.text", "text": "show me the evidence"})
            events = _until(ws, "turn.completed", limit=200)
    assert len(bodies) == rounds + 1
    assert all(b.get("tools") for b in bodies)
    assert [b["tool_choice"] for b in bodies] == ["auto"] * rounds + ["none"]
    assert events[-1]["text"].startswith("Here is what I found")
    assert not any(e["type"] == "pipeline.error" for e in events)
