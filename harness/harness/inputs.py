"""Human-in-the-loop input broker (f24): one per job, values live only in memory.

The agent/crawler calls `ask()` when a screen needs something only the user has (login, password, OTP, PIN...).
The request (labels only, never values) is shown on the live phone; `submit()` hands the answer back to the waiting
coroutine. Time spent waiting is tracked (`paused_total`) so per-profile/job timeouts and stall watchdogs do not
count it. Values are never logged, put in events, steps or job files.
"""

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

T = TypeVar("T")

ASK_TIMEOUT_S = 180.0
MAX_FIELDS = 6
MAX_VALUE_LEN = 200
SECRET_KINDS = frozenset({"password", "pin", "otp"})
KINDS = frozenset({"username", "email", "phone", "password", "otp", "pin", "text"})


@dataclass
class AskField:
    key: str
    label: str
    kind: str = "text"

    @property
    def secret(self) -> bool:
        return self.kind in SECRET_KINDS


@dataclass
class InputBroker:
    on_change: Callable[[], None] = lambda: None
    on_event: Callable[[str], None] = lambda _m: None
    clock: Callable[[], float] = time.monotonic
    timeout_s: float = ASK_TIMEOUT_S
    enabled: bool = True
    request: dict[str, Any] | None = None
    paused_s: float = 0.0
    timeouts: int = 0
    declined: set[str] = field(default_factory=set)  # kinds the user skipped; do not ask again
    _since: float | None = field(default=None, repr=False)
    _event: asyncio.Event | None = field(default=None, repr=False)
    _answer: dict[str, str] | None = field(default=None, repr=False)
    _skipped: bool = field(default=False, repr=False)
    _id: str | None = field(default=None, repr=False)
    _keys: set[str] = field(default_factory=set, repr=False)

    @property
    def waiting(self) -> bool:
        return self.request is not None

    def paused_total(self) -> float:
        extra = self.clock() - self._since if self._since is not None else 0.0
        return self.paused_s + extra

    def public(self) -> dict[str, Any] | None:
        return dict(self.request) if self.request else None

    async def ask(self, fields: list[AskField], reason: str) -> dict[str, str] | None:
        """Block until the user answers. Returns {key: value}, or None when skipped/timed out/disabled."""
        if not self.enabled or not fields or self.request is not None:
            return None
        fields = fields[:MAX_FIELDS]
        self._id = uuid.uuid4().hex[:16]
        self._event, self._answer, self._skipped = asyncio.Event(), None, False
        self._keys = {f.key for f in fields}
        self.request = {
            "request_id": self._id,
            "fields": [{"key": f.key, "label": f.label[:60], "kind": f.kind, "secret": f.secret} for f in fields],
            "reason": reason[:200],
            "screenshot": "live.png",
            "timeout_s": int(self.timeout_s),
            "started_at": time.time(),
        }
        self._since = self.clock()
        self.on_event("Waiting for you: " + ", ".join(f.label[:30] for f in fields))
        self.on_change()
        try:
            try:
                await asyncio.wait_for(self._event.wait(), self.timeout_s)
            except TimeoutError:
                self.timeouts += 1
                self.on_event("User input skipped (timed out)")
                if self.timeouts >= 2:
                    self.enabled = False  # nobody is watching; stop pausing the run
                return None
            return None if self._skipped else self._answer
        finally:
            self.paused_s += self.clock() - (self._since or self.clock())
            self._since = None
            self.request = None
            self._event = None
            self._id = None
            self.on_change()

    def submit(self, request_id: str, values: dict[str, str] | None, skip: bool = False) -> bool:
        """False when there is no matching open request (stale id)."""
        if self.request is None or self._event is None or request_id != self._id:
            return False
        clean = {k: str(v)[:MAX_VALUE_LEN] for k, v in (values or {}).items() if k in self._keys and str(v).strip()}
        if skip or not clean:
            self._skipped = True
            self.on_event("User input skipped")
        else:
            self._answer = clean
        self._event.set()
        return True


async def run_unpaused[T](aw: Awaitable[T], timeout: float, broker: InputBroker | None, poll: float = 0.25) -> T:
    """`asyncio.wait_for` whose clock stops while the user is being asked something (same task, so no semantics change)."""
    loop = asyncio.get_running_loop()
    start = loop.time()
    async with asyncio.timeout(start + timeout) as cm:

        async def adjust() -> None:
            while True:
                await asyncio.sleep(poll)
                cm.reschedule(start + timeout + (broker.paused_total() if broker else 0.0))

        ticker = asyncio.create_task(adjust()) if broker is not None else None
        try:
            return await aw
        finally:
            if ticker is not None:
                ticker.cancel()
