"""Conversation store (contract v2 §2): Supabase PostgREST or in-memory fallback."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

import httpx

from app.settings import get_settings

Role = Literal["user", "assistant", "tool"]


class ConversationStore(Protocol):
    async def create(self, user_id: str | None, mode: str) -> str: ...
    async def get_owner(self, conversation_id: str) -> str | None: ...
    async def append(
        self, conversation_id: str, role: Role, content: str, *, interrupted: bool = False, meta: dict | None = None
    ) -> None: ...
    async def history(self, conversation_id: str, limit: int = 30) -> list[dict]: ...
    async def list_for_user(self, user_id: str, limit: int = 50) -> list[dict]: ...
    async def set_run_owner(self, run_id: str, user_id: str | None) -> None: ...
    async def run_ids_for_user(self, user_id: str) -> set[str]: ...


def _title(content: str) -> str:
    return " ".join(content.split())[:60]


class MemoryConversationStore:
    def __init__(self) -> None:
        self._convs: dict[str, dict[str, Any]] = {}
        self._msgs: dict[str, list[dict]] = {}
        self._run_owner: dict[str, str] = {}

    async def create(self, user_id: str | None, mode: str) -> str:
        cid = str(uuid.uuid4())
        self._convs[cid] = {
            "id": cid, "user_id": user_id, "mode": mode, "title": None,
            "created_at": datetime.now(UTC).isoformat(),
        }
        self._msgs[cid] = []
        return cid

    async def get_owner(self, conversation_id: str) -> str | None:
        c = self._convs.get(conversation_id)
        return c["user_id"] if c else None

    async def append(
        self, conversation_id: str, role: Role, content: str, *, interrupted: bool = False, meta: dict | None = None
    ) -> None:
        conv = self._convs.get(conversation_id)
        if conv is None:
            raise KeyError(conversation_id)
        self._msgs[conversation_id].append({
            "role": role, "content": content, "interrupted": interrupted, "meta": meta,
            "created_at": datetime.now(UTC).isoformat(),
        })
        if role == "user" and not conv["title"]:
            conv["title"] = _title(content)

    async def history(self, conversation_id: str, limit: int = 30) -> list[dict]:
        return list(self._msgs.get(conversation_id, []))[-limit:]

    async def list_for_user(self, user_id: str, limit: int = 50) -> list[dict]:
        rows = [c for c in self._convs.values() if c["user_id"] == user_id]
        rows.sort(key=lambda c: c["created_at"], reverse=True)
        return [{k: c[k] for k in ("id", "mode", "created_at", "title")} for c in rows[:limit]]

    async def set_run_owner(self, run_id: str, user_id: str | None) -> None:
        if user_id:
            self._run_owner[run_id] = user_id

    async def run_ids_for_user(self, user_id: str) -> set[str]:
        return {r for r, u in self._run_owner.items() if u == user_id}


class SupabaseConversationStore:
    def __init__(self, url: str, service_key: str, timeout: float = 10.0) -> None:
        self._base = url.rstrip("/") + "/rest/v1"
        self._headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        }
        self._timeout = timeout

    async def _req(self, method: str, table: str, *, params: dict | None = None, json: Any = None,
                   prefer: str | None = None) -> Any:
        headers = dict(self._headers)
        if prefer:
            headers["Prefer"] = prefer
        async with httpx.AsyncClient(timeout=self._timeout, headers=headers) as c:
            r = await c.request(method, f"{self._base}/{table}", params=params, json=json)
            r.raise_for_status()
            return r.json() if r.content else None

    async def create(self, user_id: str | None, mode: str) -> str:
        rows = await self._req(
            "POST", "conversations", json={"user_id": user_id, "mode": mode}, prefer="return=representation"
        )
        return rows[0]["id"]

    async def get_owner(self, conversation_id: str) -> str | None:
        rows = await self._req("GET", "conversations", params={"select": "user_id", "id": f"eq.{conversation_id}"})
        return rows[0]["user_id"] if rows else None

    async def append(
        self, conversation_id: str, role: Role, content: str, *, interrupted: bool = False, meta: dict | None = None
    ) -> None:
        content = content.replace("\0", "")
        await self._req(
            "POST", "messages",
            json={"conversation_id": conversation_id, "role": role, "content": content,
                  "interrupted": interrupted, "meta": meta},
            prefer="return=minimal",
        )
        if role == "user":  # first user message becomes the title
            await self._req(
                "PATCH", "conversations",
                params={"id": f"eq.{conversation_id}", "title": "is.null"},
                json={"title": _title(content)}, prefer="return=minimal",
            )

    async def history(self, conversation_id: str, limit: int = 30) -> list[dict]:
        rows = await self._req(
            "GET", "messages",
            params={"select": "role,content,interrupted,meta,created_at",
                    "conversation_id": f"eq.{conversation_id}", "order": "created_at.desc,id.desc",
                    "limit": str(limit)},
        )
        return list(reversed(rows or []))

    async def list_for_user(self, user_id: str, limit: int = 50) -> list[dict]:
        rows = await self._req(
            "GET", "conversations",
            params={"select": "id,mode,created_at,title", "user_id": f"eq.{user_id}",
                    "order": "created_at.desc", "limit": str(limit)},
        )
        return rows or []

    async def set_run_owner(self, run_id: str, user_id: str | None) -> None:
        if user_id:
            await self._req("PATCH", "runs", params={"id": f"eq.{run_id}"},
                            json={"user_id": user_id}, prefer="return=minimal")

    async def run_ids_for_user(self, user_id: str) -> set[str]:
        rows = await self._req("GET", "runs", params={"select": "id", "user_id": f"eq.{user_id}"})
        return {r["id"] for r in rows or []}


_store: ConversationStore | None = None


def get_conversation_store() -> ConversationStore:
    global _store
    if _store is None:
        s = get_settings()
        if s.storage_backend == "supabase" and s.supabase_url and s.supabase_service_role_key:
            _store = SupabaseConversationStore(s.supabase_url, s.supabase_service_role_key)
        else:
            _store = MemoryConversationStore()
    return _store


def set_conversation_store(store: ConversationStore | None) -> None:
    global _store
    _store = store
