"""WS /ws/voice (contracts/README.md section 5)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.models import RunService
from app.voice.config import get_sarvam_key
from app.voice.session import VoiceSession

router = APIRouter()


def resolve_service() -> RunService:
    from app.services import get_run_service  # f02; imported lazily

    return get_run_service()


@router.websocket("/ws/voice")
async def voice_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    session = VoiceSession(websocket.send_json, resolve_service, get_sarvam_key())
    try:
        while True:
            frame = await websocket.receive()
            if frame["type"] == "websocket.disconnect":
                break
            if frame.get("bytes") is not None:
                session.add_audio(frame["bytes"])
            elif frame.get("text") is not None:
                await _handle_json(session, frame["text"])
    except WebSocketDisconnect:
        pass
    finally:
        await session.close()


async def _handle_json(session: VoiceSession, raw: str) -> None:
    try:
        msg: Any = json.loads(raw)
    except ValueError:
        await session.emit(None, {"type": "error", "message": "Invalid JSON message"})
        return
    kind = msg.get("type") if isinstance(msg, dict) else None
    if kind == "start":
        run_id = msg.get("run_id")
        await session.handle_start(str(msg.get("language", "auto")), str(run_id) if run_id else None)
    elif kind == "speech_end":
        await session.speech_end()
    elif kind == "interrupt":
        await session.interrupt()
    elif kind == "text":
        await session.handle_text(str(msg.get("text", "")))
    else:
        await session.emit(None, {"type": "error", "message": f"Unknown message type: {kind}"})
