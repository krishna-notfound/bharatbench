"""Launch the app and walk a bounded, safe journey, collecting screenshots, UI dumps and steps."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from .adb import Adb
from .forms import SECRET_KINDS, FormField, adb_text, fillable_fields, pick_submit
from .models import HarnessScreen, HarnessStep, ProfileId
from .parsers import (
    UiNode,
    clickable_nodes,
    has_progress,
    is_denied,
    normalize_activity,
    parse_launch_time,
    parse_resolve_activity,
    parse_resumed_activity,
    parse_ui_nodes,
    ui_hash,
    visible_texts,
)
from .secrets import Secrets

UI_REMOTE = "/sdcard/ui.xml"
DUMP_CMD = f"uiautomator dump {UI_REMOTE} >/dev/null && cat {UI_REMOTE}"
STUCK_AFTER_S = 15
STUCK_POLL_S = 3
POLL_S = 0.3  # change-detection poll interval
SETTLE_CAP_S = 2.5  # never wait longer than this for a screen to stop changing
LAUNCH_WAIT_S = 4.0  # max wait for the app to own the foreground
PNG_MAGIC = b"\x89PNG"

Sleep = Callable[[float], Awaitable[None]]


@dataclass
class Journey:
    launched: bool = False
    launch_ms: int | None = None
    screens: list[HarnessScreen] = field(default_factory=list)
    steps: list[HarnessStep] = field(default_factory=list)
    stuck_loading: bool = False
    state_lost_after_restore: bool | None = None


class Crawler:
    def __init__(
        self,
        adb: Adb,
        package: str,
        activity: str | None,
        job_dir: Path,
        profile_id: ProfileId,
        *,
        cancelled: Callable[[], bool] = lambda: False,
        sleep: Sleep = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        on_step: Callable[[HarnessStep], None] | None = None,
        secrets: Secrets | None = None,
    ) -> None:
        self.adb = adb
        self.package = package
        self.activity = activity
        self.job_dir = job_dir
        self.profile_id = profile_id
        self.cancelled = cancelled
        self._sleep = sleep
        self._clock = clock
        self._on_step = on_step
        self.secrets = secrets
        self.j = Journey()
        self._launcher: str | None = None
        self._cap_hash: str | None = None  # UI hash of the last captured screen
        self._fg: str | None = None
        self._fg_hash: str | None = None  # UI hash the cached foreground belongs to
        self._filled: set[str] = set()  # form fields already filled (once each)

    # ---- primitives ----
    def _step(
        self, action: str, ok: bool, target: str | None = None, t0: float | None = None, note: str | None = None,
        xy: tuple[int, int] | None = None,
    ) -> None:  # fmt: skip
        ms = int((self._clock() - t0) * 1000) if t0 is not None else None
        if self.secrets is not None:  # never store a real test-account value in steps
            target = self.secrets.mask(target) if target else target
            note = self.secrets.mask(note) if note else note
        step = HarnessStep(
            index=len(self.j.steps), action=action, target=target, ok=ok, duration_ms=ms, note=note,  # type: ignore[arg-type]
            x=xy[0] if xy else None, y=xy[1] if xy else None,
        )  # fmt: skip
        self.j.steps.append(step)
        if self._on_step is not None:
            self._on_step(step)

    async def dump_ui(self) -> str:
        """One adb round trip: dump the UI tree and stream it back (no separate `cat` call)."""
        rc, out = await self.adb.run_bytes(["exec-out", "sh", "-c", DUMP_CMD], timeout=30)
        return out.decode("utf-8", "replace") if rc == 0 else ""

    async def foreground(self) -> str | None:
        rc, out, _ = await self.adb.shell("dumpsys activity activities | grep ResumedActivity", timeout=20)
        return normalize_activity(parse_resumed_activity(out), self.package) if rc == 0 else None

    async def _fg_for(self, xml: str) -> str | None:
        """Foreground component, looked up only when the UI differs from the last lookup."""
        h = ui_hash(xml) if xml else None
        if h is not None and h == self._fg_hash:
            return self._fg
        self._fg = await self.foreground()
        self._fg_hash = h
        return self._fg

    async def _screencap(self) -> bytes | None:
        rc, png = await self.adb.run_bytes(["exec-out", "screencap", "-p"], timeout=30)
        return png if rc == 0 and png.startswith(PNG_MAGIC) else None

    async def _capture(self, xml: str, note: str | None = None) -> None:
        """Save evidence for the current screen; an unchanged screen reuses the last screenshot and foreground."""
        index = len(self.j.screens)
        (self.job_dir / "screens").mkdir(parents=True, exist_ok=True)
        (self.job_dir / "ui").mkdir(parents=True, exist_ok=True)
        h = ui_hash(xml) if xml else None
        prev = self.j.screens[-1] if self.j.screens else None
        if h is not None and h == self._cap_hash and prev is not None and prev.screenshot:
            shot_rel, activity = prev.screenshot, prev.activity
        else:
            png, activity = await asyncio.gather(self._screencap(), self._fg_for(xml))
            shot_rel = None
            if png is not None:
                shot_rel = f"screens/{self.profile_id}_{index}.png"
                (self.job_dir / shot_rel).write_bytes(png)
        self._cap_hash = h
        ui_rel = None
        if xml:
            ui_rel = f"ui/{self.profile_id}_{index}.xml"
            stored = self.secrets.mask(xml) if self.secrets is not None else xml
            (self.job_dir / ui_rel).write_text(stored, encoding="utf-8")
        self.j.screens.append(
            HarnessScreen(index=index, screenshot=shot_rel, ui_dump=ui_rel, activity=activity, note=note)
        )
        if self.j.steps and self.j.steps[-1].screen is None:
            self.j.steps[-1].screen = index

    async def _settle(self, prev_hash: str | None = None) -> str:
        """Change detection instead of fixed sleeps.

        Poll the UI every POLL_S (each dump itself takes real time) until a read matches the one before it
        (the screen stopped changing). An unchanged screen returns after one read. Capped at SETTLE_CAP_S.
        """
        t0 = self._clock()
        last = prev_hash
        while True:
            await self._sleep(POLL_S)
            xml = await self.dump_ui()
            h = ui_hash(xml)
            if h == last or self._clock() - t0 >= SETTLE_CAP_S:
                return xml
            last = h

    async def _watch_stuck(self, xml: str) -> str:
        """Same screen with a ProgressBar for >= 15 s of consecutive checks flags stuck_loading."""
        if not xml or not has_progress(parse_ui_nodes(xml)):
            return xml
        since = self._clock()
        while True:
            await self._sleep(STUCK_POLL_S)
            new = await self.dump_ui()
            if ui_hash(new) != ui_hash(xml):
                return new
            if self._clock() - since >= STUCK_AFTER_S:
                self.j.stuck_loading = True
                return xml

    # ---- launch ----
    async def _wait_foreground(self) -> str | None:
        """Poll until the app owns the foreground, at most LAUNCH_WAIT_S."""
        t0 = self._clock()
        fg = await self.foreground()
        while not (fg and fg.startswith(f"{self.package}/")) and self._clock() - t0 < LAUNCH_WAIT_S:
            await self._sleep(POLL_S)
            fg = await self.foreground()
        return fg

    async def launch(self) -> bool:
        t0 = self._clock()
        activity = self.activity
        if not activity:
            _, out, _ = await self.adb.shell("cmd", "package", "resolve-activity", "--brief", self.package, timeout=20)
            resolved = parse_resolve_activity(out)
            activity = resolved.split("/", 1)[1] if resolved else None
        launch_ms = None
        if activity:
            self._launcher = normalize_activity(f"{self.package}/{activity}", self.package)
            rc, out, _ = await self.adb.shell("am", "start", "-W", "-n", f"{self.package}/{activity}", timeout=60)
            launch_ms = parse_launch_time(out) if rc == 0 else None
        else:
            await self._monkey_launch()
        fg = await self._wait_foreground()
        launched = bool(fg) and fg.startswith(f"{self.package}/") and (launch_ms is not None or not activity)
        self.j.launched, self.j.launch_ms = launched, launch_ms
        self._step("launch", launched, f"{self.package}/{activity}" if activity else self.package, t0,
                   None if launched else "no app window within 4 s or launch error")  # fmt: skip
        return launched

    async def _monkey_launch(self) -> None:
        await self.adb.shell("monkey", "-p", self.package, "-c", "android.intent.category.LAUNCHER", "1", timeout=30)

    # ---- forms ----
    async def _keyboard_shown(self) -> bool:
        rc, out, _ = await self.adb.shell("dumpsys input_method | grep mInputShown", timeout=15)
        return rc == 0 and "mInputShown=true" in out

    async def _fill_field(self, f: FormField) -> None:
        t0 = self._clock()
        cx, cy = f.node.center
        rc, _, _ = await self.adb.shell("input", "tap", str(cx), str(cy), timeout=15)
        if rc == 0 and f.node.text and f.node.text != f.node.hint:  # stale text: move to end, then delete it
            await self.adb.shell("input", "keyevent", "KEYCODE_MOVE_END", *(["KEYCODE_DEL"] * len(f.node.text)), timeout=15)
        value, real = f.real_value(self.secrets)
        if rc == 0:
            rc, _, _ = await self.adb.shell("input", "text", adb_text(value), timeout=15)
        self._filled.add(f.key)
        if real:
            note = f"Filling {'OTP' if f.kind == 'otp' else 'password' if f.kind == 'password' else 'login'} (hidden)"
        else:
            note = f"typed a test {f.kind}" + (" (value masked)" if f.kind in SECRET_KINDS else "")
        self._step("fill", rc == 0, f.kind, t0, note, xy=(cx, cy))

    async def _fill_form(self, xml: str) -> str | None:
        """Fill every visible empty field once, hide the keyboard, return the fresh dump (None = no form)."""
        fields = fillable_fields(parse_ui_nodes(xml), self._filled)
        if not fields:
            return None
        for f in fields:
            await self._fill_field(f)
        if await self._keyboard_shown():
            await self.adb.shell("input", "keyevent", "KEYCODE_BACK", timeout=15)
            await self._sleep(POLL_S)  # let the layout resize back before re-reading button positions
        return await self.dump_ui()

    # ---- journey ----
    def _pick(self, nodes: list[UiNode], tapped: set[str]) -> UiNode | None:
        cands = [
            n for n in clickable_nodes(nodes)
            if not n.editable and not is_denied(n) and f"{n.label}{n.bounds}" not in tapped
        ]  # fmt: skip
        cands.sort(key=lambda n: 0 if n.text else 1)  # stable: prefer text, then document order
        return cands[0] if cands else None

    async def run(self, steps: int) -> Journey:
        if not await self.launch():
            return self.j
        xml = await self._settle()
        await self._capture(xml, "after launch")
        xml = await self._watch_stuck(xml)
        tapped: set[str] = set()
        for i in range(1, steps + 1):
            if self.cancelled():
                break
            t0 = self._clock()
            form_xml = await self._fill_form(xml) if xml else None
            if form_xml is not None:
                xml = form_xml or xml
                t0 = self._clock()
                node = pick_submit(parse_ui_nodes(xml), tapped)
            else:
                node = None
            node = node or self._pick(parse_ui_nodes(xml), tapped)
            if node:
                tapped.add(f"{node.label}{node.bounds}")
                cx, cy = node.center
                rc, _, _ = await self.adb.shell("input", "tap", str(cx), str(cy), timeout=15)
                self._step("tap", rc == 0, node.label, t0, xy=(cx, cy))
            else:
                rc, _, _ = await self.adb.shell("input", "keyevent", "KEYCODE_BACK", timeout=15)
                self._step("back", rc == 0, "KEYCODE_BACK", t0, "nothing clickable")
            xml = await self._settle(ui_hash(xml))
            xml = await self._recover_foreground(xml)
            await self._capture(xml)
            xml = await self._watch_stuck(xml)
            if self.profile_id == "process_death" and i == 2 and self.j.state_lost_after_restore is None:
                xml = await self._kill_and_restore(xml)
        return self.j

    async def _recover_foreground(self, xml: str) -> str:
        fg = await self._fg_for(xml)
        if fg and fg.startswith(f"{self.package}/"):
            return xml
        t0 = self._clock()
        await self.adb.shell("input", "keyevent", "KEYCODE_BACK", timeout=15)
        fg = await self._wait_foreground()
        if fg and fg.startswith(f"{self.package}/"):
            self._step("back", True, "KEYCODE_BACK", t0, "app left foreground; pressed back")
        else:
            await self._monkey_launch()
            await self._wait_foreground()
            self._step("launch", True, self.package, t0, "app left foreground; relaunched")
        xml = await self.dump_ui()
        self._fg_hash = None  # the foreground changed under us; force a fresh lookup
        return xml

    async def _kill_and_restore(self, before_xml: str) -> str:
        before = visible_texts(parse_ui_nodes(before_xml))
        t0 = self._clock()
        await self.adb.shell("input", "keyevent", "KEYCODE_HOME", timeout=15)
        self._step("background", True, "KEYCODE_HOME", t0)
        t0 = self._clock()
        rc, _, _ = await self.adb.shell("am", "kill", self.package, timeout=15)
        self._step("kill", rc == 0, self.package, t0)
        t0 = self._clock()
        await self._monkey_launch()
        await self._wait_foreground()
        after_xml = await self._settle()
        self._fg_hash = None
        after_activity = await self._fg_for(after_xml)
        self._step("restore", bool(after_activity), self.package, t0)
        after = visible_texts(parse_ui_nodes(after_xml))
        if before:
            overlap = len(before & after) / len(before)
            at_launcher = after_activity is not None and after_activity == self._launcher
            self.j.state_lost_after_restore = overlap < 0.5 and at_launcher
        self._cap_hash = None
        await self._capture(after_xml, "after process death restore")
        return after_xml
