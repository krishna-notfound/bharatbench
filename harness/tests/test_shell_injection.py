"""Manifest-controlled names must reach the device shell as one quoted word (docs/SECURITY_AUDIT.md)."""

import shlex

from harness.adb import Adb
from harness.manifest import Component
from harness.security import DeviceAudit


async def _nosleep(_s: float) -> None:
    return None


async def test_manifest_component_name_is_shell_quoted(tmp_path):
    calls: list[list[str]] = []

    async def runner(argv, timeout):
        calls.append(argv)
        return 0, b"", b""

    audit = DeviceAudit(Adb("adb", "s", runner), "com.ex.app", tmp_path, tmp_path / "a.apk", sleep=_nosleep)
    evil = ".Main;touch /sdcard/pwned"
    await audit._probe(Component("activity", evil, True, False, False, None))
    start = next(c for c in calls if "start" in c)
    # adb joins everything after `shell` into one device command line; the device shell splits it again
    device_words = shlex.split(" ".join(start[start.index("shell") + 1 :]))
    assert device_words[-1] == f"com.ex.app/{evil}"
    assert "touch" not in device_words
