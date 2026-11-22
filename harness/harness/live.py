"""Live view: ~1 fps screencap loop per running job plus the last step's tap point (latest frame only, in memory)."""

import asyncio
import contextlib
import struct
import time
from dataclasses import dataclass, field

from .adb import Adb
from .models import HarnessStep

PNG_MAGIC = b"\x89PNG"
FRAME_INTERVAL_S = 1.0


def png_size(png: bytes) -> tuple[int, int] | None:
    if len(png) < 24 or not png.startswith(PNG_MAGIC):
        return None
    w, h = struct.unpack(">II", png[16:24])
    return int(w), int(h)


@dataclass
class LiveState:
    seq: int = 0
    ts: float = 0.0
    frame: bytes | None = None
    screen: tuple[int, int] | None = None
    profile_id: str | None = None
    step_index: int | None = None
    action: str | None = None
    target: str | None = None
    tap: tuple[int, int] | None = None
    step_ts: float = 0.0
    running: bool = True
    _task: asyncio.Task[None] | None = field(default=None, repr=False)

    def set_profile(self, profile_id: str) -> None:
        self.profile_id = profile_id
        self.step_index = self.action = self.target = self.tap = None
        self.seq += 1

    def note_step(self, step: HarnessStep) -> None:
        self.step_index, self.action, self.target = step.index, step.action, step.target
        self.tap = (step.x, step.y) if step.x is not None and step.y is not None else None
        self.step_ts = time.time()
        self.seq += 1

    def public(self) -> dict[str, object]:
        return {
            "seq": self.seq,
            "ts": self.ts,
            "profile_id": self.profile_id,
            "step_index": self.step_index,
            "action": self.action,
            "target": self.target,
            "tap": {"x": self.tap[0], "y": self.tap[1]} if self.tap else None,
            "screen": {"w": self.screen[0], "h": self.screen[1]} if self.screen else None,
            "running": self.running,
            "has_frame": self.frame is not None,
        }

    def start(self, adb: Adb, interval: float = FRAME_INTERVAL_S) -> None:
        self._task = asyncio.create_task(self._loop(adb, interval))

    async def stop(self) -> None:
        self.running = False
        self.seq += 1
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None

    async def _loop(self, adb: Adb, interval: float) -> None:
        while True:
            t0 = time.monotonic()
            with contextlib.suppress(Exception):  # never let the viewer break a job
                rc, png = await adb.run_bytes(["exec-out", "screencap", "-p"], timeout=8)
                size = png_size(png) if rc == 0 else None
                if size:
                    self.frame, self.screen, self.ts = png, size, time.time()
                    self.seq += 1
            await asyncio.sleep(max(0.05, interval - (time.monotonic() - t0)))
