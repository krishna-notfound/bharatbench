import os

os.environ.setdefault("HARNESS_TOKEN", "test-token")
os.environ.setdefault("SECURITY_ENABLED", "false")  # real tcpdump/adb root are exercised in test_security with fakes

from pathlib import Path

import pytest

from harness.adb import Adb

FIX = Path(__file__).parent / "fixtures"


class FakeRunner:
    """Records every argv; responses are matched by substring of the joined argv (first match wins)."""

    def __init__(self, responses: dict[str, tuple[int, bytes | str]] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.responses = responses or {}

    async def __call__(self, argv: list[str], timeout: float) -> tuple[int, bytes, bytes]:
        assert timeout > 0
        self.calls.append(argv)
        joined = " ".join(argv)
        for key, (rc, out) in self.responses.items():
            if key in joined:
                return rc, out.encode() if isinstance(out, str) else out, b""
        return 0, b"", b""

    def shell_args(self) -> list[list[str]]:
        return [c[4:] for c in self.calls if c[3:4] == ["shell"]]


@pytest.fixture
def fixtures() -> Path:
    return FIX


@pytest.fixture
def runner() -> FakeRunner:
    return FakeRunner()


@pytest.fixture
def adb(runner: FakeRunner) -> Adb:
    return Adb("adb", "emulator-5554", runner)
