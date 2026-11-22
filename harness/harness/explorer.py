"""LLM-driven exploration brain for the default journey (f25).

One action per step: the model sees the visible UI, a map of screens already visited and what was tried, and
answers tap / fill / scroll / back / wait / ask / done. Used by Crawler.run when an LLM key is set; without a key
the heuristic journey runs unchanged.

Invariants (tests: harness/tests/test_explorer.py):
- Same denylist veto as the crawler (`parsers.is_denied`); a vetoed tap is recorded and the model is told.
- After EVERY action the foreground package is checked (`dumpsys window | grep mCurrentFocus`). If the app was
  left: BACK once, else `am start` the last activity, else monkey relaunch. The offending action goes on a
  "useless" list the model sees.
- BACK is never sent on the app's root screen (that would close the app); it is converted to an unvisited control.
- Real credential values never reach the model or the stored steps (secrets.py tokens / mask).
- An LLM failure or a model that repeats an already-tried node degrades to the heuristic pick, never to a crash.
"""

import hashlib
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from .agent import MAX_NODES, render_nodes
from .crawler import Crawler
from .explorer_prompt import EXPLORER_SYSTEM_PROMPT
from .forms import adb_text
from .parsers import UiNode, clickable_nodes, is_denied, normalize_activity, parse_ui_nodes, ui_hash
from .secrets import Secrets
from .settings import Settings

log = logging.getLogger("harness.explorer")

CALL_TIMEOUT_S = 8.0
MAX_TOKENS = 220
TEMPERATURE = 0.2
WAIT_S = 1.5
MAX_SUMMARY_LINES = 12
ACTIONS = ("tap", "fill", "scroll", "back", "wait", "ask", "done")
# Permission / install prompts belong to the app's own flow; the model answers them.
ALLOWED_FOREIGN = ("permissioncontroller", "packageinstaller")
_FOCUS = re.compile(r"mCurrentFocus=Window\{\S+ \S+ ([\w.]+)/([\w.$]+)\}")
_NAV_HINT = re.compile(r"nav|tab|drawer|bottom|menu", re.IGNORECASE)


def llm_extra(model: str) -> dict[str, Any]:
    """Reasoning control for a 220-token reply (Sarvam docs: sarvam-105b thinks at `low` by default; null turns
    it off; deepseekv4* accept "none"). Thinking tokens would eat the whole budget, so switch it off."""
    if model == "sarvam-105b":
        return {"reasoning_effort": None}
    if model.startswith("deepseekv4"):
        return {"reasoning_effort": "none"}
    return {}


def parse_reply(text: str | None, n_nodes: int) -> dict[str, Any] | None:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        obj = json.loads(text[a : b + 1])
    except ValueError:
        return None
    if not isinstance(obj, dict) or obj.get("action") not in ACTIONS:
        return None
    act, node = obj["action"], obj.get("node")
    if act in ("tap", "fill") and (not isinstance(node, int) or isinstance(node, bool) or not 0 <= node < n_nodes):
        return None
    if act == "fill" and not isinstance(obj.get("text"), str):
        return None
    fields = obj.get("fields") if isinstance(obj.get("fields"), list) else []
    return {
        "action": act,
        "node": node,
        "text": obj.get("text"),
        "direction": "up" if obj.get("direction") == "up" else "down",
        "fields": [f for f in fields if isinstance(f, dict)][:5],
        "reason": str(obj.get("reason") or "")[:120],
    }


def screen_size(nodes: list[UiNode]) -> tuple[int, int]:
    w = max((n.bounds[2] for n in nodes), default=0)
    h = max((n.bounds[3] for n in nodes), default=0)
    return (w or 1080), (h or 1920)


def signature(activity: str | None, nodes: list[UiNode]) -> str:
    """Activity + structure (classes and resource ids), ignoring text that changes."""
    parts = sorted({(n.cls.rsplit(".", 1)[-1], n.rid.rsplit("/", 1)[-1]) for n in nodes})
    raw = (activity or "?") + "|" + ";".join(f"{c}:{r}" for c, r in parts)
    return hashlib.sha1(raw.encode()).hexdigest()[:8]


def node_key(n: UiNode) -> str:
    return f"{n.label}{n.bounds}"


def _flags(n: UiNode) -> str:
    return ",".join(f for f, on in (("c", n.clickable), ("e", n.editable), ("p", n.password), ("s", n.scrollable)) if on)


