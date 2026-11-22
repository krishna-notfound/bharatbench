import json

import httpx

from harness.agent import drive
from harness.jobs import JobRunner
from harness.models import AgentTest, HarnessJobRequest, TestCredentials
from harness.secrets import Secrets
from harness.settings import Settings

from .device import FakeDevice, make_xml
from .test_crawler import Clock, crawler, taps  # noqa: F401

PASSWORD = "S3cret!pw"
CREDS = TestCredentials(login="tester@example.com", password=PASSWORD, note="OTP is 482913 in test mode")
TEST = AgentTest(id="login", title="Log in", goal="Log in", success_check="home visible")
LOGIN_SCREEN = make_xml(
    ["Welcome"], ["Sign in"],
    fields=[{"hint": "Email"}, {"hint": "Password", "password": True}, {"hint": "Enter OTP"}],
)  # fmt: skip


def llm(answers, seen):
    it = iter(answers)

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.content.decode())
        return httpx.Response(200, json={"choices": [{"message": {"content": next(it)}}]})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_secrets_tokenize_mask_expand():
    s = Secrets(CREDS)
    assert s.otp == "482913"
    assert s.expand("<LOGIN>|<PASSWORD>|<OTP>") == f"tester@example.com|{PASSWORD}|482913"
    assert PASSWORD not in s.mask(f"typed {PASSWORD}") and "***" in s.mask(f"typed {PASSWORD}")
    assert s.tokenize(f"x {PASSWORD}") == "x <PASSWORD>"
    assert "482913" not in s.llm_note() and "<OTP>" in s.prompt_addendum()
    assert not Secrets(None).available


async def test_crawler_uses_account_and_hides_it(tmp_path):
    dev = FakeDevice([LOGIN_SCREEN, make_xml(["Home"])])
    c = crawler(dev, tmp_path)
    c.secrets = Secrets(CREDS)
    j = await c.run(1)
    assert ["tester@example.com", PASSWORD, "482913"] == dev.typed[:3]
    fills = [s for s in j.steps if s.action == "fill"]
    assert [s.note for s in fills] == ["Filling login (hidden)", "Filling password (hidden)", "Filling OTP (hidden)"]
    stored = json.dumps([s.model_dump() for s in j.steps]) + "".join(
        p.read_text("utf-8") for p in tmp_path.rglob("*.xml")
    )
    assert PASSWORD not in stored and "482913" not in stored


async def test_crawler_without_account_uses_fake_values(tmp_path):
    dev = FakeDevice([LOGIN_SCREEN, make_xml(["Home"])])
    await crawler(dev, tmp_path).run(1)
    assert PASSWORD not in "".join(dev.typed) and "asha.verma@example.com" in dev.typed


async def test_agent_llm_never_sees_password_and_substitution_at_input(tmp_path):
    dev = FakeDevice([LOGIN_SCREEN, make_xml(["Home"])])
    seen: list[str] = []
    client = llm(
        [
            '{"action":"fill","node":2,"text":"<PASSWORD>","reason":"type the password"}',
            '{"action":"done","reason":"logged in"}',
        ],
        seen,
    )
    caps: list[str] = []
    res = await drive(
        crawler(dev, tmp_path), TEST, Settings(harness_token="t", llm_api_key="k"), client, caps.append,
        secrets=Secrets(CREDS),
    )  # fmt: skip
    assert res.passed is True and PASSWORD in dev.typed  # real value typed on the device
    blob = "".join(seen) + json.dumps([s.model_dump() for s in res.steps]) + "".join(caps)
    assert PASSWORD not in blob and "482913" not in blob  # never sent to the LLM, stored or shown
    assert "<PASSWORD>" in seen[0] and any("Filling password (hidden)" in (s.note or "") for s in res.steps)


async def test_offline_phase_scheduled_and_reverts(tmp_path, monkeypatch):
    dev = FakeDevice([LOGIN_SCREEN, make_xml(["Home"], ["Feed"])])
    clock = Clock()
    s = Settings(harness_token="t", llm_api_key="k", jobs_dir=tmp_path)
    runner = JobRunner(s, crawler(dev, tmp_path).adb, sleep=clock.sleep, clock=clock.now)
    req = HarnessJobRequest(
        run_id="r", package_name="com.example.shop", profiles=["baseline"],
        credentials=TestCredentials(login="a@b.co", password=PASSWORD, offline_after_login=True),
    )  # fmt: skip
    assert runner._offline_wanted(req)
    assert not runner._offline_wanted(HarnessJobRequest(run_id="r", package_name="com.example.shop", profiles=[]))
    seen: list[str] = []
    client = llm(
        ['{"action":"done","reason":"logged in"}', '{"action":"fail","reason":"feed spinner never ends"}'], seen
    )
    monkeypatch.setattr("harness.jobs.httpx.AsyncClient", lambda: client)
    applied: list[str] = []

    async def fake_apply(self, pid):
        applied.append(f"apply:{pid}")
        return "ok"

    async def fake_revert(self, pid):
        applied.append(f"revert:{pid}")

    monkeypatch.setattr("harness.jobs.ProfileManager.apply", fake_apply)
    monkeypatch.setattr("harness.jobs.ProfileManager.revert", fake_revert)
    job, _ = runner.start(req)
    out: list = []
    await runner._agent_tests(job, req, out)
    assert [(t.id, t.passed, t.reason) for t in out] == [("offline_after_login", False, "feed spinner never ends")]
    assert "spinner" in out[0].reason and len(seen) == 2
    assert PASSWORD not in "".join(seen) + out[0].model_dump_json()
    assert applied == ["apply:flaky_network", "revert:flaky_network"]  # login happened before the network drop
