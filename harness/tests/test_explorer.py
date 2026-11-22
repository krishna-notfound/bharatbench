import json

import httpx

from harness.explorer import explore, llm_extra, parse_reply, signature
from harness.models import TestCredentials
from harness.parsers import parse_ui_nodes
from harness.secrets import Secrets
from harness.settings import Settings

from .device import PKG, FakeDevice, make_xml
from .test_crawler import crawler, taps


def settings() -> Settings:
    return Settings(harness_token="t", llm_api_key="k")


class Scripted:
    """Mock chat-completions endpoint: replies from a script, records every request body."""

    def __init__(self, answers: list[dict | str], status: int = 200) -> None:
        self.answers = list(answers)
        self.bodies: list[dict] = []
        self.status = status

    def client(self) -> httpx.AsyncClient:
        def handler(req: httpx.Request) -> httpx.Response:
            self.bodies.append(json.loads(req.content))
            if self.status != 200:
                return httpx.Response(self.status, json={})
            a = self.answers.pop(0) if self.answers else {"action": "done", "reason": "script over"}
            return httpx.Response(200, json={"choices": [{"message": {"content": a if isinstance(a, str) else json.dumps(a)}}]})

        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    def user(self, i: int) -> str:
        return self.bodies[i]["messages"][1]["content"]


def back_calls(dev) -> int:
    return sum(1 for c in dev.calls if "KEYCODE_BACK" in c)


async def run(dev, tmp_path, llm: Scripted, steps=6, **kw):
    c = crawler(dev, tmp_path)
    for k, v in kw.items():
        setattr(c, k, v)
    assert await c.launch()
    async with llm.client() as client:
        await explore(c, steps, settings(), client, lambda _m: None, c.secrets)
    return c


def test_helpers():
    assert llm_extra("sarvam-105b") == {"reasoning_effort": None}
    assert llm_extra("deepseekv4.1-flash-1017") == {"reasoning_effort": "none"}
    assert parse_reply('{"action":"scroll","direction":"up"}', 0)["direction"] == "up"
    assert parse_reply('{"action":"tap","node":5}', 2) is None
    assert parse_reply("nope", 2) is None
    a = parse_ui_nodes(make_xml(["Hello"], ["Go"]))
    b = parse_ui_nodes(make_xml(["Different text"], ["Go"]))
    assert signature(".Main", a) == signature(".Main", b)  # text changes are ignored
    assert signature(".Main", a) != signature(".Other", a)


async def test_login_wall_ask_then_fill(tmp_path):
    login = make_xml(
        ["Welcome"], ["Sign in"],
        fields=[{"rid": "x:id/email", "hint": "Email"}, {"rid": "x:id/pw", "hint": "Password", "password": True}],
    )  # fmt: skip
    dev = FakeDevice([login, make_xml(["Home"], ["Orders"])])

    async def request_input(fields, reason):
        c.secrets = Secrets(TestCredentials(login="asha@real.test", password="Hunter22!x"))
        return True

    llm = Scripted([
        {"action": "ask", "fields": [{"key": "login", "label": "Email", "kind": "email"}], "reason": "need login"},
        {"action": "fill", "node": 2, "text": "<LOGIN>", "reason": "email"},
        {"action": "fill", "node": 3, "text": "<PASSWORD>", "reason": "password"},
        {"action": "tap", "node": 1, "reason": "sign in"},
        {"action": "done", "reason": "enough"},
    ])  # fmt: skip
    c = crawler(dev, tmp_path)
    c.request_input = request_input
    await c.launch()
    async with llm.client() as client:
        await explore(c, 6, settings(), client, lambda _m: None, None)
    assert any("asha@real.test" in t for t in dev.typed) and any("Hunter22!x" in t for t in dev.typed)
    dump = json.dumps([s.model_dump() for s in c.j.steps])
    assert "asha@real.test" not in dump and "Hunter22" not in dump
    assert "Human can answer 'ask': yes" in llm.user(0)
    assert "human answered" in llm.user(1).lower()
    assert "Hunter22" not in json.dumps(llm.bodies)
    assert taps(dev)[-1] == ["250", "85"] or any(s.action == "tap" and s.target == "Sign in" for s in c.j.steps)


async def test_ask_without_request_input_is_a_skip(tmp_path):
    dev = FakeDevice([make_xml(["Login"], ["Skip"])])
    llm = Scripted([{"action": "ask", "fields": [], "reason": "need"}, {"action": "tap", "node": 1, "reason": "skip"}])
    c = await run(dev, tmp_path, llm, steps=3)
    assert "Human can answer 'ask': no" in llm.user(0)
    assert "No human can answer" in llm.user(1)
    assert any(s.target == "Skip" for s in c.j.steps)


