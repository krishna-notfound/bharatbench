"""Condition profile appliers. The `how` text in api/app/profiles.py is the spec for each."""

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

from .adb import Adb
from .models import ProfileId
from .parsers import parse_df_free_kb

FILLER = "/data/local/tmp/bb_filler"
TARGET_FREE_KB = 400 * 1024
FLAKY_OFF_S = 6
FLAKY_ON_S = 4

Sleep = Callable[[float], Awaitable[None]]


class ProfileError(RuntimeError):
    pass


class ProfileManager:
    def __init__(self, adb: Adb, sleep: Sleep = asyncio.sleep) -> None:
        self.adb = adb
        self._sleep = sleep
        self._flaky: asyncio.Task[None] | None = None
        self.toggles = 0

    async def _ok(self, args: list[str], timeout: float = 30, shell: bool = True) -> str:
        rc, out, err = await (self.adb.shell(*args, timeout=timeout) if shell else self.adb.run(args, timeout))
        if rc != 0:
            raise ProfileError(f"`{' '.join(args)}` failed rc={rc}: {(err or out).strip()[:200]}")
        return out

    async def apply(self, profile_id: ProfileId) -> str:
        if profile_id == "baseline":
            return "no shaping"
        if profile_id == "budget_2gb":
            await self._ok(["emu", "network", "speed", "2000:2000"], shell=False)
            await self._ok(["emu", "network", "delay", "200:600"], shell=False)
            return "network speed 2000:2000 kbps, delay 200:600 ms; RAM fixed by AVD at 2048 MB; CPU not throttled"
        if profile_id == "flaky_network":
            self._flaky = asyncio.create_task(self._flaky_loop())
            return f"svc data/wifi toggled: {FLAKY_OFF_S}s off, {FLAKY_ON_S}s on during journey"
        if profile_id == "low_storage":
            return await self._fill_storage()
        if profile_id == "battery_saver":
            await self._ok(["dumpsys", "battery", "unplug"])
            await self._ok(["dumpsys", "battery", "set", "level", "10"])
            await self._ok(["settings", "put", "global", "low_power", "1"])
            return "battery unplugged at 10% with low_power=1"
        if profile_id == "process_death":
            return "HOME + am kill + relaunch performed by the crawler after step 2"
        raise ProfileError(f"unknown profile {profile_id}")

    async def revert(self, profile_id: ProfileId) -> None:
        if profile_id == "budget_2gb":
            await self._ok(["emu", "network", "speed", "full"], shell=False)
            await self._ok(["emu", "network", "delay", "none"], shell=False)
        elif profile_id == "flaky_network":
            await self._stop_flaky()
            await self._set_radios(True)
        elif profile_id == "low_storage":
            await self._ok(["rm", "-f", FILLER])
        elif profile_id == "battery_saver":
            await self._ok(["settings", "put", "global", "low_power", "0"])
            await self._ok(["dumpsys", "battery", "reset"])

    async def _set_radios(self, enabled: bool) -> None:
        verb = "enable" if enabled else "disable"
        await self._ok(["svc", "data", verb])
        await self._ok(["svc", "wifi", verb])

    async def _flaky_loop(self) -> None:
        while True:
            await self._set_radios(False)
            await self._sleep(FLAKY_OFF_S)
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
