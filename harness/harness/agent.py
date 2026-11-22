"""Goal-directed agent test driver (f23).

For one AgentTest: send the LLM the goal and a compact list of visible UI nodes, execute the single action
it answers with (tap / fill / back / done / fail) through the Crawler primitives, repeat up to MAX_STEPS.
The API key is never logged.

Invariants (tests: harness/tests/test_agent.py, test_credentials.py):
- The LLM only sees node text, never a stored password: secrets.py tokenises credentials before the prompt and
  expands them at input time.
- The same denylist as the crawler (`parsers.is_denied`) vetoes any tap the model asks for.
- With no LLM key configured the agent tests are skipped with a note, not faked.
- Bounded by MAX_STEPS actions and a per-call timeout.
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
from .secrets import Secrets
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
    '"met":true|false (required with done),"reason":"short plain sentence"}. Use "done" with "met":true only when '
    'the success check is visibly met (reason says what you saw); if the check is NOT met use "fail" '
    '(or "done" with "met":false). Use "fail" when the app clearly does not behave as the success check requires '
    'or is stuck/broken. '
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
        "met": obj.get("met") if isinstance(obj.get("met"), bool) else None,
        "reason": str(obj.get("reason") or "")[:200],
    }


# A "done" whose own reason says the check failed must not count as a pass.
_NOT_MET = re.compile(
    r"(?:not (?:been )?met|isn'?t met|wasn'?t met|not (?:been )?satisfied|check (?:fails|failed|is not met))",
    re.IGNORECASE,
)


def verdict(act: dict[str, Any]) -> bool:
    """True only for an explicit, consistent pass."""
    if act["action"] != "done":
        return False
    if act.get("met") is False:
        return False
    return not _NOT_MET.search(act.get("reason") or "")


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
    *,
    secrets: Secrets | None = None,
    launch: bool = True,
) -> HarnessAgentTestResult:
    """Run the goal loop on an already-conditioned device. Always returns a result, never raises.

    With a test account the model only sees <LOGIN>/<PASSWORD>/<OTP>; the real value is substituted at input time.
    `launch=False` continues in the app that is already open (used after logging in)."""
    res = HarnessAgentTestResult(id=test.id, title=test.title, condition=test.condition)
    sec = secrets or Secrets(None)
    system = SYSTEM_PROMPT + (" " + sec.prompt_addendum() if sec.available else "")

    def finish(passed: bool | None, reason: str) -> HarnessAgentTestResult:
        res.passed, res.reason = passed, reason
        res.steps, res.screens = crawler.j.steps, crawler.j.screens
        return res

    try:
        if launch:
            if not await crawler.launch():
                return finish(None, "The app did not launch, so this test could not be judged.")
            xml = await crawler._settle()
        else:
            xml = await crawler.dump_ui()
        await crawler._capture(xml, "after launch" if launch else "continuing")
        history: list[str] = []
        for _ in range(MAX_STEPS):
            if crawler.cancelled():
                return finish(None, "Stopped before a verdict.")
            listing, nodes = render_nodes(parse_ui_nodes(xml))
            listing = sec.tokenize(listing)
            user = (
                f"Test: {test.title}\nGoal: {test.goal}\nSuccess check: {test.success_check}\n"
                f"Previous actions: {'; '.join(history[-5:]) or 'none'}\nVisible UI:\n{listing or '(nothing visible)'}"
            )
            content = await ask_llm(
                client, settings, [{"role": "system", "content": system}, {"role": "user", "content": user}]
            )
            act = parse_action(content, len(nodes)) if content is not None else None
            if act is None:
                return finish(None, "The agent could not decide the next action (no usable answer from the model).")
            kind, reason = act["action"], sec.mask(act["reason"])
            if kind == "done":
                passed = verdict(act)
                return finish(passed, reason or ("Success check met." if passed else "Success check not met."))
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
                    history.append(f"refused to tap '{sec.tokenize(node.label)}'")
                else:
                    caption(f"Agent: {'tapping' if kind == 'tap' else 'typing into'} '{sec.mask(node.label[:40])}' — {reason}")
                    rc, _, _ = await crawler.adb.shell("input", "tap", str(cx), str(cy), timeout=15)
                    if kind == "fill" and rc == 0:
                        if node.text and node.text != node.hint:
                            await crawler.adb.shell(
                                "input", "keyevent", "KEYCODE_MOVE_END", *(["KEYCODE_DEL"] * len(node.text)), timeout=15
                            )
                        wanted = act["text"][:80]
                        used = sec.uses_secret(wanted)
                        rc, _, _ = await crawler.adb.shell("input", "text", adb_text(sec.expand(wanted)), timeout=15)
                        if used or node.password:  # the real value is substituted only in the line above
                            label = "password" if node.password or "password" in used else used[0]
                            crawler._step("fill", rc == 0, node.label, t0, f"Filling {label} (hidden): {reason}", xy=(cx, cy))
                            history.append(f"typed {label} (hidden) into '{sec.tokenize(node.label)}'")
                        else:
                            crawler._step("fill", rc == 0, node.label, t0, f"typed {sec.mask(wanted[:30])}: {reason}", xy=(cx, cy))
                            history.append(f"typed '{sec.mask(wanted[:30])}' into '{sec.tokenize(node.label)}'")
                    else:
                        crawler._step("tap", rc == 0, node.label, t0, reason, xy=(cx, cy))
                        history.append(f"tapped '{sec.tokenize(node.label)}'")
            prev = ui_hash(xml)
            xml = await crawler._settle(prev)
            xml = await crawler._recover_foreground(xml)
            await crawler._capture(xml)
        return finish(None, f"No verdict after {MAX_STEPS} steps; the agent ran out of steps.")
    except Exception as exc:  # noqa: BLE001 - a broken test is reported, never raised
        log.warning("agent test %s errored: %s", test.id, type(exc).__name__)
        return finish(None, f"The test could not run ({type(exc).__name__}).")
