"""Condition profile appliers. The `how` text in api/app/profiles.py is the spec for each."""

import asyncio
import contextlib
import re
from collections.abc import Awaitable, Callable

from .adb import Adb, Runner, subprocess_runner
from .models import ProfileId
from .parsers import parse_df_free_kb

FILLER = "/data/local/tmp/bb_filler"
TARGET_FREE_KB = 400 * 1024
FLAKY_OFF_S = 6
FLAKY_ON_S = 4

Sleep = Callable[[float], Awaitable[None]]


class ProfileError(RuntimeError):
    pass


def parse_peer_ifindex(ip_link_out: str) -> int | None:
    """`2: eth0@if4: <...>` inside the container -> 4 (ifindex of the host-side veth)."""
    m = re.search(r"eth0@if(\d+)", ip_link_out)
    return int(m.group(1)) if m else None


def find_link_name(ip_link_out: str, ifindex: int) -> str | None:
    """From host `ip -o link`: `4: veth5ae5bd0@if2: <...>` -> veth5ae5bd0."""
    for line in ip_link_out.splitlines():
        m = re.match(r"\s*(\d+):\s+([^@:\s]+)", line)
        if m and int(m.group(1)) == ifindex:
            return m.group(2)
    return None


class HostNet:
    """tc netem on the host-side veth of the redroid container (NOPASSWD sudo limited to tc).

    root netem shapes traffic TO the app (download); an ingress policer limits traffic FROM it (upload).
    """

    def __init__(self, adb: Adb, host: Runner, tc: str, ip: str, sudo: str) -> None:
        self.adb, self._host, self.tc, self.ip, self.sudo = adb, host, tc, ip, sudo
        self.dev: str | None = None

    async def _host_run(self, argv: list[str], timeout: float = 15) -> tuple[int, str]:
        rc, out, err = await self._host(argv, timeout)
        return rc, (out or err).decode("utf-8", "replace")

    async def _tc(self, *args: str) -> None:
        rc, msg = await self._host_run([self.sudo, "-n", self.tc, *args])
        if rc != 0:
            raise ProfileError(f"tc {' '.join(args)} failed rc={rc}: {msg.strip()[:200]}")

    async def device(self) -> str:
        if self.dev:
            return self.dev
        _, out, _ = await self.adb.shell("ip", "-o", "link", "show", "eth0", timeout=15)
        idx = parse_peer_ifindex(out)
        if idx is None:
            raise ProfileError("cannot find the container's eth0 peer ifindex")
        rc, host_out = await self._host_run([self.ip, "-o", "link"])
        name = find_link_name(host_out, idx) if rc == 0 else None
        if not name:
            raise ProfileError(f"no host interface with ifindex {idx}")
        self.dev = name
        return name

    async def shape(self, rate: str, delay_ms: int, jitter_ms: int) -> None:
        dev = await self.device()
        await self._tc("qdisc", "replace", "dev", dev, "root", "netem", "rate", rate, "delay", f"{delay_ms}ms", f"{jitter_ms}ms")
        await self._tc("qdisc", "replace", "dev", dev, "handle", "ffff:", "ingress")
        await self._tc(
            "filter", "replace", "dev", dev, "parent", "ffff:", "protocol", "all", "prio", "1",
            "u32", "match", "u32", "0", "0", "police", "rate", rate, "burst", "32k", "drop", "flowid", ":1",
        )  # fmt: skip

    async def blackout(self, on: bool) -> None:
        dev = await self.device()
        if on:
            await self._tc("qdisc", "replace", "dev", dev, "root", "netem", "loss", "100%")
        else:
            await self._del(dev, "root")

    async def _del(self, dev: str, kind: str) -> None:
        """Delete a qdisc; "nothing there" is success (revert must be idempotent)."""
        rc, msg = await self._host_run([self.sudo, "-n", self.tc, "qdisc", "del", "dev", dev, kind])
        benign = ("No such file", "Cannot find", "Invalid argument", "Cannot delete", "Invalid handle")
        if rc != 0 and not any(b in msg for b in benign):
            raise ProfileError(f"tc qdisc del {kind} failed rc={rc}: {msg.strip()[:100]}")

    async def clear(self) -> None:
        dev = await self.device()
        await self._del(dev, "root")
        await self._del(dev, "ingress")


