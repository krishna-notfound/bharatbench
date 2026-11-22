"""Regression tests for docs/SECURITY_AUDIT.md (IDOR, artifact headers, rate limit, import SSRF, zip bomb)."""

import asyncio
import zipfile

import httpx
import pytest
from fastapi.testclient import TestClient

from app import access
from app import github_import as gh
from app.analyzer.apk import _check_zip_budget
from app.auth.supabase import AuthUser
from app.conversations import store as store_mod
from app.conversations.store import MemoryConversationStore
from app.main import create_app
from app.routes import runs as runs_routes
from tests.conftest import make_apk_bytes


def H(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture
def client(settings, fake_analyzer, monkeypatch):
    settings.supabase_url = "https://example.supabase.co"  # accounts configured: no global listing
    store_mod.set_conversation_store(MemoryConversationStore())

    async def fake_verify(token, settings=None):
        return {"a": AuthUser("user-a"), "b": AuthUser("user-b")}.get(token)

    monkeypatch.setattr(runs_routes, "verify_token", fake_verify)
    monkeypatch.setattr(access, "verify_token", fake_verify)
    access.limiter.reset()
    with TestClient(create_app(settings)) as c:
        yield c
    store_mod.set_conversation_store(None)


def new_run(client, token=None):
    r = client.post("/api/runs", files={"apk": ("a.apk", make_apk_bytes())}, headers=H(token) if token else {})
    assert r.status_code == 201
    return r.json()["id"]


def test_run_ids_are_128_bit(client):
    rid = new_run(client, "a")
    assert len(rid) == 32 and int(rid, 16) >= 0


def test_anonymous_cannot_list_runs_when_accounts_configured(client):
    new_run(client, "a")
    assert client.get("/api/runs").json() == []
    assert client.get("/api/runs", headers=H("bad")).json() == []
    assert len(client.get("/api/runs", headers=H("a")).json()) == 1
    assert client.get("/api/runs", headers=H("b")).json() == []


def test_mutations_on_owned_run_need_the_owner(client):
    rid = new_run(client, "a")
    bodies = {
        "cancel": None,
        "retry": None,
        "input": {"request_id": "x", "values": {}, "skip": True},
        "brief": {"language": "auto"},
    }
    for path, body in bodies.items():
        for who in (None, "b"):
            r = client.post(f"/api/runs/{rid}/{path}", json=body, headers=H(who) if who else {})
            assert r.status_code == 404, (path, who, r.status_code)
    assert client.post(f"/api/runs/{rid}/cancel", headers=H("a")).status_code == 200


def test_guest_run_without_owner_stays_usable(client):
    rid = new_run(client)
    assert client.post(f"/api/runs/{rid}/cancel").status_code == 200


def test_artifact_headers_and_allowlist(client, settings):
    rid = new_run(client, "a")
    d = settings.data_dir / "runs" / rid / "artifacts"
    d.mkdir(parents=True, exist_ok=True)
    (d / "x.html").write_text("<script>alert(1)</script>")
    (d / "ui.xml").write_text("<hierarchy/>")
    (d / "s.png").write_bytes(b"\x89PNG")
    assert client.get(f"/api/runs/{rid}/artifacts/x.html").status_code == 404
    r = client.get(f"/api/runs/{rid}/artifacts/ui.xml")
    assert r.headers["content-type"].startswith("text/plain")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in r.headers["content-security-policy"]
    assert client.get(f"/api/runs/{rid}/artifacts/s.png").headers["content-type"] == "image/png"
    for bad in ("..%2f..%2fapp.apk", "..%5c..%5capp.apk", "%2e%2e/app.apk", "../app.apk"):
        assert client.get(f"/api/runs/{rid}/artifacts/{bad}").status_code in (400, 404)


def test_upload_rate_limited(client):
    codes = [client.post("/api/runs", files={"apk": ("a.apk", make_apk_bytes())}).status_code for _ in range(12)]
    assert codes.count(429) == 2


def test_voice_list_runs_is_scoped(client):
    rid = new_run(client, "a")

    class Svc:
        async def list_runs(self):
            return await client.app.state.service.list_runs()

    settings = client.app.state.settings
    scoped_b = asyncio.run(access.scope_service(Svc(), "user-b", settings))
    scoped_a = asyncio.run(access.scope_service(Svc(), "user-a", settings))
    assert asyncio.run(scoped_b.list_runs()) == []
    assert [r.id for r in asyncio.run(scoped_a.list_runs())] == [rid]


def test_import_rejects_traversal_tag():
    for url in ("https://github.com/o/r/releases/tag/../../../user", "https://github.com/o/r/releases/tag/a/%2e%2e/b"):
        with pytest.raises(gh.GithubImportError):
            gh.parse_repo_url(url)


async def test_download_refuses_redirect_off_github(tmp_path):
    hits = []

    def handler(req: httpx.Request) -> httpx.Response:
        hits.append(str(req.url))
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})

    asset = gh.ApkAsset("a.apk", "https://api.github.com/repos/o/r/releases/assets/1", 10, "v1")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(gh.GithubImportError):
            await gh.download_apk(asset, tmp_path / "a.apk", "tok", c)
    assert hits == ["https://api.github.com/repos/o/r/releases/assets/1"]


async def test_download_token_not_sent_to_cdn(tmp_path):
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "api.github.com":
            return httpx.Response(302, headers={"location": "https://objects.githubusercontent.com/x"})
        seen["auth"] = req.headers.get("authorization")
        return httpx.Response(200, content=make_apk_bytes())

    asset = gh.ApkAsset("a.apk", "https://api.github.com/repos/o/r/releases/assets/1", 10, "v1")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        assert await gh.download_apk(asset, tmp_path / "a.apk", "tok", c) > 0
    assert seen["auth"] is None


def test_zip_bomb_rejected(tmp_path):
    p = tmp_path / "bomb.apk"
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("classes.dex", b"\0" * (60 * 1024 * 1024))
    with pytest.raises(ValueError):
        _check_zip_budget(p)
    ok = tmp_path / "ok.apk"
    ok.write_bytes(make_apk_bytes())
    _check_zip_budget(ok)
