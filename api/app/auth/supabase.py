"""Supabase access-token verification (contract v2 §2).

Asymmetric tokens (ES256/RS256) are verified against the project JWKS; HS256 only when
`supabase_jwt_secret` is set. Each key source accepts only its own algorithms.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt

from app.settings import Settings, get_settings

log = logging.getLogger(__name__)

AUDIENCE = "authenticated"
_JWKS_TTL_S = 3600
_jwks_cache: dict[str, tuple[float, list[dict]]] = {}


@dataclass(frozen=True, slots=True)
class AuthUser:
    id: str
    is_anonymous: bool = False
    email: str | None = None


def clear_jwks_cache() -> None:
    _jwks_cache.clear()


async def _jwks(url: str, *, force: bool = False) -> list[dict]:
    cached = _jwks_cache.get(url)
    if cached and not force and time.monotonic() - cached[0] < _JWKS_TTL_S:
        return cached[1]
    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.get(url)
        r.raise_for_status()
        keys = r.json().get("keys", [])
    _jwks_cache[url] = (time.monotonic(), keys)
    return keys


async def _asymmetric_key(token: str, base: str) -> Any:
    kid = jwt.get_unverified_header(token).get("kid")
    url = f"{base}/auth/v1/.well-known/jwks.json"
    for force in (False, True):  # refetch once on an unknown kid (key rotation)
        for jwk in await _jwks(url, force=force):
            if kid is None or jwk.get("kid") == kid:
                return jwt.PyJWK.from_dict(jwk).key
    raise jwt.InvalidKeyError("no matching signing key")


async def verify_token(token: str | None, settings: Settings | None = None) -> AuthUser | None:
    """Return the user for a valid Supabase access token, else None. Never raises."""
    if not token:
        return None
    settings = settings or get_settings()
    base = (settings.supabase_url or "").rstrip("/")
    try:
        alg = jwt.get_unverified_header(token).get("alg")
        issuer = f"{base}/auth/v1" if base else None
        key: Any
        if alg == "HS256":
            if not settings.supabase_jwt_secret:
                return None
            key, algorithms = settings.supabase_jwt_secret, ["HS256"]
        elif alg in ("ES256", "RS256") and base:
            key, algorithms = await _asymmetric_key(token, base), ["ES256", "RS256"]
        else:
            return None
        claims = jwt.decode(
            token,
            key,
            algorithms=algorithms,
            audience=AUDIENCE,
            issuer=issuer,
            leeway=5,
            options={"require": ["exp", "sub", "aud"] + (["iss"] if issuer else [])},
        )
    except (jwt.PyJWTError, httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        log.warning("token rejected: %s", type(exc).__name__)
        return None
    return AuthUser(
        id=str(claims["sub"]),
        is_anonymous=bool(claims.get("is_anonymous", False)),
        email=claims.get("email"),
    )


def bearer_token(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None