class Leaving(FakeDevice):
    """The first tap opens another app; BACK returns."""

    leave_once = True

    async def __call__(self, argv, timeout):
        out = await super().__call__(argv, timeout)
        joined = " ".join(argv)
        if "input tap" in joined and self.leave_once:
            self.leave_once = False
            self.foreground = "com.android.chrome/.Main"
        elif "KEYCODE_BACK" in joined and not self.foreground.startswith(PKG):
            self.foreground = f"{PKG}/{self.launcher}"
        return out


async def test_leaving_the_app_is_recovered_and_remembered(tmp_path):
    dev = Leaving([make_xml(["Home"], ["Rate us", "Offers"]), make_xml(["Offers page"], ["Back to home"])])
    llm = Scripted([{"action": "tap", "node": 1, "reason": "rate"}, {"action": "tap", "node": 2, "reason": "offers"}])
    c = await run(dev, tmp_path, llm, steps=2)
    assert any("Left the app (opened com.android.chrome)" in (s.note or "") for s in c.j.steps)
    assert dev.foreground.startswith(PKG)
    msg = llm.user(1)
    assert "Rate us" in msg and "opened another app" in msg and "Useless" in msg


async def test_never_back_on_root(tmp_path):
    dev = FakeDevice([make_xml(["Home"], ["Orders"])])
    llm = Scripted([{"action": "back", "reason": "go back"}, {"action": "done", "reason": "x"}])
    c = await run(dev, tmp_path, llm, steps=3)
    assert back_calls(dev) == 0
    assert "root screen" in llm.user(1)
    assert taps(dev) == [["250", "185"]]  # converted to the unvisited control "Orders"
    assert c.j.steps[-1].action in ("tap", "wait")


async def test_already_tried_is_avoided(tmp_path):
    # tapping never changes this screen, so repeats are visible
    xml = make_xml(["Home"], ["Products", "Orders"])
    dev = FakeDevice([xml])
    again = {"action": "tap", "node": 1, "reason": "again"}
    llm = Scripted([again, again, again, again])
    await run(dev, tmp_path, llm, steps=4)
    t = taps(dev)
    assert t[0] == ["250", "185"]  # Products once
    assert ["250", "245"] in t  # fallback chose the untried Orders
    assert t.count(["250", "185"]) == 1
    assert "already tried" in llm.user(2)


async def test_denied_tap_is_vetoed(tmp_path):
    dev = FakeDevice([make_xml(["Home"], ["Log out", "Orders"])])
    llm = Scripted([{"action": "tap", "node": 1, "reason": "x"}, {"action": "tap", "node": 2, "reason": "y"}])
    c = await run(dev, tmp_path, llm, steps=2)
    assert ["250", "185"] not in taps(dev)  # Log out never tapped
    assert any(not s.ok and "unsafe" in (s.note or "") for s in c.j.steps)
    assert "vetoed" in llm.user(1)


async def test_scroll_and_wait(tmp_path):
    dev = FakeDevice([make_xml(["Home"], ["Orders"])])
    llm = Scripted([{"action": "scroll", "direction": "down", "reason": "more"}, {"action": "wait", "reason": "load"}])
    await run(dev, tmp_path, llm, steps=2)
    assert any("input" in c and "swipe" in c for c in dev.calls)


async def test_no_usable_llm_falls_back_to_heuristic(tmp_path):
    dev = FakeDevice([make_xml(["Home"], ["Products"]), make_xml(["List"])])
    llm = Scripted([], status=500)
    c = await run(dev, tmp_path, llm, steps=2)
    assert taps(dev) and c.j.steps[1].action == "tap" and c.j.steps[1].target == "Products"


async def test_crawler_run_without_explorer_is_heuristic(tmp_path):
    dev = FakeDevice([make_xml(["Home"], ["Products"]), make_xml(["List"])])
    c = crawler(dev, tmp_path)
    assert c.explorer is None
    j = await c.run(2)
    assert [s.action for s in j.steps][:2] == ["launch", "tap"]


async def test_crawler_run_uses_explorer_and_survives_its_failure(tmp_path):
    dev = FakeDevice([make_xml(["Home"], ["Products"]), make_xml(["List"])])
    c = crawler(dev, tmp_path)
    seen = []

    async def brain(cr, n):
        seen.append(n)
        raise RuntimeError("boom")

    c.explorer = brain
    j = await c.run(2)
    assert seen == [2] and any(s.target == "explorer" for s in j.steps) and any(s.action == "tap" for s in j.steps)
