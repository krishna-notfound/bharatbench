"""Goal-directed agent test driver (f23).

For one AgentTest: send the LLM the goal and a compact list of visible UI nodes, execute the single action
it answers with (tap / fill / back / done / fail) through the Crawler primitives, repeat up to MAX_STEPS.
The API key is never logged.
"""

import json
import logging
import re
from collections.abc import Callable
from typing import Any

import httpx

from .crawler import Crawler
from .forms import adb_text
from .models import AgentTest, HarnessAgentTestResult
from .parsers import UiNode, is_denied, parse_ui_nodes, ui_hash
from .settings import Settings

log = logging.getLogger("harness.agent")

MAX_STEPS = 8
MAX_NODES = 40
CALL_TIMEOUT_S = 25.0
ACTIONS = ("tap", "fill", "back", "done", "fail")

SYSTEM_PROMPT = (
    "You drive an Android app on a phone to check one test. You see the visible UI nodes as lines "
    "'index|class|text|hint|resource-id|flags'. Reply with strict JSON only, one action per reply: "
    '{"action":"tap"|"fill"|"back"|"done"|"fail","node":<index, for tap/fill>,"text":"<text to type, for fill>",'
    '"reason":"short plain sentence"}. Use "done" when the success check is visibly met (reason says what you saw), '
    '"fail" when the app clearly does not behave as the success check requires or is stuck/broken. '
    "Never use real personal data; never pay, buy, delete or log out."
)


def llm_ready(s: Settings) -> bool:
    return bool(s.llm_api_key)


def render_nodes(nodes: list[UiNode]) -> tuple[str, list[UiNode]]:
    """Compact, indexed list of useful nodes (clickable, editable or with text)."""
    picked = [n for n in nodes if (n.clickable or n.editable or n.text or n.desc) and n.bounds[2] > n.bounds[0]]
    picked = picked[:MAX_NODES]
    lines = []
    for i, n in enumerate(picked):
        flags = ",".join(f for f, on in (("clickable", n.clickable), ("editable", n.editable)) if on)
        lines.append(
            f"{i}|{n.cls.rsplit('.', 1)[-1]}|{(n.text or n.desc)[:60]}|{n.hint[:30]}|{n.rid.rsplit('/', 1)[-1][:30]}|{flags}"
        )
    return "\n".join(lines), picked


def parse_action(text: str, n_nodes: int) -> dict[str, Any] | None:
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
    act = obj["action"]
    node = obj.get("node")
    if act in ("tap", "fill") and (not isinstance(node, int) or isinstance(node, bool) or not 0 <= node < n_nodes):
        return None
    if act == "fill" and not isinstance(obj.get("text"), str):
        return None
    return {
        "action": act,
        "node": node,
        "text": obj.get("text"),
        "reason": str(obj.get("reason") or "")[:200],
    }


async def ask_llm(client: httpx.AsyncClient, s: Settings, messages: list[dict[str, str]]) -> str | None:
    base = s.llm_base_url.rstrip("/")
    body: dict[str, Any] = {"model": s.llm_model, "messages": messages, "max_tokens": 300, "temperature": 0.1}
    if s.llm_model == "sarvam-105b":
        body["reasoning_effort"] = None
    key = s.llm_api_key or ""
    headers = {"api-subscription-key": key} if "sarvam.ai" in base else {"Authorization": f"Bearer {key}"}
    try:
        resp = await client.post(f"{base}/chat/completions", headers=headers, json=body, timeout=CALL_TIMEOUT_S)
        if resp.status_code != 200:
            return None
        return resp.json()["choices"][0]["message"].get("content") or ""
    except (httpx.HTTPError, KeyError, IndexError, ValueError, AttributeError):
        return None


async def drive(
    crawler: Crawler,
    test: AgentTest,
    settings: Settings,
    client: httpx.AsyncClient,
    caption: Callable[[str], None] = lambda _m: None,
) -> HarnessAgentTestResult:
    """Run the goal loop on an already-conditioned device. Always returns a result, never raises."""
    res = HarnessAgentTestResult(id=test.id, title=test.title, condition=test.condition)

    def finish(passed: bool | None, reason: str) -> HarnessAgentTestResult:
        res.passed, res.reason = passed, reason
        res.steps, res.screens = crawler.j.steps, crawler.j.screens
        return res

    try:
        if not await crawler.launch():
            return finish(None, "The app did not launch, so this test could not be judged.")
        xml = await crawler._settle()
        await crawler._capture(xml, "after launch")
        history: list[str] = []
        for _ in range(MAX_STEPS):
            if crawler.cancelled():
                return finish(None, "Stopped before a verdict.")
            listing, nodes = render_nodes(parse_ui_nodes(xml))
            user = (
                f"Test: {test.title}\nGoal: {test.goal}\nSuccess check: {test.success_check}\n"
                f"Previous actions: {'; '.join(history[-5:]) or 'none'}\nVisible UI:\n{listing or '(nothing visible)'}"
            )
            content = await ask_llm(
                client, settings, [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]
            )
            act = parse_action(content, len(nodes)) if content is not None else None
            if act is None:
                return finish(None, "The agent could not decide the next action (no usable answer from the model).")
            kind, reason = act["action"], act["reason"]
            if kind == "done":
                return finish(True, reason or "Success check met.")
            if kind == "fail":
                return finish(False, reason or "Success check not met.")
            t0 = crawler._clock()
            if kind == "back":
                caption(f"Agent: going back — {reason}")
                rc, _, _ = await crawler.adb.shell("input", "keyevent", "KEYCODE_BACK", timeout=15)
                crawler._step("back", rc == 0, "KEYCODE_BACK", t0, reason)
                history.append("back")
            else:
                node = nodes[act["node"]]
                cx, cy = node.center
                if kind == "tap" and is_denied(node):
                    crawler._step("tap", False, node.label, t0, "skipped: unsafe action (pay/delete/logout)")
                    history.append(f"refused to tap '{node.label}'")
                else:
                    caption(f"Agent: {'tapping' if kind == 'tap' else 'typing into'} '{node.label[:40]}' — {reason}")
                    rc, _, _ = await crawler.adb.shell("input", "tap", str(cx), str(cy), timeout=15)
                    if kind == "fill" and rc == 0:
                        if node.text and node.text != node.hint:
                            await crawler.adb.shell(
                                "input", "keyevent", "KEYCODE_MOVE_END", *(["KEYCODE_DEL"] * len(node.text)), timeout=15
                            )
                        rc, _, _ = await crawler.adb.shell("input", "text", adb_text(act["text"][:80]), timeout=15)
                        shown = "(masked)" if node.password else act["text"][:30]
                        crawler._step("fill", rc == 0, node.label, t0, f"typed {shown}: {reason}", xy=(cx, cy))
                        history.append(f"typed '{shown}' into '{node.label}'")
                    else:
                        crawler._step("tap", rc == 0, node.label, t0, reason, xy=(cx, cy))
                        history.append(f"tapped '{node.label}'")
            prev = ui_hash(xml)
            xml = await crawler._settle(prev)
            xml = await crawler._recover_foreground(xml)
            await crawler._capture(xml)
        return finish(None, f"No verdict after {MAX_STEPS} steps; the agent ran out of steps.")
    except Exception as exc:  # noqa: BLE001 - a broken test is reported, never raised
        log.warning("agent test %s errored: %s", test.id, type(exc).__name__)
        return finish(None, f"The test could not run ({type(exc).__name__}).")
