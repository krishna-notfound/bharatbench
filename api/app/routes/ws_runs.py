import asyncio
import contextlib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services import get_run_service

router = APIRouter()


@router.websocket("/ws/runs/{run_id}")
async def run_events(ws: WebSocket, run_id: str) -> None:
    service = get_run_service()
    await ws.accept()
    if await service.get_run(run_id) is None:
        await ws.close(code=4404, reason="run not found")
        return

    async with service.subscribe(run_id) as sub:

        async def pump() -> None:
            async for event in sub:
                await ws.send_text(event.model_dump_json())
                if event.type in ("done", "error"):
                    return

        pump_task = asyncio.create_task(pump())
        try:
            while True:
                try:
                    msg = await ws.receive_json()
                except ValueError:
                    continue
                if isinstance(msg, dict) and msg.get("type") == "ping":
                    await ws.send_json({"type": "pong"})
        except WebSocketDisconnect:
            pass
        finally:
            pump_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, RuntimeError, WebSocketDisconnect):
                await pump_task
