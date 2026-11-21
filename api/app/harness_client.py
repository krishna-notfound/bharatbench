"""Async client for the EC2 harness service (contracts/README.md section 4)."""

from pathlib import Path
from typing import Any

import anyio
import httpx

from app.models import HarnessJob, HarnessJobRequest, HarnessResult


class HarnessClient:
    def __init__(self, url: str, token: str | None) -> None:
        headers = {"X-Harness-Token": token} if token else {}
        self._client = httpx.AsyncClient(
            base_url=url.rstrip("/"), headers=headers, timeout=httpx.Timeout(60.0, connect=5.0)
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def health(self) -> dict[str, Any]:
        resp = await self._client.get("/health")
        resp.raise_for_status()
        return resp.json()

    async def submit(self, apk_path: Path, request: HarnessJobRequest) -> HarnessJob:
        content = await anyio.Path(apk_path).read_bytes()
        resp = await self._client.post(
            "/jobs",
            files={"apk": ("app.apk", content, "application/vnd.android.package-archive")},
            data={"request": request.model_dump_json()},
        )
        resp.raise_for_status()
        return HarnessJob.model_validate(resp.json())

    async def poll(self, job_id: str) -> HarnessJob:
        resp = await self._client.get(f"/jobs/{job_id}")
        resp.raise_for_status()
        return HarnessJob.model_validate(resp.json())

    async def result(self, job_id: str) -> HarnessResult:
        resp = await self._client.get(f"/jobs/{job_id}/result")
        resp.raise_for_status()
        return HarnessResult.model_validate(resp.json())

    async def download_artifact(self, job_id: str, path: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        async with self._client.stream("GET", f"/jobs/{job_id}/artifacts/{path}") as resp:
            resp.raise_for_status()
            async with await anyio.open_file(dest, "wb") as out:
                async for chunk in resp.aiter_bytes():
                    await out.write(chunk)

    async def cancel(self, job_id: str) -> HarnessJob:
        resp = await self._client.post(f"/jobs/{job_id}/cancel")
        resp.raise_for_status()
        return HarnessJob.model_validate(resp.json())
