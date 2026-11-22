import json

import httpx

from harness.agent import drive, parse_action, render_nodes
from harness.models import AgentTest
from harness.parsers import parse_ui_nodes
from harness.settings import Settings

from .device import FakeDevice, make_xml
from .test_crawler import crawler, taps

TEST = AgentTest(id="bad_email", title="Invalid email", goal="Enter a bad email", success_check="error shown")


def settings() -> Settings:
    return Settings(harness_token="t", llm_api_key="k")


def llm(answers: list[str]) -> httpx.AsyncClient:
    it = iter(answers)

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["api-subscription-key"] == "k"
        return httpx.Response(200, json={"choices": [{"message": {"content": next(it)}}]})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_parse_action_validates():
    assert parse_action('{"action":"tap","node":1,"reason":"x"}', 3)["node"] == 1
    assert parse_action('{"action":"tap","node":9}', 3) is None
    assert parse_action('{"action":"fill","node":0}', 3) is None  # fill needs text
    assert parse_action('<think>x</think>{"action":"done","reason":"ok"}', 0)["action"] == "done"
    assert parse_action("nonsense", 3) is None


def test_render_nodes_is_indexed():
    text, nodes = render_nodes(parse_ui_nodes(make_xml(["Welcome"], ["Sign up"])))
    assert text.splitlines()[0].startswith("0|") and any("Sign up" in line for line in text.splitlines())
    assert len(nodes) >= 2


def _index_of(label: str, xml: str) -> int:
    _, nodes = render_nodes(parse_ui_nodes(xml))
    return next(i for i, n in enumerate(nodes) if n.text == label)


async def test_drive_tap_then_done(tmp_path):
    first = make_xml(["Home"], ["Sign up"])
    dev = FakeDevice([first, make_xml(["Invalid email"])])
    c = crawler(dev, tmp_path, profile="agent_bad_email")
    idx = _index_of("Sign up", first)
    caps: list[str] = []
    answers = [
        json.dumps({"action": "tap", "node": idx, "reason": "open sign up"}),
        json.dumps({"action": "done", "reason": "error visible"}),
    ]
    async with llm(answers) as client:
        res = await drive(c, TEST, settings(), client, caps.append)
    assert res.passed is True and res.reason == "error visible"
    assert taps(dev) and caps and caps[0].startswith("Agent: tapping 'Sign up'")
    assert [s.action for s in res.steps][:2] == ["launch", "tap"]
    assert res.screens


async def test_drive_fail_verdict_and_unusable_answer(tmp_path):
    dev = FakeDevice([make_xml(["Home"], ["Go"])])
    async with llm(['{"action":"fail","reason":"no error shown"}']) as client:
        res = await drive(crawler(dev, tmp_path, profile="agent_a"), TEST, settings(), client)
    assert res.passed is False and "no error" in res.reason
    dev2 = FakeDevice([make_xml(["Home"], ["Go"])])
    async with llm(["garbage"]) as client:
        res2 = await drive(crawler(dev2, tmp_path, profile="agent_b"), TEST, settings(), client)
    assert res2.passed is None


async def test_drive_denylist_never_taps_unsafe(tmp_path):
    xml = make_xml(["Home"], ["Pay now"])
    dev = FakeDevice([xml])
    idx = _index_of("Pay now", xml)
    answers = [json.dumps({"action": "tap", "node": idx, "reason": "x"}), '{"action":"fail","reason":"stop"}']
    async with llm(answers) as client:
        res = await drive(crawler(dev, tmp_path, profile="agent_c"), TEST, settings(), client)
    assert taps(dev) == [] and res.passed is False
    assert any(s.note and "unsafe" in s.note for s in res.steps)
