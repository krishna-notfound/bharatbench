"""f24: human-in-the-loop input broker."""

import asyncio
import json

import pytest

from harness.inputs import AskField, InputBroker, run_unpaused
from harness.live import LiveState
from harness.secrets import Secrets

from .device import FakeDevice, make_xml
from .test_crawler import crawler

FIELDS = [AskField("email", "Email", "email"), AskField("password", "Password", "password")]
SECRET = "Zx9!hunter2"
LOGIN_SCREEN = make_xml(
    ["Welcome"], ["Sign in"], fields=[{"hint": "Email"}, {"hint": "Password", "password": True}]
)


async def test_request_answer_roundtrip():
    events: list[str] = []
    b = InputBroker(on_event=events.append)
    task = asyncio.create_task(b.ask(FIELDS, "login"))
    await asyncio.sleep(0.05)
    pub = b.public()
    assert pub and [f["secret"] for f in pub["fields"]] == [False, True] and "value" not in json.dumps(pub)
    assert not b.submit("wrong-id", {"email": "a@b.co"})
    assert b.submit(pub["request_id"], {"email": "a@b.co", "password": SECRET, "bogus": "x"})
    assert await task == {"email": "a@b.co", "password": SECRET}
    assert b.public() is None and events == ["Waiting for you: Email, Password"]
    assert SECRET not in "".join(events)


async def test_skip_and_timeout():
    b = InputBroker(timeout_s=0.1)
    t = asyncio.create_task(b.ask(FIELDS, "x"))
    await asyncio.sleep(0.02)
    b.submit(b.public()["request_id"], None, skip=True)
    assert await t is None
    assert await b.ask(FIELDS, "x") is None  # timeout
    assert b.timeouts == 1 and b.paused_s >= 0.09
    await b.ask(FIELDS, "x")
    assert not b.enabled  # nobody is watching: stop pausing


async def test_paused_time_does_not_count_toward_timeout():
    b = InputBroker(timeout_s=0.5)

    async def work() -> str:
        await asyncio.sleep(0.1)
        await b.ask(FIELDS, "x")  # waits 0.5 s (times out), well past the 0.3 s budget
        await asyncio.sleep(0.1)
        return "ok"

    assert await run_unpaused(work(), 0.3, b, poll=0.05) == "ok"

    async def slow() -> None:
        await asyncio.sleep(2)

    with pytest.raises(TimeoutError):
        await run_unpaused(slow(), 0.2, b, poll=0.05)


async def test_live_state_exposes_request_without_values():
    live = LiveState()
    t = asyncio.create_task(live.broker.ask(FIELDS, "login"))
    await asyncio.sleep(0.05)
    pub = live.public()
    assert pub["waiting_for_input"] and pub["input_request"]["fields"][0]["key"] == "email"
    live.broker.submit(pub["input_request"]["request_id"], {"password": SECRET})
    await t
    assert not live.public()["waiting_for_input"] and SECRET not in json.dumps(live.public())


async def test_crawler_asks_then_types_and_hides(tmp_path):
    dev = FakeDevice([LOGIN_SCREEN, make_xml(["Home"])])
    c = crawler(dev, tmp_path)
    c.broker = InputBroker()
    c.secrets = Secrets(None)

    async def user() -> None:
        while c.broker.public() is None:
            await asyncio.sleep(0.01)
        c.broker.submit(c.broker.public()["request_id"], {"email": "me@real.in", "password": SECRET})

    u = asyncio.create_task(user())
    j = await c.run(1)
    await u
    assert "me@real.in" in dev.typed and SECRET in dev.typed
    stored = json.dumps([s.model_dump() for s in j.steps]) + "".join(p.read_text("utf-8") for p in tmp_path.rglob("*.xml"))
    assert SECRET not in stored
    assert [s.note for s in j.steps if s.action == "fill"][:2] == ["Filling login (hidden)", "Filling password (hidden)"]


async def test_crawler_skip_falls_back_to_fake_values(tmp_path):
    dev = FakeDevice([LOGIN_SCREEN, make_xml(["Home"])])
    c = crawler(dev, tmp_path)
    c.broker = InputBroker()

    async def user() -> None:
        while c.broker.public() is None:
            await asyncio.sleep(0.01)
        c.broker.submit(c.broker.public()["request_id"], None, skip=True)

    u = asyncio.create_task(user())
    j = await c.run(1)
    await u
    assert any(s.note == "User input skipped" for s in j.steps)
    assert "asha.verma@example.com" in dev.typed and c.broker.declined
