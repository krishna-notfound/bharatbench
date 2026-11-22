"""Run access policy and a small in-memory rate limiter (docs/SECURITY_AUDIT.md).

Model: a run id is 128-bit and unguessable, so read links (report, findings, artifacts) work as share links.
Listing and every state-changing or costly call (cancel, retry, live input, brief) are owner-gated:
- a run created with a verified token is owned by that user; only that user may change it or list it;
- a run created without a token (guest, no sign-in configured) has no owner; its id is the capability.
Local development (no SUPABASE_URL) keeps the old behaviour of listing every run.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any

from fastapi import HTTPException, Request

from app.auth.supabase import bearer_token, verify_token
from app.conversations.store import get_conversation_store
from app.models import Run
from app.settings import Settings


def dev_mode(settings: Settings) -> bool:
    return not settings.supabase_url


async def request_user_id(authorization: str | None, settings: Settings) -> str | None:
    user = await verify_token(bearer_token(authorization), settings)
    return user.id if user else None


async def visible_run_ids(user_id: str | None, settings: Settings) -> set[str] | None:
    """None = no restriction (local dev). Otherwise the ids this caller may list."""
    if user_id:
        return await get_conversation_store().run_ids_for_user(user_id)
    return None if dev_mode(settings) else set()


async def require_run_owner(run: Run, authorization: str | None, settings: Settings) -> None:
    owner = await get_conversation_store().run_owner(run.id)
    if owner is None:
        return
    if await request_user_id(authorization, settings) != owner:
        raise HTTPException(404, f"Run {run.id} not found")  # 404: do not confirm the id exists


class ScopedService:
    """RunService view for voice tools: list_runs only returns what the caller may see."""

    def __init__(self, inner: Any, allowed: set[str] | None) -> None:
        self._inner, self._allowed = inner, allowed

    async def list_runs(self) -> list[Run]:
        runs = await self._inner.list_runs()
        return runs if self._allowed is None else [r for r in runs if r.id in self._allowed]

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


async def scope_service(service: Any, user_id: str | None, settings: Settings) -> Any:
    return ScopedService(service, await visible_run_ids(user_id, settings))


class RateLimiter:
    """Sliding window per key. In-memory, per process (the API is a single process)."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, window_s: float) -> None:
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > window_s:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(
                429, "Too many requests. Try again in a few minutes.", headers={"Retry-After": str(int(window_s))}
            )
        q.append(now)
        if len(self._hits) > 5000:  # bound memory
            for k in [k for k, v in self._hits.items() if not v or now - v[-1] > window_s]:
                self._hits.pop(k, None)

    def reset(self) -> None:
        self._hits.clear()


limiter = RateLimiter()


def client_key(request: Request) -> str:
    # Caddy appends the real peer to X-Forwarded-For; the last entry is the one our proxy saw.
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(request: Request, bucket: str, limit: int, window_s: float = 600) -> None:
    limiter.check(f"{bucket}:{client_key(request)}", limit, window_s)
