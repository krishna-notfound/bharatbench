from typing import Any

import anyio
import httpx
from fastapi import APIRouter, Request

from app.harness_client import HarnessClient
from app.profiles import PROFILES
from app.settings import Settings

router = APIRouter(prefix="/api")
HEALTH_TIMEOUT_S = 3.0


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    harness: dict[str, Any] = {"configured": settings.harness_configured, "reachable": False, "detail": ""}
    if not settings.harness_configured:
        harness["detail"] = "HARNESS_URL is not set; runtime testing will be skipped."
    else:
        client = HarnessClient(settings.harness_url or "", settings.harness_token)
        try:
            with anyio.fail_after(HEALTH_TIMEOUT_S):  # a busy harness must not stall /api/health
                info = await client.health()
            harness["reachable"] = True
            harness["detail"] = (
                f"adb={info.get('adb')} emulator_booted={info.get('emulator_booted')} maestro={info.get('maestro')}"
            )
        except TimeoutError:
            harness["detail"] = f"harness did not answer within {HEALTH_TIMEOUT_S:g}s (busy or unreachable)"
        except (httpx.HTTPError, OSError) as exc:
            harness["detail"] = f"{type(exc).__name__}: {exc}"
        finally:
            await client.aclose()
    return {"ok": True, "harness": harness, "sarvam_configured": bool(settings.sarvam_api_key)}


@router.get("/profiles")
async def profiles() -> list[dict[str, Any]]:
    return [p.model_dump() for p in PROFILES]
