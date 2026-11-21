from datetime import UTC, datetime

import pytest

from app.events import EventBus
from app.models import RunEvent
from app.storage.sqlite import SqliteStorage
from tests.conftest import make_finding, make_run


@pytest.fixture
async def storage(tmp_path):
    s = SqliteStorage(tmp_path / "t.db")
    await s.init()
    yield s
    await s.close()


async def test_run_roundtrip_and_order(storage):
    await storage.create_run(make_run("r1"), "/x/a.apk")
    await storage.create_run(make_run("r2"), "/x/b.apk")
    assert (await storage.get_run("r1")).id == "r1"
    assert await storage.get_run("nope") is None
    assert await storage.get_apk_path("r2") == "/x/b.apk"
    assert [r.id for r in await storage.list_runs()] == ["r2", "r1"]
    r = make_run("r1", "done")
    await storage.update_run(r)
    assert (await storage.get_run("r1")).status == "done"


async def test_findings_roundtrip(storage):
    await storage.add_findings("r1", [make_finding("a"), make_finding("b")])
    assert [f.id for f in await storage.list_findings("r1")] == ["a", "b"]
    assert await storage.list_findings("other") == []


async def test_event_seq_and_after_seq(storage):
    assert await storage.next_seq("r1") == 1
    for seq in (1, 2, 3):
        await storage.add_event(
            RunEvent(run_id="r1", seq=seq, ts=datetime.now(UTC), type="log", message=str(seq))
        )
    assert await storage.next_seq("r1") == 4
    assert await storage.next_seq("r2") == 1
    assert [e.seq for e in await storage.list_events("r1", 1)] == [2, 3]


async def test_bus_subscription_history_then_live_no_dupes(storage):
    bus = EventBus(storage)
    await bus.publish("r1", "log", "one")
    await bus.publish("r1", "log", "two")
    async with bus.subscribe("r1") as sub:
        await bus.publish("r1", "done", "three")
        got = [await sub.__anext__() for _ in range(3)]
    assert [e.seq for e in got] == [1, 2, 3]
    assert [e.message for e in got] == ["one", "two", "three"]
