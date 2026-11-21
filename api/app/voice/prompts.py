"""System prompt for the BharatBench voice agent."""

import re

SYSTEM_PROMPT = """You are BharatBench's voice assistant. BharatBench tests Android apps (APKs) under real Indian \
network and device conditions and reports reliability findings.

Rules:
- {language_rule} Keep it to at most two \
short spoken sentences unless the user asks you to explain a finding. No markdown, no lists, no emojis.
- Never invent results. Only report what tools returned. If a tool returns an error, say so honestly.
- To test an app call start_test. Pick profile ids from list_profiles: for "slow network" use flaky_network and \
budget_2gb; for "low memory" use budget_2gb; the default is baseline, budget_2gb, flaky_network. To re-run, pass the \
active run (or the most recent run) as apk_run_id. You cannot upload files; tell the user to upload the APK in the web UI.
- Use list_runs, get_run_status, list_findings and explain_finding to answer questions about results.
- Call cancel_run ONLY if the user explicitly said cancel, stop or ruko for that run.
- Active run id: {active_run}.
"""


_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_WORD = re.compile(r"[a-z]+")
# Romanised Hindi words that rarely occur in English. Two hits (or one strong) mark the message as Hinglish.
_STRONG = {"hai", "hain", "kya", "kyun", "kaise", "batao", "bataiye", "karo", "kijiye", "mera", "mere", "meri",
           "mujhe", "nahi", "nahin", "chahiye", "sabse", "accha", "acha", "theek", "thik", "ruko", "chalao", "dikhao"}
_WEAK = {"ka", "ki", "ke", "ko", "se", "aur", "bhi", "tum", "aap", "raha", "rahi", "wala", "wali", "bada", "abhi"}

_RULES = {
    "en": "Reply in English, because the user wrote in English.",
    "hi": "Reply in Hindi using Devanagari script.",
    "hinglish": "Reply in Hinglish: Hindi written in Latin script mixed with English, matching the user's style.",
}


def detect_reply_language(user_text: str, preference: str | None) -> str:
    """Language for the reply: explicit preference wins, else mirror the user's last message."""
    if preference == "hi-IN":
        return "hi"
    if preference == "en-IN":
        return "en"
    if _DEVANAGARI.search(user_text):
        return "hi"
    words = _WORD.findall(user_text.lower())
    strong = sum(w in _STRONG for w in words)
    weak = sum(w in _WEAK for w in words)
    return "hinglish" if strong >= 1 and strong + weak >= 2 or strong >= 2 else "en"


def build_system_prompt(active_run_id: str | None, user_text: str = "", preference: str | None = "auto") -> str:
    rule = _RULES[detect_reply_language(user_text, preference)]
    return SYSTEM_PROMPT.format(active_run=active_run_id or "none", language_rule=rule)
