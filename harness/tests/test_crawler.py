import asyncio

from harness.adb import Adb
from harness.crawler import Crawler

from .device import PKG, FakeDevice, make_xml


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    async def sleep(self, s: float) -> None:
        self.t += s
        await asyncio.sleep(0)


def crawler(dev, tmp_path, profile="baseline", activity=".MainActivity"):
    clock = Clock()
    return Crawler(
        Adb("adb", "emulator-5554", dev), PKG, activity, tmp_path, profile, sleep=clock.sleep, clock=clock.now
    )


def taps(dev):
    return [c[-2:] for c in dev.calls if "tap" in c]


async def test_journey_launch_tap_denylist_back(tmp_path):
    dev = FakeDevice([make_xml(["Home"], ["Log out", "Products", "Pay now"]), make_xml(["List"])])
    c = crawler(dev, tmp_path)
    j = await c.run(3)
    assert j.launched and j.launch_ms == 777
    assert ["adb", "-s", "emulator-5554", "shell", "am", "start", "-W", "-n", f"{PKG}/.MainActivity"] in dev.calls
    assert taps(dev) == [["250", "245"]]  # only "Products"; Log out / Pay now denied
    assert [s.action for s in j.steps] == ["launch", "tap", "back", "back"]
    assert j.steps[1].target == "Products"
    assert [s.index for s in j.screens] == [0, 1, 2, 3]
    assert (tmp_path / "screens" / "baseline_0.png").read_bytes().startswith(b"\x89PNG")
    assert (tmp_path / "ui" / "baseline_1.xml").exists()
    assert j.screens[0].screenshot == "screens/baseline_0.png"


async def test_launch_resolves_activity_when_missing(tmp_path):
    dev = FakeDevice([make_xml(["Home"])])
    j = await crawler(dev, tmp_path, activity=None).run(0)
    assert j.launched
    assert any("resolve-activity" in " ".join(c) for c in dev.calls)


async def test_launch_failure(tmp_path):
    dev = FakeDevice([make_xml(["Home"])])
    dev.foreground = "com.android.launcher/.Home"
    dev.fail["am start"] = 1
    j = await crawler(dev, tmp_path).run(3)
    assert not j.launched and j.screens == []


async def test_stuck_loading_after_15s(tmp_path):
    dev = FakeDevice([make_xml(["Loading"], progress=True)])
    j = await crawler(dev, tmp_path).run(1)
    assert j.stuck_loading


async def test_not_stuck_when_screen_changes(tmp_path):
    dev = FakeDevice([make_xml(["Loading"], progress=True), make_xml(["Done"])])
    dev.change_after_dumps = 3  # screen resolves by itself after a couple of polls
    j = await crawler(dev, tmp_path).run(1)
    assert not j.stuck_loading


async def test_cancel_stops_between_steps(tmp_path):
    dev = FakeDevice([make_xml(["Home"], ["A", "B", "C"])])
    c = crawler(dev, tmp_path)
    c.cancelled = lambda: True
    j = await c.run(5)
    assert j.launched and taps(dev) == []


async def test_process_death_state_lost(tmp_path):
    home = make_xml(["Home", "Welcome back"], ["Cart"])
    cart = make_xml(["Your cart", "3 items", "Total"], ["Checkout ok"])
    dev = FakeDevice([home, cart, cart])
    dev.after_kill_screen = make_xml(["Splash"], ["Start"])
    j = await crawler(dev, tmp_path, "process_death").run(2)
    assert j.state_lost_after_restore is True
    seq = [c[4:] for c in dev.calls if c[3:4] == ["shell"] and ("KEYCODE_HOME" in c or "kill" in c or "monkey" in c)]
    assert seq[0] == ["input", "keyevent", "KEYCODE_HOME"]
    assert seq[1] == ["am", "kill", PKG]
    assert seq[2][:3] == ["monkey", "-p", PKG]
    assert [s.action for s in j.steps][-3:] == ["background", "kill", "restore"]


async def test_process_death_state_preserved(tmp_path):
    cart = make_xml(["Your cart", "3 items"], ["Back to shop"])
    dev = FakeDevice([make_xml(["Home"], ["Cart"]), cart, cart])
    dev.after_kill_screen = cart
    j = await crawler(dev, tmp_path, "process_death").run(2)
    assert j.state_lost_after_restore is False
