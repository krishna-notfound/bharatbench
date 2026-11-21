import asyncio

import pytest

from harness.adb import RC_MISSING, RC_TIMEOUT, Adb, subprocess_runner
from harness.profiles import FILLER, ProfileError, ProfileManager

from .conftest import FakeRunner


async def nosleep(_: float) -> None:
    await asyncio.sleep(0)


async def test_adb_argv_prefix(adb, runner):
    await adb.shell("echo", "hi")
    await adb.run(["exec-out", "cat", "/sdcard/ui.xml"])
    assert runner.calls[0] == ["adb", "-s", "emulator-5554", "shell", "echo", "hi"]
    assert runner.calls[1] == ["adb", "-s", "emulator-5554", "exec-out", "cat", "/sdcard/ui.xml"]


async def test_real_runner_missing_binary_and_timeout():
    rc, _, _ = await subprocess_runner(["definitely-not-a-binary-xyz"], 2)
    assert rc == RC_MISSING
    import sys

    rc, _, err = await subprocess_runner([sys.executable, "-c", "import time; time.sleep(30)"], 0.5)
    assert rc == RC_TIMEOUT and err == b"timeout"


async def test_budget_apply_revert(adb, runner):
    pm = ProfileManager(adb, nosleep)
    await pm.apply("budget_2gb")
    await pm.revert("budget_2gb")
    base = ["adb", "-s", "emulator-5554"]
    assert runner.calls == [
        [*base, "emu", "network", "speed", "2000:2000"],
        [*base, "emu", "network", "delay", "200:600"],
        [*base, "emu", "network", "speed", "full"],
        [*base, "emu", "network", "delay", "none"],
    ]


async def test_battery_apply_revert(adb, runner):
    pm = ProfileManager(adb, nosleep)
    await pm.apply("battery_saver")
    await pm.revert("battery_saver")
    assert runner.shell_args() == [
        ["dumpsys", "battery", "unplug"],
        ["dumpsys", "battery", "set", "level", "10"],
        ["settings", "put", "global", "low_power", "1"],
        ["settings", "put", "global", "low_power", "0"],
        ["dumpsys", "battery", "reset"],
    ]


async def test_low_storage_fallocate_and_revert(fixtures):
    r = FakeRunner({"df -k": (0, (fixtures / "df.txt").read_text())})
    pm = ProfileManager(Adb("adb", "emulator-5554", r), nosleep)
    note = await pm.apply("low_storage")
    expected = (4900000 - 400 * 1024) * 1024
    assert r.shell_args()[1] == ["fallocate", "-l", str(expected), FILLER]
    assert "MB written" in note
    await pm.revert("low_storage")
    assert r.shell_args()[-1] == ["rm", "-f", FILLER]


async def test_low_storage_dd_fallback(fixtures):
    r = FakeRunner({"df -k": (0, (fixtures / "df.txt").read_text()), "fallocate": (1, "")})
    pm = ProfileManager(Adb("adb", "emulator-5554", r), nosleep)
    await pm.apply("low_storage")
    dd = r.shell_args()[-1]
    assert dd[0] == "dd" and f"of={FILLER}" in dd


async def test_low_storage_already_low():
    r = FakeRunner({"df -k": (0, "Filesystem 1K-blocks Used Available Use% Mounted\n/dev/x 100 90 300000 99% /data")})
    pm = ProfileManager(Adb("adb", "emulator-5554", r), nosleep)
    note = await pm.apply("low_storage")
    assert "already low" in note
    assert not any(c[4] == "fallocate" for c in r.calls if len(c) > 4)


async def test_flaky_toggles_then_reverts(adb, runner):
    pm = ProfileManager(adb, nosleep)
    await pm.apply("flaky_network")
    for _ in range(20):
        await asyncio.sleep(0)
    await pm.revert("flaky_network")
    shells = runner.shell_args()
    assert ["svc", "data", "disable"] in shells and ["svc", "wifi", "disable"] in shells
    assert shells[-2:] == [["svc", "data", "enable"], ["svc", "wifi", "enable"]]
    assert pm.toggles >= 1


async def test_apply_failure_raises():
    r = FakeRunner({"dumpsys battery unplug": (1, "boom")})
    pm = ProfileManager(Adb("adb", "emulator-5554", r), nosleep)
    with pytest.raises(ProfileError):
        await pm.apply("battery_saver")