class ProfileManager:
    def __init__(
        self,
        adb: Adb,
        sleep: Sleep = asyncio.sleep,
        device_kind: str = "emulator",
        host: Runner = subprocess_runner,
        tc: str = "/usr/sbin/tc",
        ip: str = "/usr/sbin/ip",
        sudo: str = "sudo",
    ) -> None:
        self.adb = adb
        self._sleep = sleep
        self.kind = device_kind
        self.net = HostNet(adb, host, tc, ip, sudo)
        self._flaky: asyncio.Task[None] | None = None
        self.toggles = 0

    @property
    def redroid(self) -> bool:
        return self.kind == "redroid"

    async def _ok(self, args: list[str], timeout: float = 30, shell: bool = True) -> str:
        rc, out, err = await (self.adb.shell(*args, timeout=timeout) if shell else self.adb.run(args, timeout))
        if rc != 0:
            raise ProfileError(f"`{' '.join(args)}` failed rc={rc}: {(err or out).strip()[:200]}")
        return out

    async def apply(self, profile_id: ProfileId) -> str:
        if profile_id == "baseline":
            return "no shaping"
        if profile_id == "budget_2gb":
            if self.redroid:
                await self.net.shape("2mbit", 200, 100)
                return (
                    "container RAM capped at 2 GB (docker --memory, cgroup OOM enforced); "
                    f"tc netem on {self.net.dev}: download 2mbit + 200ms delay (100ms jitter), "
                    "upload policed to 2mbit; CPU not throttled"
                )
            await self._ok(["emu", "network", "speed", "2000:2000"], shell=False)
            await self._ok(["emu", "network", "delay", "200:600"], shell=False)
            return "network speed 2000:2000 kbps, delay 200:600 ms; RAM fixed by AVD at 2048 MB; CPU not throttled"
        if profile_id == "flaky_network":
            if self.redroid:
                await self.net.blackout(True)  # first blackout is synchronous: tc failure => applied=false
                self._flaky = asyncio.create_task(self._flaky_loop(dark=True))
                return (
                    f"tc netem loss 100% on {self.net.dev} for {FLAKY_OFF_S}s, restored for {FLAKY_ON_S}s, "
                    "cycling during the journey (svc wifi/data do not cut connectivity on redroid)"
                )
            self._flaky = asyncio.create_task(self._flaky_loop())
            return f"svc data/wifi toggled: {FLAKY_OFF_S}s off, {FLAKY_ON_S}s on during journey"
        if profile_id == "low_storage":
            if self.redroid:
                raise ProfileError(
                    "redroid /data is the shared host disk (`df /data` reports the host root fs); filling it to "
                    "~400 MB free would endanger the API host, so this condition is not applied"
                )
            return await self._fill_storage()
        if profile_id == "battery_saver":
            await self._ok(["dumpsys", "battery", "unplug"])
            await self._ok(["dumpsys", "battery", "set", "level", "10"])
            await self._ok(["settings", "put", "global", "low_power", "1"])
            return "battery unplugged at 10% with low_power=1 (settings flag set; background-restriction effect not verified)"
        if profile_id == "process_death":
            return "HOME + am kill + relaunch performed by the crawler after step 2"
        raise ProfileError(f"unknown profile {profile_id}")

    async def revert(self, profile_id: ProfileId) -> None:
        if profile_id in ("budget_2gb", "flaky_network") and self.redroid:
            await self._stop_flaky()
            if self.net.dev:
                await self.net.clear()
        elif profile_id == "budget_2gb":
            await self._ok(["emu", "network", "speed", "full"], shell=False)
            await self._ok(["emu", "network", "delay", "none"], shell=False)
        elif profile_id == "flaky_network":
            await self._stop_flaky()
            await self._set_radios(True)
        elif profile_id == "low_storage" and not self.redroid:
            await self._ok(["rm", "-f", FILLER])
        elif profile_id == "battery_saver":
            await self._ok(["settings", "put", "global", "low_power", "0"])
            await self._ok(["dumpsys", "battery", "reset"])

    async def _set_radios(self, enabled: bool) -> None:
        verb = "enable" if enabled else "disable"
        await self._ok(["svc", "data", verb])
        await self._ok(["svc", "wifi", verb])

    async def _flaky_loop(self, dark: bool = False) -> None:
        while True:
            if not dark:
                if self.redroid:
                    await self.net.blackout(True)
                else:
                    await self._set_radios(False)
            dark = False
            await self._sleep(FLAKY_OFF_S)
            if self.redroid:
                await self.net.blackout(False)
            else:
                await self._set_radios(True)
            self.toggles += 1
            await self._sleep(FLAKY_ON_S)

    async def _stop_flaky(self) -> None:
        task, self._flaky = self._flaky, None
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, ProfileError):
                await task

    async def _fill_storage(self) -> str:
        out = await self._ok(["df", "-k", "/data"])
        free_kb = parse_df_free_kb(out)
        if free_kb is None:
            raise ProfileError("could not parse `df -k /data`")
        if free_kb <= TARGET_FREE_KB:
            return f"already low: only {free_kb // 1024} MB free, no filler written"
        fill_bytes = (free_kb - TARGET_FREE_KB) * 1024
        rc, _, _ = await self.adb.shell("fallocate", "-l", str(fill_bytes), FILLER, timeout=120)
        if rc != 0:
            await self._ok(
                ["dd", "if=/dev/zero", f"of={FILLER}", "bs=1048576", f"count={fill_bytes // 1048576}"],
                timeout=300,
            )
        return f"filler of {fill_bytes // 1048576} MB written; ~400 MB left free (was {free_kb // 1024} MB)"
