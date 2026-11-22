import time

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app import github_import as gh
from app.main import create_app
from tests.conftest import make_apk_bytes

BASE = "https://api.github.com/repos/o/r/releases"
ASSET_URL = "https://api.github.com/repos/o/r/releases/assets/7"


@pytest.fixture
def client(settings, fake_analyzer):
    with TestClient(create_app(settings)) as c:
        yield c


def asset(name, aid=7, size=100, state="uploaded"):
    return {
        "name": name,
        "size": size,
        "state": state,
        "url": f"https://api.github.com/repos/o/r/releases/assets/{aid}",
    }


def release(tag="v1.2", assets=(), draft=False):
    return {"tag_name": tag, "draft": draft, "assets": list(assets)}


def post(client, url="https://github.com/o/r", **kw):
    return client.post("/api/runs/import", json={"repo_url": url, **kw})


def wait_done(client, run_id, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in ("done", "failed", "cancelled"):
            return run
        time.sleep(0.02)
    raise AssertionError("run did not finish")


@pytest.mark.parametrize(
    "raw,owner,repo,tag",
    [
        ("https://github.com/o/r", "o", "r", None),
        ("https://github.com/o/r.git", "o", "r", None),
        ("https://github.com/o/r/", "o", "r", None),
        ("github.com/o/r", "o", "r", None),
        ("https://github.com/o/r/releases/tag/v1.0", "o", "r", "v1.0"),
        ("https://www.github.com/o/r/tree/main", "o", "r", None),
    ],
)
def test_parse_ok(raw, owner, repo, tag):
    assert gh.parse_repo_url(raw) == gh.RepoRef(owner, repo, tag)


@pytest.mark.parametrize(
    "raw",
    ["", "https://gitlab.com/o/r", "https://github.com/o", "https://evilgithub.com/o/r", "ftp://github.com/o/r",
     "https://github.com/o/r%20x", "not a url", "https://github.com.evil.com/o/r"],
)
def test_parse_rejects(raw):
    with pytest.raises(gh.GithubImportError) as e:
        gh.parse_repo_url(raw)
    assert e.value.status == 400


def test_pick_prefers_universal_and_never_aab():
    rel = release(assets=[asset("app-x86.apk"), asset("app.aab"), asset("app-arm64-v8a.apk"), asset("app-universal.apk")])
    assert gh.pick_apk(rel)["name"] == "app-universal.apk"
    assert gh.pick_apk(release(assets=[asset("app.aab")])) is None
    assert gh.pick_apk(release(assets=[asset("a.apk", state="starter")])) is None


@respx.mock(assert_all_called=False)
def test_import_happy_path(client, respx_mock):
    respx_mock.get(f"{BASE}/latest").mock(return_value=httpx.Response(200, json=release(assets=[asset("My-App.apk")])))
    respx_mock.get(ASSET_URL).mock(return_value=httpx.Response(200, content=make_apk_bytes()))
    r = post(client)
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["apk_name"] == "My-App.apk"
    wait_done(client, run["id"])
    events = client.get(f"/api/runs/{run['id']}/events").json()
    assert any(e["message"] == "Imported from github.com/o/r release v1.2" for e in events)
    # temp download removed
    assert not list((client.app.state.settings.data_dir / "tmp").glob("*.apk"))


@respx.mock(assert_all_called=False)
def test_fallback_to_older_release_with_apk(client, respx_mock):
    respx_mock.get(f"{BASE}/latest").mock(return_value=httpx.Response(200, json=release("v2", [asset("a.aab")])))
    respx_mock.get(BASE).mock(
        return_value=httpx.Response(200, json=[release("v2", [asset("a.aab")]), release("v1", [asset("old.apk")])])
    )
    respx_mock.get(ASSET_URL).mock(return_value=httpx.Response(200, content=make_apk_bytes()))
    r = post(client)
    assert r.status_code == 201
    assert r.json()["apk_name"] == "old.apk"


@respx.mock(assert_all_called=False)
def test_explicit_tag(client, respx_mock):
    respx_mock.get(f"{BASE}/tags/v0.9").mock(return_value=httpx.Response(200, json=release("v0.9", [asset("t.apk")])))
    respx_mock.get(ASSET_URL).mock(return_value=httpx.Response(200, content=make_apk_bytes()))
    assert post(client, "https://github.com/o/r/releases/tag/v0.9").json()["apk_name"] == "t.apk"


@respx.mock(assert_all_called=False)
def test_repo_not_found(client, respx_mock):
    respx_mock.get(f"{BASE}/latest").mock(return_value=httpx.Response(404, json={}))
    respx_mock.get(BASE).mock(return_value=httpx.Response(404, json={}))
    r = post(client)
    assert r.status_code == 404 and "private" in r.json()["detail"]


@respx.mock(assert_all_called=False)
def test_no_releases(client, respx_mock):
    respx_mock.get(f"{BASE}/latest").mock(return_value=httpx.Response(404, json={}))
    respx_mock.get(BASE).mock(return_value=httpx.Response(200, json=[]))
    r = post(client)
    assert r.status_code == 404 and gh.NO_APK_MESSAGE in r.json()["detail"]


@respx.mock(assert_all_called=False)
def test_no_apk_anywhere(client, respx_mock):
    respx_mock.get(f"{BASE}/latest").mock(return_value=httpx.Response(200, json=release(assets=[asset("a.aab")])))
    respx_mock.get(BASE).mock(return_value=httpx.Response(200, json=[release(assets=[asset("a.zip")])]))
    r = post(client)
    assert r.status_code == 404 and r.json()["detail"] == gh.NO_APK_MESSAGE
    assert client.get("/api/runs").json() == []


@respx.mock(assert_all_called=False)
def test_too_big_declared(client, respx_mock):
    respx_mock.get(f"{BASE}/latest").mock(
        return_value=httpx.Response(200, json=release(assets=[asset("big.apk", size=gh.MAX_APK_BYTES + 1)]))
    )
    assert post(client).status_code == 413


@respx.mock(assert_all_called=False)
def test_too_big_while_streaming(client, respx_mock, monkeypatch):
    monkeypatch.setattr(gh, "MAX_APK_BYTES", 10)
    monkeypatch.setattr(gh, "CHUNK", 4)
    respx_mock.get(f"{BASE}/latest").mock(return_value=httpx.Response(200, json=release(assets=[asset("a.apk", size=5)])))
    respx_mock.get(ASSET_URL).mock(return_value=httpx.Response(200, content=b"PK" + b"x" * 100))
    assert post(client).status_code == 413
    assert not list((client.app.state.settings.data_dir / "tmp").glob("*.apk"))


@respx.mock(assert_all_called=False)
def test_not_a_zip(client, respx_mock):
    respx_mock.get(f"{BASE}/latest").mock(return_value=httpx.Response(200, json=release(assets=[asset("a.apk")])))
    respx_mock.get(ASSET_URL).mock(return_value=httpx.Response(200, content=b"<html>nope"))
    assert post(client).status_code == 400


@respx.mock(assert_all_called=False)
def test_rate_limited(client, respx_mock):
    respx_mock.get(f"{BASE}/latest").mock(
        return_value=httpx.Response(403, headers={"x-ratelimit-remaining": "0"}, json={})
    )
    assert post(client).status_code == 429


def test_bad_url_and_profiles(client):
    assert post(client, "https://example.com/o/r").status_code == 400
    assert post(client, profiles=["nope"]).status_code == 422


@respx.mock(assert_all_called=False)
def test_token_sent_but_not_leaked(settings, fake_analyzer, respx_mock, caplog):
    settings.github_token = "ghp_secret123"
    route = respx_mock.get(f"{BASE}/latest").mock(return_value=httpx.Response(200, json=release(assets=[asset("a.apk")])))
    respx_mock.get(ASSET_URL).mock(return_value=httpx.Response(200, content=make_apk_bytes()))
    with TestClient(create_app(settings)) as c:
        r = post(c)
        assert r.status_code == 201
        events = c.get(f"/api/runs/{r.json()['id']}/events").text
    assert route.calls.last.request.headers["authorization"] == "Bearer ghp_secret123"
    assert "ghp_secret123" not in events and "ghp_secret123" not in caplog.text
