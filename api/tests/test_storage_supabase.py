"""SupabaseStorage against a stateful respx fake of PostgREST."""

import json

import httpx
import pytest
import respx

from app.models import RunEvent
from app.storage.supabase import SupabaseStorage
from tests.conftest import make_finding, make_run

BASE = "https://x.supabase.co"


def _eq(params, key):
    v = params.get(key)
    return v[3:] if v and v.startswith("eq.") else None


@pytest.fixture
async def storage():
    tables: dict[str, list[dict]] = {"runs": [], "findings": [], "events": []}
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        table = request.url.path.rsplit("/", 1)[-1]
        q = dict(request.url.params)
        rows = tables[table]
        if request.method == "POST":
            body = json.loads(request.content)
            for b in body if isinstance(body, list) else [body]:
                if table == "findings":
                    b = {**b, "ord": len(rows) + 1}
                rows.append(b)
            return httpx.Response(201)
        if request.method == "PATCH":
            for r in rows:
                if r["id"] == _eq(q, "id"):
                    r.update(json.loads(request.content))
            return httpx.Response(204)
        out = list(rows)
        for col in ("id", "run_id"):
            if _eq(q, col) is not None:
                out = [r for r in out if r[col] == _eq(q, col)]
        if q.get("seq", "").startswith("gt."):
            out = [r for r in out if r["seq"] > int(q["seq"][3:])]
        if "order" in q:
            col, direction = q["order"].split(".")
            out.sort(key=lambda r: r[col], reverse=direction == "desc")
        if "limit" in q:
            out = out[: int(q["limit"])]
        cols = q["select"].split(",")
        return httpx.Response(200, json=[{c: r[c] for c in cols} for r in out])

    with respx.mock(base_url=BASE) as mock:
        mock.route().mock(side_effect=handler)
        s = SupabaseStorage(BASE, "secret-key")
        await s.init()
        s.seen = seen  # type: ignore[attr-defined]
        yield s
        await s.close()


async def test_runs(storage):
    await storage.create_run(make_run("r1"), "/x/a.apk")
    await storage.create_run(make_run("r2"), "/x/b.apk")
    assert (await storage.get_run("r1")).id == "r1"
    assert await storage.get_run("nope") is None
    assert await storage.get_apk_path("r2") == "/x/b.apk"
    assert await storage.get_apk_path("nope") is None
    assert [r.id for r in await storage.list_runs()] == ["r2", "r1"]
    await storage.update_run(make_run("r1", "done"))
    assert (await storage.get_run("r1")).status == "done"
    req = storage.seen[0]
    assert req.headers["apikey"] == "secret-key"
    assert req.headers["authorization"] == "Bearer secret-key"
    assert req.headers["prefer"] == "return=minimal"


async def test_findings_in_insertion_order(storage):
    await storage.create_run(make_run("r1"), "/a")
    await storage.add_findings("r1", [make_finding("b", "r1"), make_finding("a", "r1")])
    await storage.add_findings("r1", [])
    await storage.add_findings("r1", [make_finding("c", "r1")])
    assert [f.id for f in await storage.list_findings("r1")] == ["b", "a", "c"]
    assert await storage.list_findings("other") == []


async def test_events_and_next_seq(storage):
    from datetime import UTC, datetime

    await storage.create_run(make_run("r1"), "/a")
    assert await storage.next_seq("r1") == 1
    for seq in (1, 2, 3):
        await storage.add_event(
            RunEvent(run_id="r1", seq=seq, ts=datetime.now(UTC), type="log", message=f"m{seq}")  # type: ignore[arg-type]
        )
    assert [e.seq for e in await storage.list_events("r1")] == [1, 2, 3]
    assert [e.seq for e in await storage.list_events("r1", after_seq=1)] == [2, 3]
    assert await storage.next_seq("r1") == 4


def test_strip_nul_removes_nul_recursively():
    from app.storage.supabase import _strip_nul

    assert _strip_nul({"a": ["x\x00y", {"b": "\x00"}], "n": 1}) == {"a": ["xy", {"b": ""}], "n": 1}
