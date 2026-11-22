"""Agent-written, app-specific tests (f23). The LLM proposes 3-5 tests; invalid output falls back to
deterministic tests derived from the planner. Never raises; never invents conditions."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, get_args

import httpx

from app.analyzer.explain import _llm_config
from app.models import AgentTest, AppInfo, Finding, ProfileId

log = logging.getLogger(__name__)

# low_storage is not applicable on the redroid test phone (shared host disk).
SUPPORTED: set[str] = set(get_args(ProfileId)) - {"low_storage"}
MAX_TESTS = 5
CALL_TIMEOUT_S = 30.0

SYSTEM_PROMPT = (
    "You write 3 to 5 short, concrete UI tests for an Android app that a robot will run on a phone. "
    "Use ONLY the app facts given. Each test is a goal a user could do in the UI (e.g. sign up with an invalid "
    "email and expect an error, search in Hindi, lose network during login then retry). "
    'Reply with strict JSON only: {"tests":[{"id":"snake_case","title":"short title","goal":"what to do",'
    f'"condition":"one of {sorted(SUPPORTED)}","success_check":"what must be visible for pass"}}]}}'
)


def _facts(app: AppInfo, findings: list[Finding]) -> str:
    return json.dumps(
        {
            "package": app.package_name,
            "name": app.app_name,
            "permissions": [p.rsplit(".", 1)[-1] for p in app.permissions][:25],
            "activities": app.activities[:20],
            "ui_strings": app.ui_strings[:40],
            "static_findings": [f.title for f in findings][:8],
        },
        ensure_ascii=False,
    )


def validate(raw: Any) -> list[AgentTest]:
    """Keep only well-formed tests with a supported condition; unique ids; at most MAX_TESTS."""
    items = raw.get("tests") if isinstance(raw, dict) else None
    out: list[AgentTest] = []
    seen: set[str] = set()
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        try:
            t = AgentTest(
                id=re.sub(r"[^a-z0-9_]", "_", str(it.get("id", "")).lower())[:40] or f"t{len(out) + 1}",
                title=str(it["title"]).strip()[:90],
                goal=str(it["goal"]).strip()[:300],
                condition=it.get("condition", "baseline"),
                success_check=str(it["success_check"]).strip()[:300],
            )
        except (KeyError, ValueError):
            continue
        if t.condition not in SUPPORTED or not t.title or not t.goal or t.id in seen:
            continue
        seen.add(t.id)
        out.append(t)
    return out[:MAX_TESTS]


def parse_llm_json(text: str) -> Any:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        return json.loads(text[a : b + 1])
    except ValueError:
        return None


def fallback_tests(app: AppInfo, findings: list[Finding]) -> list[AgentTest]:
    """Deterministic tests from what the APK declares (same signals the planner uses)."""
    from app.planner import plan_initial

    plan = plan_initial(app, findings)
    tests = [
        AgentTest(
            id="first_screen_flow",
            title="Main flow works on a normal connection",
            goal="From the first screen, follow the most obvious primary action (sign in, continue, search) "
            "using sample data and see whether the app responds without an error.",
            condition="baseline",
            success_check="A new screen or content appears and no crash or error dialog is shown.",
        )
    ]
    for r in plan.reasons:
        if r.profile == "flaky_network":
            tests.append(
                AgentTest(
                    id="network_drop_retry",
                    title="Lose network mid-action, then retry",
                    goal="Start the main action (sign in or load content) while the connection drops, then retry.",
                    condition="flaky_network",
                    success_check="The app shows a clear error or recovers; it does not freeze or crash.",
                )
            )
        elif r.profile == "process_death":
            tests.append(
                AgentTest(
                    id="state_after_kill",
                    title="Keep your place after the phone kills the app",
                    goal="Go one or two screens deep, then continue using the app.",
                    condition="process_death",
                    success_check="The app is still usable and not stuck on a blank or loading screen.",
                )
            )
    return validate({"tests": [t.model_dump() for t in tests]})


async def generate_agent_tests(
    app: AppInfo, findings: list[Finding], *, client: httpx.AsyncClient | None = None
) -> tuple[list[AgentTest], str]:
    """Return (tests, source) where source is 'llm' or 'fallback'. Never raises."""
    try:
        cfg = _llm_config()
        if cfg is not None:
            base, model, key, style = cfg
            body: dict[str, Any] = {
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": _facts(app, findings)},
                ],
                "max_tokens": 900,
                "temperature": 0.3,
            }
            if model == "sarvam-105b":
                body["reasoning_effort"] = None
            headers = {"api-subscription-key": key} if style == "sarvam" else {"Authorization": f"Bearer {key}"}
            owned = client is None
            http = client or httpx.AsyncClient()
            try:
                resp = await http.post(f"{base}/chat/completions", headers=headers, json=body, timeout=CALL_TIMEOUT_S)
                if resp.status_code == 200:
                    content = resp.json()["choices"][0]["message"].get("content") or ""
                    tests = validate(parse_llm_json(content))
                    if len(tests) >= 2:
                        return tests, "llm"
            finally:
                if owned:
                    await http.aclose()
    except Exception as exc:  # noqa: BLE001 - best effort
        log.warning("Agent test generation failed: %s", type(exc).__name__)
    return fallback_tests(app, findings), "fallback"
