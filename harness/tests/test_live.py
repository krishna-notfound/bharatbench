import asyncio
import struct

from fastapi.testclient import TestClient

from harness.adb import Adb
from harness.crawler import Crawler
from harness.live import LiveState, png_size
from harness.main import create_app
from harness.models import HarnessJob

from .conftest import FakeRunner
from .device import PKG, FakeDevice, make_xml
from .test_api_jobs import H, settings
from .test_crawler import Clock

PNG = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 720, 1280) + b"\x08\x06\x00\x00\x00"


def test_png_size():
    assert png_size(PNG) == (720, 1280)
    assert png_size(b"nope") is None


async def test_loop_keeps_only_latest_frame():
    live = LiveState()
    live.start(Adb("adb", "s", FakeRunner({"screencap": (0, PNG)})), interval=0.01)
    await asyncio.sleep(0.1)
    await live.stop()
    assert live.frame == PNG and live.screen == (720, 1280) and live.running is False
    assert live.public()["screen"] == {"w": 720, "h": 1280}


async def test_crawler_records_tap_point_and_screen(tmp_path):
    dev = FakeDevice([make_xml(["Home"], ["Products"]), make_xml(["List"])])
    clock = Clock()
    live = LiveState()
    c = Crawler(
        Adb("adb", "emulator-5554", dev), PKG, ".MainActivity", tmp_path, "baseline",
        sleep=clock.sleep, clock=clock.now, on_step=live.note_step,
    )  # fmt: skip
    j = await c.run(1)
    tap = j.steps[1]
    assert (tap.action, tap.target, tap.x, tap.y) == ("tap", "Products", 250, 185)
    assert tap.screen == 1 and j.steps[0].screen == 0
    pub = live.public()
    assert pub["action"] == "tap" and pub["tap"] == {"x": 250, "y": 185}


def test_live_endpoints_auth_and_frames(tmp_path):
    app = create_app(settings(tmp_path), runner=FakeRunner())
    jid = "a" * 32
    app.state.jobs.jobs[jid] = HarnessJob(job_id=jid, run_id="r", status="running")
    c = TestClient(app)
    assert c.get(f"/jobs/{jid}/live").status_code == 401
    assert c.get(f"/jobs/{jid}/live.png").status_code == 401
    assert c.get(f"/jobs/{jid}/live", headers=H).json()["running"] is False
    assert c.get(f"/jobs/{jid}/live.png", headers=H).status_code == 404
    st = LiveState(frame=PNG, screen=(720, 1280), profile_id="baseline")
    app.state.jobs.live[jid] = st
    body = c.get(f"/jobs/{jid}/live", headers=H).json()
    assert body["profile_id"] == "baseline" and body["running"] is True and body["tap"] is None
    r = c.get(f"/jobs/{jid}/live.png", headers=H)
    assert r.content == PNG and r.headers["cache-control"] == "no-store"
