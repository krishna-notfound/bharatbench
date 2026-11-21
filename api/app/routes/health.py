from typing import Any

import httpx
from fastapi import APIRouter, Request

from app.harness_client import HarnessClient
from app.profiles import PROFILES
from app.settings import Settings

router = APIRouter(prefix="/api")


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    harness: dict[str, Any] = {"configured": settings.harness_configured, "reachable": False, "detail": ""}
    if not settings.harness_configured:
        harness["detail"] = "HARNESS_URL is not set; runtime testing will be skipped."
    else:
        client = HarnessClient(settings.harness_url or "", settings.harness_token)
        try:
            info = await client.health()
            harness["reachable"] = True
            harness["detail"] = (
                f"adb={info.get('adb')} emulator_booted={info.get('emulator_booted')} maestro={info.get('maestro')}"
            )
        except (httpx.HTTPError, OSError) as exc:
            harness["detail"] = f"{type(exc).__name__}: {exc}"
        finally:
            await client.aclose()
    return {"ok": True, "harness": harness, "sarvam_configured": bool(settings.sarvam_api_key)}


@router.get("/profiles")
async def profiles() -> list[dict[str, Any]]:
    return [p.model_dump() for p in PROFILES]
