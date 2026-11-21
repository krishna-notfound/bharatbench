"""WS /ws/realtime (contracts/v2-voice-and-users.md section 1)."""

from __future__ import annotations

from fastapi import APIRouter, WebSocket

from app.models import RunService
from app.realtime.session import RealtimeSession
from app.settings import Settings

router = APIRouter()


def resolve_service() -> RunService:
    from app.services import get_run_service  # imported lazily

    return get_run_service()


def resolve_settings(websocket: WebSocket) -> Settings:
    settings = getattr(websocket.app.state, "settings", None)
    return settings if isinstance(settings, Settings) else Settings()


@router.websocket("/ws/realtime")
async def realtime_ws(websocket: WebSocket) -> None:
    await RealtimeSession(websocket, resolve_settings(websocket), resolve_service).run()
