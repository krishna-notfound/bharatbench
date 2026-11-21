"""Best-effort, evidence-grounded LLM explanations for the top findings.

The model sees only the finding JSON (including its evidence excerpts). Output must be strict JSON and may
not name classes/files/URLs absent from that input; anything else keeps the deterministic text.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx

from app.models import Evidence, Finding

log = logging.getLogger(__name__)

TOP_N = 8
TOTAL_BUDGET_S = 30.0
CONCURRENCY = 3
CALL_TIMEOUT_S = 25.0
DEFAULT_BASE_URL = "https://api.sarvam.ai/v1"
DEFAULT_MODEL = "sarvam-105b"
NOTE_PREFIX = "AI explanation (based on the evidence above): "

SYSTEM_PROMPT = (
    "You are an Android app quality reviewer. You are given ONE finding as JSON, including its evidence. "
    "Use ONLY that JSON. Do not mention any class, file, package, method or URL that does not appear in it. "
    "Reply with strict JSON only, no markdown, with exactly these string keys: "
    '"probable_cause" (one sentence), "suggested_fix" (one or two sentences), '
    '"developer_explanation" (2-3 plain sentences on what is wrong and why it matters to users).'
)

_URL = re.compile(r"https?://[^\s\"'<>)\]]+")
_DOTTED = re.compile(r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)+")
_ALLOWED_TOKENS = {
    "e.g", "i.e", "androidmanifest.xml", "build.gradle", "proguard-rules.pro", "gradle.properties",
}
_KEYS = ("probable_cause", "suggested_fix", "developer_explanation")

LlmConfig = tuple[str, str, str, str]


def _llm_config() -> LlmConfig | None:
    """(base_url, model, api_key, auth_style) or None when no key is configured."""
    from app.settings import get_settings

    s = get_settings()
    key = getattr(s, "llm_api_key", None) or getattr(s, "sarvam_api_key", None)
    if not key:
        return None
    base = (getattr(s, "llm_base_url", None) or DEFAULT_BASE_URL).rstrip("/")
    model = getattr(s, "llm_model", None) or DEFAULT_MODEL
    style = "sarvam" if "sarvam.ai" in base else "bearer"
    return base, model, str(key), style


def _finding_payload(f: Finding) -> dict[str, Any]:
    return f.model_dump(
        mode="json",
        include={
            "rule_id", "title", "severity", "category", "description", "evidence", "repro_steps",
            "profile_id", "probable_cause", "suggested_fix",
        },
    )


def parse_output(text: str) -> dict[str, str] | None:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(text[start : end + 1])
    except ValueError:
        return None
    if not isinstance(obj, dict) or not all(isinstance(obj.get(k), str) and obj[k].strip() for k in _KEYS):
        return None
    return {k: obj[k].strip() for k in _KEYS}


def validate_grounded(output: dict[str, str], source_text: str) -> bool:
    """Reject output naming URLs or dotted identifiers (classes/files) not present in the source JSON."""
    haystack = source_text.lower()
    for value in output.values():
        for url in _URL.findall(value):
            if url.rstrip(".,;").lower() not in haystack:
                return False
        for tok in _DOTTED.findall(_URL.sub(" ", value)):
            t = tok.rstrip(".").lower()
            if t not in _ALLOWED_TOKENS and t not in haystack:
                return False
    return True


async def _explain_one(client: httpx.AsyncClient, cfg: LlmConfig, f: Finding) -> dict[str, str] | None:
    base, model, key, style = cfg
    payload = json.dumps(_finding_payload(f), ensure_ascii=False)
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": payload},
        ],
        "max_tokens": 700,
        "temperature": 0.2,
    }
    if model == "sarvam-105b":
        body["reasoning_effort"] = None
    headers = {"api-subscription-key": key} if style == "sarvam" else {"Authorization": f"Bearer {key}"}
    try:
        resp = await client.post(f"{base}/chat/completions", headers=headers, json=body, timeout=CALL_TIMEOUT_S)
        if resp.status_code != 200:
            return None
        content = resp.json()["choices"][0]["message"].get("content") or ""
    except (httpx.HTTPError, KeyError, IndexError, ValueError, AttributeError):
        return None
    parsed = parse_output(content)
    if parsed is None or not validate_grounded(parsed, payload):
        return None
    return parsed


def _apply(f: Finding, out: dict[str, str]) -> Finding:
    note = Evidence(kind="note", excerpt=NOTE_PREFIX + out["developer_explanation"])
    return f.model_copy(
        update={
            "evidence": [*f.evidence, note],
            "probable_cause": out["probable_cause"],
            "suggested_fix": out["suggested_fix"],
        }
    )


async def explain_findings(
    findings: list[Finding],
    *,
    client: httpx.AsyncClient | None = None,
    budget_s: float = TOTAL_BUDGET_S,
) -> tuple[list[Finding], int]:
    """Return (findings with explanations added where valid, number explained). Never raises."""
    try:
        cfg = _llm_config()
        if cfg is None or not findings:
            return findings, 0
        ranked = sorted(
            range(len(findings)),
            key=lambda i: findings[i].impact.score if findings[i].impact else 0.0,
            reverse=True,
        )[:TOP_N]
        owned = client is None
        http = client or httpx.AsyncClient()
        sem = asyncio.Semaphore(CONCURRENCY)
        results: dict[int, dict[str, str]] = {}

        async def work(i: int) -> None:
            async with sem:
                out = await _explain_one(http, cfg, findings[i])
            if out:
                results[i] = out

        tasks = [asyncio.create_task(work(i)) for i in ranked]
        try:
            _, pending = await asyncio.wait(tasks, timeout=budget_s)
            for t in pending:
                t.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        finally:
            if owned:
                await http.aclose()
        updated = [_apply(f, results[i]) if i in results else f for i, f in enumerate(findings)]
        return updated, len(results)
    except Exception:  # best-effort: never fail the run
        log.exception("Explanation step failed; keeping deterministic text")
        return findings, 0
