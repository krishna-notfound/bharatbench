"""Device health gate and self-repair for the test phone (redroid container or emulator).

Every command goes through the injectable adb runner so it is testable with a fake device.
Problem codes: adb (not in `device` state), boot (sys.boot_completed != 1), container (docker says not
running), disk (host / low), data_disk (/data on the phone low).
"""

import logging
import re
import shutil
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .adb import RC_MISSING, Adb
from .settings import Settings

log = logging.getLogger("harness.heal")

JOB_DIR = re.compile(r"[0-9a-f]{32}")
Emit = Callable[[str], None]


def _noop(_: str) -> None:
    return None


class DeviceDoctor:
    def __init__(
        self,
        settings: Settings,
        adb: Adb,
        sleep: Callable[[float], Any],
        clock: Callable[[], float] = time.monotonic,
        disk_probe: Callable[[Path], float] | None = None,
    ) -> None:
        self.settings = settings
        self.adb = adb
        self._sleep = sleep
        self._clock = clock
        self._disk_probe = disk_probe or self._real_disk_mb
        self.repairing = False
        self.last_repair: dict[str, object] | None = None
        self.installed: set[str] = set()  # packages this harness installed and has not yet removed

    # ---- probes ----
    @staticmethod
    def _real_disk_mb(path: Path) -> float:
        path.mkdir(parents=True, exist_ok=True)
        return shutil.disk_usage(path).free / (1024 * 1024)

    def host_free_mb(self) -> float:
        return round(self._disk_probe(self.settings.jobs_dir), 1)

    async def adb_alive(self) -> bool:
        rc, out, _ = await self.adb.run(["get-state"], timeout=10)
        return rc == 0 and out.strip() == "device"

    async def booted(self) -> bool:
        rc, out, _ = await self.adb.shell("getprop", "sys.boot_completed", timeout=10)
        return rc == 0 and out.strip() == "1"

    async def data_free_mb(self) -> float | None:
        rc, out, _ = await self.adb.shell("df", "-k", "/data", timeout=15)
        if rc != 0:
            return None
        for line in out.splitlines()[1:]:
            cols = line.split()
            if len(cols) >= 4 and cols[3].isdigit():
                return int(cols[3]) / 1024
        return None

    async def container_running(self) -> bool | None:
        """None when it cannot be determined (not a redroid device, or docker unavailable)."""
        if self.settings.device_kind != "redroid":
            return None
        rc, out, _ = await self.adb.raw(
            [self.settings.docker_path, "inspect", "-f", "{{.State.Running}}", self.settings.container_name], 20
        )
        if rc == RC_MISSING:
            return None
        return rc == 0 and out.strip() == "true"

    async def probe(self) -> list[str]:
        problems: list[str] = []
        if await self.container_running() is False:
            problems.append("container")
        if not await self.adb_alive():
            problems.append("adb")
        elif not await self.booted():
            problems.append("boot")
        if self.host_free_mb() < self.settings.min_free_mb:
            problems.append("disk")
        if "adb" not in problems and "boot" not in problems:
            free = await self.data_free_mb()
            if free is not None and free < self.settings.min_free_mb:
                problems.append("data_disk")
        return problems

    def snapshot(self, adb_ok: bool, booted: bool) -> dict[str, object]:
        """Fields for /health, from facts the caller already has plus disk and repair history."""
        free = self.host_free_mb()
        if self.repairing:
            status = "repairing"
        elif not adb_ok or not booted:
            status = "down"
        elif free < self.settings.min_free_mb:
            status = "degraded"
        else:
            status = "ok"
        return {"device_status": status, "last_repair": self.last_repair, "disk_free_mb": free}

    # ---- repair steps ----
    async def reconnect(self) -> bool:
        """`adb reconnect` + `adb connect`, then wait for the device to come back."""
        await self.adb.run(["reconnect"], timeout=15)
        await self.adb.global_run(["connect", self.adb.serial], timeout=15)
        return await self._wait(self.settings.reconnect_wait_s, self.adb_alive)

    async def _wait(self, seconds: float, check: Callable[[], Any]) -> bool:
        deadline = self._clock() + seconds
        while True:
            if await check():
                return True
            if self._clock() >= deadline:
                return False
            await self._sleep(2)

    async def restart_container(self) -> bool:
        rc, _, err = await self.adb.raw([self.settings.docker_path, "restart", self.settings.container_name], 90)
        if rc != 0:
            log.warning("docker restart failed: %s", err.strip()[:200])
            return False
        await self._sleep(3)

        async def ready() -> bool:
            if not await self.adb_alive():
                await self.adb.global_run(["connect", self.adb.serial], timeout=15)
                return False
            return await self.booted()

        return await self._wait(self.settings.boot_timeout_s, ready)

    def purge_jobs(self, protect: set[str]) -> int:
        """Delete old job dirs, keeping the newest `keep_jobs` and anything protected."""
        root = self.settings.jobs_dir
        if not root.is_dir():
            return 0
        dirs = [d for d in root.iterdir() if d.is_dir() and JOB_DIR.fullmatch(d.name) and d.name not in protect]
        dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
        removed = 0
        for d in dirs[self.settings.keep_jobs :]:
            shutil.rmtree(d, ignore_errors=True)
            removed += 1
        return removed

    async def uninstall_leftovers(self, keep: set[str]) -> list[str]:
        gone: list[str] = []
        for pkg in sorted(self.installed - keep):
            rc, out, _ = await self.adb.run(["uninstall", pkg], timeout=60)
            if rc == 0 or "Unknown package" in out:
                self.installed.discard(pkg)
                gone.append(pkg)
        return gone

    # ---- the gate ----
    async def ensure_ready(
        self, emit: Emit = _noop, protect_jobs: set[str] | None = None, keep_pkgs: set[str] | None = None
    ) -> bool:
        """Health gate before a job. Repairs what it can; returns False if the phone is unusable."""
        protect_jobs, keep_pkgs = protect_jobs or set(), keep_pkgs or set()
        problems = await self.probe()
        if not problems:
            return True
        emit(f"DEVICE: health check failed ({', '.join(problems)}); starting repair")
        self.repairing = True
        actions: list[str] = []
        try:
            if "disk" in problems or "data_disk" in problems:
                n = self.purge_jobs(protect_jobs)
                gone = await self.uninstall_leftovers(keep_pkgs)
                actions.append(f"freed space (removed {n} old job folders, {len(gone)} leftover apps)")
                emit(f"DEVICE: {actions[-1]}")
            if "container" not in problems and ("adb" in problems or "boot" in problems):
                emit("DEVICE: phone not responding; reconnecting adb")
                if await self.reconnect() and await self.booted():
                    actions.append("reconnected adb")
                    emit("DEVICE: adb reconnected")
            remaining = await self.probe()
            if {"adb", "boot", "container"} & set(remaining):
                name = self.settings.container_name
                emit(f"DEVICE: restarting the phone ({name}); this takes up to {self.settings.boot_timeout_s}s")
                restarted = await self.restart_container()
                actions.append("restarted phone container" if restarted else "phone container restart failed")
                emit(f"DEVICE: {'phone restarted and booted' if restarted else 'phone did not come back'}")
            remaining = await self.probe()
            fatal = {"adb", "boot", "container"} & set(remaining)
            ok = not fatal and self.host_free_mb() >= self.settings.hard_min_free_mb
            if ok and remaining:
                emit(f"DEVICE: continuing with warnings ({', '.join(remaining)})")
            self.last_repair = {
                "at": datetime.now(UTC).isoformat(),
                "problems": problems,
                "actions": actions,
                "ok": ok,
            }
            if not ok:
                emit(f"DEVICE: repair failed ({', '.join(remaining) or 'low disk'})")
            return ok
        finally:
            self.repairing = False
