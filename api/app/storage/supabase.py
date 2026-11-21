"""Supabase (PostgREST) implementation of Storage. Models are stored as JSON in `data`."""

from typing import Any

import httpx

from app.models import Finding, Run, RunEvent


class SupabaseStorage:
    def __init__(self, url: str, service_key: str, timeout: float = 10.0) -> None:
        self._base = url.rstrip("/") + "/rest/v1"
        self._headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        }
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("SupabaseStorage.init() was not called")
        return self._client

    async def init(self) -> None:
        self._client = httpx.AsyncClient(headers=self._headers, timeout=self._timeout)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _write(self, method: str, table: str, *, params: dict[str, str] | None = None, json: Any = None) -> None:
        r = await self.client.request(
            method,
            f"{self._base}/{table}",
            params=params,
            json=_strip_nul(json),
            headers={"Prefer": "return=minimal"},
        )
        r.raise_for_status()

    async def _select(self, table: str, params: dict[str, str]) -> list[dict[str, Any]]:
        r = await self.client.get(f"{self._base}/{table}", params=params)
        r.raise_for_status()
        return r.json()

    async def create_run(self, run: Run, apk_path: str) -> None:
        await self._write(
            "POST",
            "runs",
            json={
                "id": run.id,
                "apk_path": apk_path,
                "status": run.status,
                "created_at": run.created_at.isoformat(),
                "updated_at": run.updated_at.isoformat(),
                "data": run.model_dump(mode="json"),
            },
        )

    async def update_run(self, run: Run) -> None:
        await self._write(
            "PATCH",
            "runs",
            params={"id": f"eq.{run.id}"},
            json={
                "status": run.status,
                "updated_at": run.updated_at.isoformat(),
                "data": run.model_dump(mode="json"),
            },
        )

    async def get_run(self, run_id: str) -> Run | None:
        rows = await self._select("runs", {"select": "data", "id": f"eq.{run_id}"})
        return Run.model_validate(rows[0]["data"]) if rows else None

    async def get_apk_path(self, run_id: str) -> str | None:
        rows = await self._select("runs", {"select": "apk_path", "id": f"eq.{run_id}"})
        return rows[0]["apk_path"] if rows else None

    async def list_runs(self) -> list[Run]:
        rows = await self._select("runs", {"select": "data", "order": "created_at.desc"})
        return [Run.model_validate(r["data"]) for r in rows]

    async def add_findings(self, run_id: str, findings: list[Finding]) -> None:
        if not findings:
            return
        await self._write(
            "POST",
            "findings",
            json=[{"id": f.id, "run_id": run_id, "data": f.model_dump(mode="json")} for f in findings],
        )

    async def list_findings(self, run_id: str) -> list[Finding]:
        rows = await self._select("findings", {"select": "data", "run_id": f"eq.{run_id}", "order": "ord.asc"})
        return [Finding.model_validate(r["data"]) for r in rows]

    async def add_event(self, event: RunEvent) -> None:
        await self._write(
            "POST",
            "events",
            json={
                "run_id": event.run_id,
                "seq": event.seq,
                "ts": event.ts.isoformat(),
                "type": event.type,
                "data": event.model_dump(mode="json"),
            },
        )

    async def list_events(self, run_id: str, after_seq: int = 0) -> list[RunEvent]:
        rows = await self._select(
            "events",
            {"select": "data", "run_id": f"eq.{run_id}", "seq": f"gt.{after_seq}", "order": "seq.asc"},
        )
        return [RunEvent.model_validate(r["data"]) for r in rows]

    async def next_seq(self, run_id: str) -> int:
        rows = await self._select(
            "events", {"select": "seq", "run_id": f"eq.{run_id}", "order": "seq.desc", "limit": "1"}
        )
        return int(rows[0]["seq"]) + 1 if rows else 1


def _strip_nul(value: Any) -> Any:
    """Postgres text/jsonb rejects U+0000 (APK strings can contain it); drop it before writing."""
    if isinstance(value, str):
        return value.replace("\0", "")
    if isinstance(value, list):
        return [_strip_nul(v) for v in value]
    if isinstance(value, dict):
        return {k: _strip_nul(v) for k, v in value.items()}
    return value
