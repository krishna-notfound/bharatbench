import time

import httpx
import jwt
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import ec

from app.auth import supabase as auth
from app.settings import Settings

URL = "https://proj.supabase.co"
JWKS_URL = f"{URL}/auth/v1/.well-known/jwks.json"
SECRET = "s" * 40


@pytest.fixture
def key():
    return ec.generate_private_key(ec.SECP256R1())


def jwks_for(private_key, kid="k1"):
    jwk = jwt.algorithms.ECAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    return {"keys": [{**jwk, "kid": kid, "alg": "ES256", "use": "sig"}]}


def make_token(key, *, kid="k1", alg="ES256", **over):
    claims = {"sub": "11111111-1111-1111-1111-111111111111", "aud": "authenticated", "iss": f"{URL}/auth/v1",
              "exp": int(time.time()) + 300, "is_anonymous": True, **over}
    return jwt.encode(claims, key, algorithm=alg, headers={"kid": kid})


@pytest.fixture(autouse=True)
def _clear():
    auth.clear_jwks_cache()


def settings(**kw):
    return Settings(_env_file=None, supabase_url=URL, **kw)  # type: ignore[call-arg]


@respx.mock
async def test_valid_es256(key):
    respx.get(JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_for(key)))
    user = await auth.verify_token(make_token(key), settings())
    assert user is not None and user.is_anonymous and user.id.startswith("1111")


@respx.mock
async def test_rejects_expired_wrong_aud_wrong_key(key):
    respx.get(JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_for(key)))
    s = settings()
    assert await auth.verify_token(make_token(key, exp=int(time.time()) - 100), s) is None
    assert await auth.verify_token(make_token(key, aud="other"), s) is None
    assert await auth.verify_token(make_token(key, iss="https://evil/auth/v1"), s) is None
    other = ec.generate_private_key(ec.SECP256R1())
    assert await auth.verify_token(make_token(other), s) is None


@respx.mock
async def test_jwks_unreachable_returns_none(key):
    respx.get(JWKS_URL).mock(return_value=httpx.Response(500))
    assert await auth.verify_token(make_token(key), settings()) is None


async def test_none_and_garbage():
    assert await auth.verify_token(None, settings()) is None
    assert await auth.verify_token("not-a-jwt", settings()) is None


async def test_hs256_only_with_secret():
    tok = make_token(SECRET, alg="HS256")
    assert await auth.verify_token(tok, settings()) is None
    user = await auth.verify_token(tok, settings(supabase_jwt_secret=SECRET))
    assert user is not None


def test_bearer_token():
    assert auth.bearer_token("Bearer abc") == "abc"
    assert auth.bearer_token("abc") is None
    assert auth.bearer_token(None) is None
