"""Report insights: Play Store risk, run-vs-previous comparison, and a spoken team brief (f20).

Everything is derived from a run's real findings. The Play Store card never claims a real-user rate: it says what
the lab observed and what Google Play's bad-behaviour thresholds are.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any, Literal

import httpx

from app.analyzer.explain import _llm_config
from app.models import Finding, Run, RunService
from app.voice import languages
from app.voice.config import get_sarvam_key
from app.voice.sarvam_stt import SarvamError
from app.voice.sarvam_tts import synthesize
from app.voice.tools import ToolContext, _compare_runs, _get_report

log = logging.getLogger(__name__)

CRASH_RATE_PCT = 1.09
ANR_RATE_PCT = 0.47
THRESHOLDS = {"crash_rate_pct": CRASH_RATE_PCT, "anr_rate_pct": ANR_RATE_PCT}
BRIEF_TIMEOUT_S = 40.0

RiskLevel = Literal["high", "medium", "low", "unknown"]
_CRASH_RULES = {"rt.crash", "rt.anr", "rt.launch_failed"}
_NETWORK_RULES = {"rt.network_errors", "rt.stuck_loading"}
_LIMITS = "Google Play flags apps above 0.47% ANR rate and 1.09% crash rate of users"


def _reasons(findings: list[Finding]) -> list[dict[str, str]]:
    """One reason per distinct title (titles already name the profile)."""
    seen: dict[str, dict[str, str]] = {}
    for f in findings:
        seen.setdefault(f.title, {"finding_id": f.id, "text": f.title})
    return list(seen.values())


def _result(level: RiskLevel, headline: str, reasons: list[dict[str, str]]) -> dict[str, Any]:
    return {"level": level, "headline": headline, "reasons": reasons, "thresholds": THRESHOLDS}


def assess_play_risk(run: Run, findings: list[Finding]) -> dict[str, Any]:
    """Honest, lab-based Play Store risk level for a run."""
    if run.status != "done":
        return _result("unknown", "Not assessed yet: the run has not finished.", [])
    if not (run.summary and run.summary.runtime_executed):
        return _result("unknown", "Not tested on a device, so crash and ANR behaviour is unknown.", [])

    crashes = [f for f in findings if f.rule_id in _CRASH_RULES]
    if crashes:
        names = {"rt.anr": "ANR", "rt.crash": "crash", "rt.launch_failed": "launch failure"}
        what = " and ".join(sorted({names[f.rule_id] for f in crashes}))
        article = "an" if what[0] in "AEIOU" else "a"
        budget_only = {f.profile_id for f in crashes} == {"budget_2gb"}
        lead = "High risk for budget phones" if budget_only else "High risk"
        where = " on the 2 GB budget-phone profile" if budget_only else ""
        head = (
            f"{lead}: we observed {article} {what}{where} in our lab. {_LIMITS}; "
            "we cannot measure your real-user rate."
        )
        return _result("high", head, _reasons(crashes))

    net = [f for f in findings if f.rule_id in _NETWORK_RULES]
    if net:
        head = (
            "Medium risk: we observed no crash or ANR in our lab, but the app showed network errors or got stuck "
            "loading on a slow connection, which frustrates users and can cause freezes in the field."
        )
        return _result("medium", head, _reasons(net))
    head = (
        f"Low risk: we observed no crash or ANR in our lab runs. This is a small sample, not your real-user rate. "
        f"{_LIMITS}."
    )
    return _result("low", head, [])


async def compare_with_previous(service: RunService, run: Run) -> dict[str, Any] | None:
    """Compare against the newest earlier finished run of the same package; None when there is none."""
    if run.app is None:
        return None
    pkg = run.app.package_name
    candidates = [
        r
        for r in await service.list_runs()
        if r.id != run.id
        and r.status == "done"
        and r.app is not None
        and r.app.package_name == pkg
        and r.created_at < run.created_at
    ]
    if not candidates:
        return None
    prev = max(candidates, key=lambda r: r.created_at)
    cmp = await _compare_runs(service, {"run_a": prev.id, "run_b": run.id}, ToolContext())
    if "error" in cmp:
        return None
    return {
        "previous_run_id": prev.id,
        "score_before": cmp["run_a"]["score"],
        "score_after": cmp["run_b"]["score"],
        "fixed": cmp["fixed"],
        "new": cmp["new"],
        "persisting": cmp["persisting"],
    }


def _language(requested: str) -> languages.Language:
    """auto -> English: a brief has no user text to detect a language from."""
    code = requested if requested in languages.SUPPORTED_CODES else "en-IN"
    return next(lang for lang in languages.LANGUAGES if lang.code == code)


def _brief_prompt(lang: languages.Language) -> str:
    return (
        "You write a 60-second spoken briefing (about 130 words) for a non-technical product manager or founder "
        "about an Android app test. Use ONLY the JSON facts provided; never invent numbers, issues or causes. "
        "No jargon (say 'the app freezes' not 'ANR'), no bullet points, no markdown, no emojis: plain sentences "
        "that sound natural when read aloud. Structure: one sentence on the overall reliability score out of 100; "
        "then the top two issues, each with its business impact (lost users, bad reviews, Play Store ranking); "
        "then exactly one concrete recommendation. If observed_crash_or_anr is not empty, the freeze or crash must be one of the two issues. If the facts say runtime testing did not run, say so plainly. "
        "State that results come from our test lab, not real-user data. "
        f"Write the whole briefing in {lang.english} ({lang.native}), in {lang.script} script."
    )


def _clean_llm_text(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    return re.sub(r"[*#`]+", "", text).strip()


async def _brief_text(facts: dict[str, Any], lang: languages.Language, client: httpx.AsyncClient) -> str:
    cfg = _llm_config()
    if cfg is None:
        raise SarvamError("LLM is not configured")
    base, model, key, style = cfg
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": _brief_prompt(lang)},
            {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
        ],
        "max_tokens": 900,
        "temperature": 0.3,
    }
    if model == "sarvam-105b":
        body["reasoning_effort"] = None
    headers = {"api-subscription-key": key} if style == "sarvam" else {"Authorization": f"Bearer {key}"}
    try:
        resp = await client.post(f"{base}/chat/completions", headers=headers, json=body, timeout=BRIEF_TIMEOUT_S)
        if resp.status_code != 200:
            raise SarvamError(f"chat failed ({resp.status_code})")
        content = resp.json()["choices"][0]["message"].get("content") or ""
    except (httpx.HTTPError, KeyError, IndexError, ValueError, AttributeError) as exc:
        raise SarvamError(f"chat error: {type(exc).__name__}") from exc
    text = _clean_llm_text(content)
    if not text:
        raise SarvamError("chat returned no text")
    return text


async def build_brief(
    service: RunService,
    run: Run,
    findings: list[Finding],
    language: str,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """{text, audio_b64, language}. Raises SarvamError if no text; audio_b64 is None when TTS fails."""
    lang = _language(language)
    report = await _get_report(service, {"run_id": run.id}, ToolContext())
    risk = assess_play_risk(run, findings)
    facts = {
        "app": report.get("app") or {"apk": run.apk_name},
        "score_out_of_100": report.get("score"),
        "runtime_executed": report.get("runtime_executed"),
        "runtime_skipped_reason": report.get("runtime_skipped_reason"),
        "counts": report.get("counts"),
        "top_issues": [
            {k: f.get(k) for k in ("severity", "title", "profile", "cause", "fix")}
            for f in report["top_findings"][:2]
        ],
        "play_store_risk": risk["headline"],
        "play_store_risk_level": risk["level"],
        "observed_crash_or_anr": [r["text"] for r in risk["reasons"]] if risk["level"] == "high" else [],
    }
    owned = client is None
    http = client or httpx.AsyncClient(timeout=BRIEF_TIMEOUT_S)
    try:
        text = await _brief_text(facts, lang, http)
        audio: str | None = None
        key = get_sarvam_key()
        if key:
            try:
                audio, _rate = await synthesize(text, lang.code, key, http)
                base64.b64decode(audio, validate=True)
            except (SarvamError, ValueError):
                log.warning("brief TTS failed; returning text only")
                audio = None
        return {"text": text, "audio_b64": audio, "language": lang.code}
    finally:
        if owned:
            await http.aclose()