def render_ui(nodes: list[UiNode], sec: Secrets) -> tuple[str, list[UiNode]]:
    """agent.render_nodes selection, with the explorer flags c/e/p/s."""
    _, picked = render_nodes(nodes)
    lines = [
        f"{i}|{n.cls.rsplit('.', 1)[-1]}|{(n.text or n.desc)[:60]}|{n.hint[:30]}|{n.rid.rsplit('/', 1)[-1][:30]}|{_flags(n)}"
        for i, n in enumerate(picked[:MAX_NODES])
    ]
    return sec.tokenize("\n".join(lines)), picked


def section_nodes(nodes: list[UiNode]) -> list[UiNode]:
    """Bottom-nav / tab / drawer style controls: clickable, labelled, in a nav-like container or the bottom strip."""
    _, h = screen_size(nodes)
    out = []
    for n in clickable_nodes(nodes):
        name = f"{n.rid} {n.cls}"
        if (n.text or n.desc) and (_NAV_HINT.search(name) or n.bounds[1] > h * 0.88) and not n.editable:
            out.append(n)
    return out[:8]


@dataclass
class ScreenInfo:
    title: str
    tried: set[str] = field(default_factory=set)
    unexplored: int = 0
    visits: int = 0


@dataclass
class State:
    screens: dict[str, ScreenInfo] = field(default_factory=dict)
    sections: dict[str, bool] = field(default_factory=dict)  # label -> visited
    tried_log: dict[str, list[str]] = field(default_factory=dict)  # sig -> human-readable actions
    useless: list[str] = field(default_factory=list)
    root_sig: str | None = None
    last_comp: str | None = None
    notes: list[str] = field(default_factory=list)  # one-shot messages for the next turn
    dup_streak: int = 0
    asked: bool = False


def guess_title(activity: str | None, nodes: list[UiNode]) -> str:
    for n in nodes:
        if n.text and not n.clickable and not n.editable and n.bounds[1] < 400:
            return n.text[:30]
    return (activity or "screen").rsplit(".", 1)[-1][:30]


def summary(st: State, current: str) -> str:
    lines = []
    for sig, info in list(st.screens.items())[-MAX_SUMMARY_LINES + 2 :]:
        mark = " <- you are here" if sig == current else ""
        lines.append(f"{sig} '{info.title}': {len(info.tried)} tried, {info.unexplored} unexplored{mark}")
    if st.sections:
        lines.append("Main sections: " + ", ".join(f"{k}{' (visited)' if v else ' (NOT visited)'}" for k, v in list(st.sections.items())[:8]))
    return "\n".join(lines[:MAX_SUMMARY_LINES]) or "(none yet)"


def untried(nodes: list[UiNode], tried: set[str], useless: list[str]) -> UiNode | None:
    cands = [
        n for n in clickable_nodes(nodes)
        if not n.editable and not is_denied(n) and node_key(n) not in tried and n.label not in useless
    ]  # fmt: skip
    cands.sort(key=lambda n: 0 if n.text else 1)
    return cands[0] if cands else None


