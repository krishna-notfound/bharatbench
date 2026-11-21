"""Guarded access to the f10 conversation store and Supabase auth, with in-memory/anonymous fallbacks."""

from __future__ import annotations

import logging
import uuid
from typing import Any

log = logging.getLogger(__name__)


class InMemoryStore:
    """Fallback when app.conversations.store is not available (f10 not merged)."""

    def __init__(self) -> None:
        self._owner: dict[str, str | None] = {}
        self._messages: dict[str, list[dict[str, Any]]] = {}

    async def create(self, user_id: str | None, mode: str) -> str:
        cid = uuid.uuid4().hex
        self._owner[cid] = user_id
        self._messages[cid] = []
        return cid

    async def get_owner(self, conversation_id: str) -> str | None:
        return self._owner.get(conversation_id)

    async def append(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        interrupted: bool = False,
        meta: dict[str, Any] | None = None,
    ) -> None:
        self._messages.setdefault(conversation_id, []).append(
            {"role": role, "content": content, "interrupted": interrupted, "meta": meta or {}}
        )

    async def history(self, conversation_id: str, limit: int = 30) -> list[dict[str, Any]]:
        return self._messages.get(conversation_id, [])[-limit:]


_fallback = InMemoryStore()


def get_store() -> Any:
    try:
        from app.conversations.store import get_conversation_store  # f10

        return get_conversation_store()
    except Exception:  # ImportError, or the store failing to initialise  # noqa: BLE001
        return _fallback


async def verify_token(token: str | None) -> tuple[bool, Any]:
    """(verifier_available, user). user is None when the token is missing/invalid."""
    try:
        from app.auth.supabase import verify_token as verify  # f10
    except Exception:  # noqa: BLE001
        return False, None
    try:
        return True, await verify(token)
    except Exception:  # noqa: BLE001
        log.warning("token verification raised")
        return True, None


def user_id(user: Any) -> str | None:
    if user is None:
        return None
    if isinstance(user, dict):
        return user.get("id")
    return getattr(user, "id", None)
