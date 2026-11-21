"""Languages BharatBench speaks and understands, and how a reply language is chosen.

Only languages supported by BOTH Saaras v4 (STT) and Bulbul v3 (TTS) are offered; the verified list and
source URLs are in SARVAM_NOTES.md. Reply language keys are short: the BCP-47 prefix ("ta", "mr", ...) plus
"hinglish" (romanised Hindi mixed with English, spoken with the hi-IN voice).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Language:
    code: str  # BCP-47, as Sarvam STT and TTS take it
    key: str  # short key used in prompts
    english: str
    native: str
    script: str  # script name for the reply rule
    speaker: str | None = None  # Bulbul v3 speaker recommended for the language; None = the default


LANGUAGES: tuple[Language, ...] = (
    Language("en-IN", "en", "English", "English", "Latin"),
    Language("hi-IN", "hi", "Hindi", "हिन्दी", "Devanagari"),
    Language("bn-IN", "bn", "Bengali", "বাংলা", "Bengali", "rehan"),
    Language("ta-IN", "ta", "Tamil", "தமிழ்", "Tamil", "ratan"),
    Language("te-IN", "te", "Telugu", "తెలుగు", "Telugu"),
    Language("kn-IN", "kn", "Kannada", "ಕನ್ನಡ", "Kannada"),
    Language("ml-IN", "ml", "Malayalam", "മലയാളം", "Malayalam"),
    Language("mr-IN", "mr", "Marathi", "मराठी", "Devanagari"),
    Language("gu-IN", "gu", "Gujarati", "ગુજરાતી", "Gujarati"),
    Language("pa-IN", "pa", "Punjabi", "ਪੰਜਾਬੀ", "Gurmukhi"),
    Language("od-IN", "od", "Odia", "ଓଡ଼ିଆ", "Odia"),
)
SUPPORTED_CODES: frozenset[str] = frozenset(lang.code for lang in LANGUAGES)
SESSION_LANGUAGES: frozenset[str] = SUPPORTED_CODES | {"auto"}
_BY_KEY = {lang.key: lang for lang in LANGUAGES}
_BY_CODE = {lang.code: lang for lang in LANGUAGES}

# Unicode block -> language key (Devanagari is shared by Hindi and Marathi and is resolved separately).
_SCRIPTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile("[ঀ-৿]"), "bn"),
    (re.compile("[਀-੿]"), "pa"),
    (re.compile("[઀-૿]"), "gu"),
    (re.compile("[଀-୿]"), "od"),
    (re.compile("[஀-௿]"), "ta"),
    (re.compile("[ఀ-౿]"), "te"),
    (re.compile("[ಀ-೿]"), "kn"),
    (re.compile("[ഀ-ൿ]"), "ml"),
)
_DEVANAGARI = re.compile("[ऀ-ॿ]")
_LATIN_WORD = re.compile(r"[a-z]+")
_DEVA_WORD = re.compile("[ऀ-ॿ]+")

# Romanised Hindi words that rarely occur in English. One strong + any other, or two strong, marks Hinglish.
_STRONG = {"hai", "hain", "kya", "kyun", "kaise", "batao", "bataiye", "karo", "kijiye", "mera", "mere", "meri",
           "mujhe", "nahi", "nahin", "chahiye", "sabse", "accha", "acha", "theek", "thik", "ruko", "chalao", "dikhao"}
_WEAK = {"ka", "ki", "ke", "ko", "se", "aur", "bhi", "tum", "aap", "raha", "rahi", "wala", "wali", "bada", "abhi"}

# Devanagari words that are Marathi, not Hindi. The letter ळ (U+0933) is also a strong Marathi marker.
_MARATHI_WORDS = {"आहे", "आहेत", "काय", "मला", "माझे", "माझा", "माझी", "माझ्या", "तुम्ही", "नाही", "झाले", "झाली",
                  "झाला", "करा", "सांगा", "दाखवा", "कसे", "कसा", "आणि", "होते", "होती", "तुमचे", "तुमचा", "तुमची",
                  "चाचणी", "चालवा", "पाहिजे", "आता", "काही", "सर्वात", "म्हणजे", "कृपया", "मी", "आम्ही", "त्याचे"}


def code_to_key(code: str | None) -> str | None:
    """'ta-IN' -> 'ta' when supported, else None."""
    lang = _BY_CODE.get(code or "")
    return lang.key if lang else None


def is_marathi(text: str) -> bool:
    if "ळ" in text:
        return True
    return any(w in _MARATHI_WORDS for w in _DEVA_WORD.findall(text))


def detect_script_language(text: str, stt_code: str | None = None) -> str | None:
    """Language key from the script of `text`; None when it is Latin/unknown. Devanagari: STT code, else markers."""
    for pattern, key in _SCRIPTS:
        if pattern.search(text):
            return key
    if _DEVANAGARI.search(text):
        if stt_code in ("mr-IN", "hi-IN"):
            return code_to_key(stt_code)
        return "mr" if is_marathi(text) else "hi"
    return None


def is_hinglish(text: str) -> bool:
    words = _LATIN_WORD.findall(text.lower())
    strong = sum(w in _STRONG for w in words)
    weak = sum(w in _WEAK for w in words)
    return strong >= 1 and strong + weak >= 2 or strong >= 2


def detect_reply_language(user_text: str, preference: str | None, stt_code: str | None = None) -> str:
    """Reply language key. Explicit selection wins; else the message's script (Devanagari split by the STT
    code); else Hinglish detection; else English."""
    explicit = code_to_key(preference)
    if explicit:
        return explicit
    scripted = detect_script_language(user_text, stt_code)
    if scripted:
        return scripted
    if is_hinglish(user_text) or (stt_code == "hi-IN" and user_text.strip()):
        return "hinglish"  # Hindi speech transcribed in Latin script is romanised Hindi
    return "en"


def reply_rule(key: str) -> str:
    if key == "hinglish":
        return (
            "Reply in Hinglish: Hindi written in Latin script mixed with English, the way the user writes, "
            "as an Indian developer would talk."
        )
    if key == "en":
        return "Reply in English, because the user wrote in English."
    lang = _BY_KEY[key]
    return (
        f"Reply in {lang.english} ({lang.native}), written in {lang.script} script, because the user is "
        f"speaking {lang.english}. Keep technical terms such as ANR, APK, logcat, crash, RAM and API in "
        f"English, as Indian developers do, and write everything else in {lang.english}."
    )


def tts_language(text: str, preference: str | None, stt_code: str | None = None, user_text: str = "") -> str:
    """BCP-47 code for Bulbul. Explicit selection wins; else the reply's script (Devanagari split by the STT
    code or Marathi markers); Latin text follows the user's language (Hinglish is spoken with hi-IN)."""
    if preference in SUPPORTED_CODES:
        return str(preference)
    key = detect_script_language(text, stt_code)
    if key is None:
        key = detect_reply_language(user_text, None, stt_code) if user_text else "en"
        if key == "hinglish":
            key = "hi"
        elif _BY_KEY[key].script != "Latin":
            key = "en"  # a Latin-script reply to a non-Latin user: English voice
    return _BY_KEY[key].code


def tts_speaker(code: str, default: str) -> str:
    """Speaker for a language: SARVAM_TTS_SPEAKER (if set) wins, else the doc-recommended v3 speaker, else default."""
    lang = _BY_CODE.get(code)
    if os.environ.get("SARVAM_TTS_SPEAKER") or lang is None or lang.speaker is None:
        return default
    return lang.speaker
