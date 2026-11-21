"""Async adb wrapper. Argument lists only (never a host shell), every call has a timeout."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

log = logging.getLogger("harness.adb")

# (argv, timeout_s) -> (returncode, stdout bytes, stderr bytes)
Runner = Callable[[list[str], float], Awaitable[tuple[int, bytes, bytes]]]

RC_TIMEOUT = 124
RC_MISSING = 127


async def subprocess_runner(argv: list[str], timeout: float) -> tuple[int, bytes, bytes]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (FileNotFoundError, PermissionError) as exc:
        return RC_MISSING, b"", str(exc).encode()
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return RC_TIMEOUT, b"", b"timeout"
    return proc.returncode if proc.returncode is not None else -1, out, err


class Adb:
    def __init__(self, adb_path: str, serial: str, runner: Runner = subprocess_runner) -> None:
        self.adb_path = adb_path
        self.serial = serial
        self._runner = runner

    def _argv(self, args: list[str]) -> list[str]:
        return [self.adb_path, "-s", self.serial, *args]

    async def run(self, args: list[str], timeout: float = 30) -> tuple[int, str, str]:
        rc, out, err = await self._runner(self._argv(args), timeout)
        return rc, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")

    async def run_bytes(self, args: list[str], timeout: float = 30) -> tuple[int, bytes]:
        rc, out, _ = await self._runner(self._argv(args), timeout)
        return rc, out

    async def shell(self, *args: str, timeout: float = 30) -> tuple[int, str, str]:
        return await self.run(["shell", *args], timeout)

    async def global_run(self, args: list[str], timeout: float = 15) -> tuple[int, str, str]:
        """adb command without -s (e.g. `adb devices`)."""
        rc, out, err = await self._runner([self.adb_path, *args], timeout)
        return rc, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")