class Explorer:
    def __init__(
        self, crawler: Crawler, steps: int, settings: Settings, client: httpx.AsyncClient,
        caption: Callable[[str], None], secrets: Secrets | None,
    ) -> None:  # fmt: skip
        self.c = crawler
        self.steps = steps
        self.s = settings
        self.client = client
        self.caption = caption
        self.sec = secrets or crawler.secrets or Secrets(None)
        self.st = State()
        self.pkg = crawler.package
        self.llm_ms: list[int] = []
        self.last_bad: str | None = None

    # ---- device helpers ----
    async def focus(self) -> tuple[str | None, str | None]:
        """(package, component) of the focused window; (None, None) while unknown (a transition)."""
        rc, out, _ = await self.c.adb.shell("dumpsys window | grep mCurrentFocus", timeout=15)
        found = _FOCUS.findall(out) if rc == 0 else []
        # Several displays/windows can each report a focus (a stale window of another app on a secondary
        # display was seen on the test phone). The app owning ANY of them is in the foreground.
        for pkg, comp in found:
            if pkg == self.pkg:
                return pkg, comp
        return found[-1] if found else (None, None)

    def _in_app(self, pkg: str | None) -> bool:
        return pkg is None or pkg == self.pkg or any(a in pkg for a in ALLOWED_FOREIGN)

    async def guard(self, xml: str, what: str) -> str:
        """Stay-in-app check after an action. Returns the (possibly refreshed) UI dump."""
        pkg, comp = await self.focus()
        if not self._in_app(pkg):  # confirm with the resumed activity: mCurrentFocus can be stale during transitions
            resumed = await self.c.foreground()
            if resumed and resumed.startswith(f"{self.pkg}/"):
                return xml
            if resumed and "/" in resumed:
                pkg = resumed.split("/", 1)[0]
                if self._in_app(pkg):
                    return xml
        if self._in_app(pkg):
            if pkg == self.pkg and comp:
                self.st.last_comp = comp
            return xml
        c, t0 = self.c, self.c._clock()
        await c.adb.shell("input", "keyevent", "KEYCODE_BACK", timeout=15)
        await c._sleep(0.6)
        pkg2, _ = await self.focus()
        how = "back"
        if not self._in_app(pkg2):
            comp = self.st.last_comp or (c._launcher.split("/", 1)[1] if c._launcher else None)
            if comp:
                await c.adb.shell("am", "start", "-n", f"{self.pkg}/{comp}", timeout=30)
                how = "relaunch"
            pkg3, _ = await self.focus()
            if not self._in_app(pkg3):
                await c._monkey_launch()
                how = "monkey relaunch"
            await c._wait_foreground()
        c._step("back" if how == "back" else "launch", True, pkg, t0, f"Left the app (opened {pkg}) - returned ({how})")
        self.st.useless.append(what)
        self.st.notes.append(f"Your last action '{what}' opened another app ({pkg}); the lab brought you back. Do not repeat it.")
        c._fg_hash = None
        return await c._settle()

    async def act_tap(self, n: UiNode, reason: str) -> None:
        c, t0 = self.c, self.c._clock()
        cx, cy = n.center
        rc, _, _ = await c.adb.shell("input", "tap", str(cx), str(cy), timeout=15)
        c._step("tap", rc == 0, n.label, t0, reason, xy=(cx, cy))

    async def act_fill(self, n: UiNode, text: str, reason: str) -> None:
        c, sec, t0 = self.c, self.sec, self.c._clock()
        cx, cy = n.center
        rc, _, _ = await c.adb.shell("input", "tap", str(cx), str(cy), timeout=15)
        if rc == 0 and n.text and n.text != n.hint:
            await c.adb.shell("input", "keyevent", "KEYCODE_MOVE_END", *(["KEYCODE_DEL"] * len(n.text)), timeout=15)
        wanted = text[:80]
        used = sec.uses_secret(wanted)
        if rc == 0:
            rc, _, _ = await c.adb.shell("input", "text", adb_text(sec.expand(wanted)), timeout=15)
        if used or n.password:
            label = "password" if n.password or "password" in used else used[0]
            note = f"Filling {label} (hidden): {reason}"
        else:
            note = f"typed {sec.mask(wanted[:30])}: {reason}"
        c._step("fill", rc == 0, n.label, t0, note, xy=(cx, cy))

    async def act_scroll(self, nodes: list[UiNode], direction: str, reason: str) -> None:
        c, t0 = self.c, self.c._clock()
        w, h = screen_size(nodes)
        y1, y2 = (int(h * 0.7), int(h * 0.3)) if direction == "down" else (int(h * 0.3), int(h * 0.7))
        rc, _, _ = await c.adb.shell("input", "swipe", str(w // 2), str(y1), str(w // 2), str(y2), "300", timeout=15)
        c._step("wait", rc == 0, f"scroll {direction}", t0, f"scrolled {direction}: {reason}")

    async def act_back(self, reason: str) -> None:
        c, t0 = self.c, self.c._clock()
        rc, _, _ = await c.adb.shell("input", "keyevent", "KEYCODE_BACK", timeout=15)
        c._step("back", rc == 0, "KEYCODE_BACK", t0, reason)

    # ---- LLM ----
    async def ask_llm(self, user: str) -> str | None:
        s = self.s
        base = s.llm_base_url.rstrip("/")
        system = EXPLORER_SYSTEM_PROMPT + ("\n" + self.sec.prompt_addendum() if self.sec.available else "")
        body: dict[str, Any] = {
            "model": s.llm_model, "max_tokens": MAX_TOKENS, "temperature": TEMPERATURE,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            **llm_extra(s.llm_model),
        }  # fmt: skip
        key = s.llm_api_key or ""
        headers = {"api-subscription-key": key} if "sarvam.ai" in base else {"Authorization": f"Bearer {key}"}
        try:
            resp = await self.client.post(f"{base}/chat/completions", headers=headers, json=body, timeout=CALL_TIMEOUT_S)
            if resp.status_code != 200:
                return None
            return resp.json()["choices"][0]["message"].get("content") or ""
        except (httpx.HTTPError, KeyError, IndexError, ValueError, AttributeError):
            return None

    def user_message(self, k: int, sig: str, listing: str, tried_here: list[str]) -> str:
        st = self.st
        notes = list(st.notes)
        st.notes.clear()
        parts = [
            f"App package: {self.pkg}",
            f"Step {k}/{self.steps}. Screen signature: {sig}",
            f"Visible UI:\n{listing or '(nothing visible)'}",
            f"Visited screens:\n{summary(st, sig)}",
            "Tried here: " + ("; ".join(tried_here[-10:]) or "nothing yet"),
        ]
        if st.useless:
            parts.append("Useless actions (they left the app): " + "; ".join(st.useless[-6:]))
        parts.extend(notes)
        parts.append(
            "Test account: " + ("available, use <LOGIN>/<PASSWORD>/<OTP>" if self.sec.available else "not available")
            + ". Human can answer 'ask': " + ("yes" if self._can_ask() else "no")
        )
        return "\n".join(parts)

    def _can_ask(self) -> bool:
        return getattr(self.c, "broker", None) is not None and hasattr(self.c, "request_input") and not self.st.asked

    # ---- loop ----
    async def run(self) -> None:
        c, st = self.c, self.st
        xml = await c.dump_ui()
        for k in range(1, self.steps + 1):
            if c.cancelled():
                break
            t0 = c._clock()
            all_nodes = parse_ui_nodes(xml)
            pkg, comp = await self.focus()
            activity = normalize_activity(f"{pkg}/{comp}", self.pkg) if pkg and comp else c._fg
            sig = signature(activity, all_nodes)
            if st.root_sig is None:
                st.root_sig = sig
            info = st.screens.setdefault(sig, ScreenInfo(guess_title(activity, all_nodes)))
            info.visits += 1
            tried_here = st.tried_log.setdefault(sig, [])
            info.unexplored = sum(
                1 for n in clickable_nodes(all_nodes)
                if not n.editable and not is_denied(n) and node_key(n) not in info.tried
            )  # fmt: skip
            for n in section_nodes(all_nodes):
                st.sections.setdefault(n.label[:20], False)
            listing, nodes = render_ui(all_nodes, self.sec)
            act: dict[str, Any] | None = None
            if st.dup_streak < 2:
                tl = c._clock()
                content = await self.ask_llm(self.user_message(k, sig, listing, tried_here))
                self.llm_ms.append(int((c._clock() - tl) * 1000))
                act = parse_reply(content, len(nodes)) if content is not None else None
                self.last_bad = None if act else " ".join((content or "no response")[:80].split())
            what = await self.execute(act, k, sig, info, all_nodes, nodes)
            if what == "done":
                break
            xml = await c._settle(ui_hash(xml))
            xml = await self.guard(xml, what)
            await c._capture(xml)
            xml = await c._watch_stuck(xml)
            if c.profile_id == "process_death" and k == 2 and c.j.state_lost_after_restore is None:
                xml = await c._kill_and_restore(xml)
            log.debug("explorer step %d took %.1fs", k, c._clock() - t0)

    def _fallback(self, all_nodes: list[UiNode], info: ScreenInfo, sig: str) -> tuple[str, UiNode | None]:
        n = untried(all_nodes, info.tried, self.st.useless)
        if n:
            return "tap", n
        if any(x.scrollable for x in all_nodes):
            return "scroll", None
        return ("wait", None) if sig == self.st.root_sig else ("back", None)

    async def execute(
        self, act: dict[str, Any] | None, k: int, sig: str, info: ScreenInfo,
        all_nodes: list[UiNode], nodes: list[UiNode],
    ) -> str:  # fmt: skip
        """Run one decided action; returns a short label of what was done ("done" ends the journey)."""
        c, st, sec = self.c, self.st, self.sec
        log_here = st.tried_log[sig]
        kind = act["action"] if act else "fallback"
        reason = sec.mask(act["reason"]) if act else f"no usable model answer ({self.last_bad}); picking an untried control"
        node = nodes[act["node"]] if act and act["node"] is not None else None

        if kind == "tap" and node is not None:
            if is_denied(node) or node.label in st.useless:
                c._step("tap", False, node.label, c._clock(), "skipped: unsafe or useless action")
                st.notes.append(f"Your tap on '{sec.tokenize(node.label)}' was vetoed (unsafe or useless). Pick another control.")
                info.tried.add(node_key(node))
                return f"vetoed {node.label}"
            if node_key(node) in info.tried:
                st.dup_streak += 1
                st.notes.append(f"'{sec.tokenize(node.label)}' was already tried here. Pick an untried control.")
                if st.dup_streak < 2:
                    return f"skip repeat {node.label}"
                kind = "fallback"
                reason = "model repeated a tried control; picking an untried one"
            else:
                st.dup_streak = 0
        elif kind not in ("fallback", "fill"):
            st.dup_streak = 0

        if kind == "fill" and node is not None:
            wanted = sec.expand(str(act["text"]))[:80] if act else ""
            if node.text and node.text == wanted:  # already holds this value: retyping wastes the step
                st.dup_streak += 1
                st.notes.append(f"Field '{sec.tokenize(node.label)[:30]}' is already filled. Do NOT refill it: tap the next/submit control.")
                if st.dup_streak < 2:
                    return f"skip refill {node.label}"
                kind = "fallback"
                reason = "field already filled; picking an untried control"
            else:
                st.dup_streak = 0
        if kind == "done":
            self.caption(f"Agent: finished - {reason}")
            c._step("wait", True, "done", c._clock(), reason)
            return "done"
        if kind == "ask":
            return await self.do_ask(act or {})
        if kind == "back" and sig == st.root_sig:
            st.notes.append("You are on the app's root screen: BACK would close the app, so it was not sent. Pick an unvisited control.")
            kind = "fallback"
            reason = "root screen: picking an unvisited control instead of back"
        if kind == "fallback":
            kind, node = self._fallback(all_nodes, info, sig)
            st.dup_streak = 0 if node else st.dup_streak

        self.caption(f"Agent: {reason}")
        if kind == "tap" and node is not None:
            info.tried.add(node_key(node))
            log_here.append(f"tap '{sec.tokenize(node.label)[:30]}'")
            if node.label[:20] in st.sections:
                st.sections[node.label[:20]] = True
            await self.act_tap(node, reason)
            return node.label
        if kind == "fill" and node is not None:
            info.tried.add(node_key(node))
            log_here.append(f"fill '{sec.tokenize(node.label)[:30]}'")
            await self.act_fill(node, str(act["text"]) if act else "", reason)
            if await c._keyboard_shown():
                await c.adb.shell("input", "keyevent", "KEYCODE_BACK", timeout=15)
                await c._sleep(0.3)
            return f"fill {node.label}"
        if kind == "scroll":
            direction = act["direction"] if act else "down"
            log_here.append(f"scroll {direction}")
            await self.act_scroll(all_nodes, direction, reason)
            return "scroll"
        if kind == "back":
            log_here.append("back")
            await self.act_back(reason)
            return "back"
        # wait (also an empty fallback on the root screen)
        t0 = c._clock()
        await c._sleep(WAIT_S)
        c._step("wait", True, "wait", t0, reason)
        return "wait"

    async def do_ask(self, act: dict[str, Any]) -> str:
        c, st = self.c, self.st
        fields, reason = act.get("fields", []), act.get("reason", "")
        t0 = c._clock()
        req = getattr(c, "request_input", None)
        if req is None or st.asked:
            st.notes.append("No human can answer: look for Skip / Guest / sign-up instead.")
            c._step("wait", False, "ask", t0, "no human available; skipping")
            return "ask-skip"
        st.asked = True
        self.caption(f"Agent: asking for {', '.join(str(f.get('label', f.get('key', '?'))) for f in fields) or 'input'}")
        try:
            got = await req(fields, reason)
        except Exception as exc:  # noqa: BLE001 - a failed ask is a skip
            log.warning("request_input failed: %s", type(exc).__name__)
            got = None
        if got:
            self.sec = c.secrets or self.sec  # the other agent's code may have refreshed the account values
            st.notes.append("The human answered: use <LOGIN>/<PASSWORD>/<OTP> placeholders now.")
            c._step("wait", True, "ask", t0, "human provided the requested details")
        else:
            st.notes.append("The human skipped: look for Skip / Guest / sign-up instead.")
            c._step("wait", False, "ask", t0, "human skipped")
        return "ask"


async def explore(
    crawler: Crawler, steps: int, settings: Settings, client: httpx.AsyncClient,
    caption: Callable[[str], None] = lambda _m: None, secrets: Secrets | None = None,
) -> None:  # fmt: skip
    await Explorer(crawler, steps, settings, client, caption, secrets).run()
