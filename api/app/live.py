"""Live phone view + step replay: proxies the harness live frame and persists per-profile step lists."""

import json
import struct
from pathlib import Path
from typing import Any

import anyio
import httpx

from app.models import HarnessResult, Run

ACTIVE = ("provisioning", "running")


def png_size(path: Path) -> tuple[int, int] | None:
    try:
        with path.open("rb") as fh:
            head = fh.read(24)
    except OSError:
        return None
    if len(head) < 24 or head[1:4] != b"PNG":
        return None
    w, h = struct.unpack(">II", head[16:24])
    return int(w), int(h)


class _AgentView:
    def __init__(self, t: Any) -> None:
        self.profile_id, self.steps, self.screens = f"agent_{t.id}", t.steps, t.screens


def _agent_as_profiles(result: HarnessResult) -> list[Any]:
    return [_AgentView(t) for t in result.agent_tests]


def write_steps(result: HarnessResult, art_dir: Path) -> None:
    """Write `{profile_id}/steps.json` for each profile (refs already rewritten to `{profile}/{file}`)."""
    for p in [*result.profiles, *_agent_as_profiles(result)]:
        if not p.steps:
            continue
        shots = {s.index: s.screenshot for s in p.screens}
        size = next((sz for s in p.screens if s.screenshot and (sz := png_size(art_dir / s.screenshot))), None)
        steps = [
            {
                "index": st.index,
                "action": st.action,
                "target": st.target,
                "ok": st.ok,
                "x": st.x,
                "y": st.y,
                "note": st.note,
                "duration_ms": st.duration_ms,
                "screenshot": shots.get(st.screen) if st.screen is not None else None,
            }
            for st in p.steps
        ]
        out = art_dir / p.profile_id / "steps.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {"profile_id": p.profile_id, "screen": {"w": size[0], "h": size[1]} if size else None, "steps": steps}
        out.write_text(json.dumps(payload), encoding="utf-8")


async def read_replay(run: Run, art_dir: Path) -> dict[str, Any]:
    profiles: list[dict[str, Any]] = []
    for pid in run.profile_ids:
        f = anyio.Path(art_dir / pid / "steps.json")
        if not await f.is_file():
            continue
        try:
            profiles.append(json.loads(await f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    for f in sorted(art_dir.glob("agent_*/steps.json")) if art_dir.is_dir() else []:
        try:
            profiles.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return {"run_id": run.id, "profiles": profiles}


def not_running(reason: str) -> dict[str, Any]:
    return {"running": False, "reason": reason, "has_frame": False, "tap": None, "screen": None}


def _reason(run: Run) -> str:
    if run.status in ("queued", "analyzing"):
        return "The test phone starts after the APK scan."
    if run.status == "scoring":
        return "The live test is over; I'm scoring the results."
    return "No live test is running for this session."


async def live_state(service: Any, run: Run) -> dict[str, Any]:
    job_id = service._job_ids.get(run.id)
    if run.status not in ACTIVE or not job_id:
        return not_running(_reason(run))
    client = service._harness_factory()
    if client is None or not hasattr(client, "live"):
        return not_running("Live view is not available on this test lab.")
    try:
        data = await client.live(job_id)
    except (httpx.HTTPError, OSError):
        return not_running("The test phone is not answering right now.")
    finally:
        await client.aclose()
    return data


MAX_INPUT_FIELDS = 8
MAX_INPUT_KEY = 40
MAX_INPUT_VALUE = 200


def validate_input(body: Any) -> tuple[str, dict[str, str], bool] | str:
    """(request_id, values, skip) or an error message that never echoes a value."""
    if not isinstance(body, dict):
        return "Send a JSON object."
    rid = body.get("request_id")
    if not isinstance(rid, str) or not 0 < len(rid) <= 64:
        return "request_id is required."
    skip = body.get("skip") is True
    raw = body.get("values") or {}
    if not isinstance(raw, dict) or len(raw) > MAX_INPUT_FIELDS:
        return "Too many fields."
    values: dict[str, str] = {}
    for k, v in raw.items():
        if not isinstance(k, str) or not isinstance(v, str) or len(k) > MAX_INPUT_KEY or len(v) > MAX_INPUT_VALUE:
            return "A field is too long or not text."
        values[k] = v
    if not skip and not values:
        return "Fill at least one field, or skip."
    return rid, values, skip


async def forward_input(service: Any, run: Run, rid: str, values: dict[str, str], skip: bool) -> str:
    """Forward to the harness job; returns 'ok' | 'stale' | 'unavailable'. Values are never stored or logged."""
    job_id = service._job_ids.get(run.id)
    if run.status not in ACTIVE or not job_id:
        return "unavailable"
    client = service._harness_factory()
    if client is None or not hasattr(client, "send_input"):
        return "unavailable"
    try:
        ok = await client.send_input(job_id, rid, values, skip)
    except (httpx.HTTPError, OSError):
        return "unavailable"
    finally:
        await client.aclose()
    if not ok:
        return "stale"
    n = len(values)
    msg = "Skipped" if skip or not n else f"You filled {n} field{'s' if n != 1 else ''} (hidden)"
    await service.bus.publish(run.id, "log", msg)
    return "ok"


async def live_frame(service: Any, run: Run) -> bytes | None:
    job_id = service._job_ids.get(run.id)
    if run.status not in ACTIVE or not job_id:
        return None
    client = service._harness_factory()
    if client is None or not hasattr(client, "live_png"):
        return None
    try:
        return await client.live_png(job_id)
    except (httpx.HTTPError, OSError):
        return None
    finally:
        await client.aclose()