async def test_baseline_noop(adb, runner):
    pm = ProfileManager(adb, nosleep)
    assert await pm.apply("baseline") == "no shaping"
    await pm.revert("baseline")
    assert runner.calls == []


# ---- redroid (tc on host veth) ----
IP_LINK_CONTAINER = "2: eth0@if4: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP\n"
IP_LINK_HOST = (
    "1: lo: <LOOPBACK> mtu 65536\n"
    "3: docker0: <BROADCAST> mtu 1500\n"
    "4: veth5ae5bd0@if2: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 master docker0\n"
)


def redroid_pm(responses=None):
    adb_r = FakeRunner({"ip -o link show eth0": (0, IP_LINK_CONTAINER)})
    host_r = FakeRunner({"/usr/sbin/ip -o link": (0, IP_LINK_HOST), **(responses or {})})
    pm = ProfileManager(Adb("adb", "127.0.0.1:5555", adb_r), nosleep, "redroid", host=host_r)
    return pm, adb_r, host_r


def tc_calls(host_r):
    return [c[3:] for c in host_r.calls if c[:3] == ["sudo", "-n", "/usr/sbin/tc"]]


def test_veth_discovery_parsers():
    from harness.profiles import find_link_name, parse_peer_ifindex

    assert parse_peer_ifindex(IP_LINK_CONTAINER) == 4
    assert parse_peer_ifindex("garbage") is None
    assert find_link_name(IP_LINK_HOST, 4) == "veth5ae5bd0"
    assert find_link_name(IP_LINK_HOST, 9) is None


async def test_redroid_budget_netem_and_revert():
    pm, _, host_r = redroid_pm()
    note = await pm.apply("budget_2gb")
    await pm.revert("budget_2gb")
    calls = tc_calls(host_r)
    assert calls[0] == ["qdisc", "replace", "dev", "veth5ae5bd0", "root", "netem", "rate", "2mbit", "delay", "200ms", "100ms"]
    assert calls[1][:5] == ["qdisc", "replace", "dev", "veth5ae5bd0", "handle"]
    assert "police" in calls[2]
    assert calls[-2:] == [
        ["qdisc", "del", "dev", "veth5ae5bd0", "root"],
        ["qdisc", "del", "dev", "veth5ae5bd0", "ingress"],
    ]
    assert "2 GB" in note and "veth5ae5bd0" in note


async def test_redroid_flaky_blackout_cycles():
    pm, _, host_r = redroid_pm()
    await pm.apply("flaky_network")
    for _ in range(8):
        await asyncio.sleep(0)
    await pm.revert("flaky_network")
    calls = tc_calls(host_r)
    assert ["qdisc", "replace", "dev", "veth5ae5bd0", "root", "netem", "loss", "100%"] in calls
    assert ["qdisc", "del", "dev", "veth5ae5bd0", "root"] in calls
    assert pm.toggles >= 1


async def test_redroid_tc_failure_is_not_applied():
    pm, _, _ = redroid_pm({"qdisc replace": (1, "sudo: a password is required")})
    with pytest.raises(ProfileError, match="tc qdisc"):
        await pm.apply("budget_2gb")


async def test_redroid_revert_idempotent_when_no_qdisc():
    pm, _, _ = redroid_pm({"qdisc del": (2, "Error: Invalid handle.")})
    await pm.net.device()
    await pm.revert("budget_2gb")  # must not raise


async def test_redroid_flaky_tc_failure_is_not_applied():
    pm, _, _ = redroid_pm({"netem loss": (2, "Error: Specified qdisc kind is unknown.")})
    with pytest.raises(ProfileError, match="qdisc kind is unknown"):
        await pm.apply("flaky_network")


async def test_redroid_missing_veth_fails_fast():
    pm, _, _ = redroid_pm({"/usr/sbin/ip -o link": (0, "1: lo: <LOOPBACK>\n")})
    with pytest.raises(ProfileError, match="no host interface"):
        await pm.apply("flaky_network")


async def test_redroid_low_storage_refused(adb):
    pm = ProfileManager(adb, nosleep, "redroid")
    with pytest.raises(ProfileError, match="shared host disk"):
        await pm.apply("low_storage")
