import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.auth.supabase import AuthUser
from app.conversations import store as store_mod
from app.conversations.store import MemoryConversationStore, SupabaseConversationStore
from app.main import create_app
from app.routes import conversations as conv_routes
from app.routes import runs as runs_routes
from tests.conftest import make_apk_bytes


async def test_memory_store_roundtrip():
    s = MemoryConversationStore()
    cid = await s.create("u1", "voice")
    await s.append(cid, "user", "hello   there")
    await s.append(cid, "assistant", "hi", interrupted=True, meta={"x": 1})
    h = await s.history(cid)
    assert [m["role"] for m in h] == ["user", "assistant"] and h[1]["interrupted"] and h[1]["meta"] == {"x": 1}
    assert await s.get_owner(cid) == "u1"
    assert (await s.list_for_user("u1"))[0]["title"] == "hello there"
    assert await s.list_for_user("u2") == []
    assert await s.history(cid, limit=1) == h[-1:]


@respx.mock
async def test_supabase_store_requests():
    base = "https://p.supabase.co/rest/v1"
    s = SupabaseConversationStore("https://p.supabase.co", "svc")
    post = respx.post(f"{base}/conversations").mock(return_value=httpx.Response(201, json=[{"id": "c1"}]))
    assert await s.create("u1", "text") == "c1"
    assert post.calls[0].request.headers["authorization"] == "Bearer svc"
    respx.post(f"{base}/messages").mock(return_value=httpx.Response(201))
    patch = respx.patch(f"{base}/conversations").mock(return_value=httpx.Response(204))
    await s.append("c1", "user", "hi")
    assert patch.called
    respx.get(f"{base}/messages").mock(
        return_value=httpx.Response(200, json=[{"role": "assistant", "content": "b"}, {"role": "user", "content": "a"}])
    )
    assert [m["content"] for m in await s.history("c1")] == ["a", "b"]
    respx.get(f"{base}/conversations").mock(return_value=httpx.Response(200, json=[{"user_id": "u1"}]))
    assert await s.get_owner("c1") == "u1"


@pytest.fixture
def memstore():
    s = MemoryConversationStore()
    store_mod.set_conversation_store(s)
    yield s
    store_mod.set_conversation_store(None)


@pytest.fixture
def users(monkeypatch):
    async def fake_verify(token, settings=None):
        return {"a": AuthUser("user-a"), "b": AuthUser("user-b")}.get(token)

    monkeypatch.setattr(conv_routes, "verify_token", fake_verify)
    monkeypatch.setattr(runs_routes, "verify_token", fake_verify)
    from app import access

    monkeypatch.setattr(access, "verify_token", fake_verify)


@pytest.fixture
def client(settings, fake_analyzer, memstore, users):
    with TestClient(create_app(settings)) as c:
        yield c


def H(t):
    return {"Authorization": f"Bearer {t}"}


async def test_routes_scoping(client, memstore):
    cid = await memstore.create("user-a", "voice")
    await memstore.append(cid, "user", "yo")
    assert client.get("/api/conversations").status_code == 401
    assert client.get("/api/conversations", headers=H("bad")).status_code == 401
    rows = client.get("/api/conversations", headers=H("a")).json()
    assert [r["id"] for r in rows] == [cid]
    assert client.get("/api/conversations", headers=H("b")).json() == []
    assert client.get(f"/api/conversations/{cid}/messages", headers=H("a")).json()[0]["content"] == "yo"
    assert client.get(f"/api/conversations/{cid}/messages", headers=H("b")).status_code == 404


def test_runs_user_scoping(client):
    r = client.post("/api/runs", files={"apk": ("a.apk", make_apk_bytes())}, headers=H("a"))
    assert r.status_code == 201
    rid = r.json()["id"]
    assert [x["id"] for x in client.get("/api/runs", headers=H("a")).json()] == [rid]
    assert client.get("/api/runs", headers=H("b")).json() == []
    assert len(client.get("/api/runs").json()) == 1  # anonymous caller sees all (dev mode)


def test_auth_required_blocks_anonymous_upload(settings, fake_analyzer, memstore, users):
    settings.auth_required = True
    with TestClient(create_app(settings)) as c:
        r = c.post("/api/runs", files={"apk": ("a.apk", make_apk_bytes())})
        assert r.status_code == 401
