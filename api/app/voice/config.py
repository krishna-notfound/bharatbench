"""Sarvam configuration helpers (key lookup and endpoint constants)."""

from __future__ import annotations

import os

SARVAM_BASE_URL = "https://api.sarvam.ai"
STT_MODEL = "saaras:v4"
CHAT_MODEL_DEFAULT = "sarvam-105b-conversations"
TTS_MODEL_DEFAULT = "bulbul:v3"
TTS_SPEAKER_DEFAULT = "shubh"
TTS_SAMPLE_RATE = 24000
HTTP_TIMEOUT = 30.0


def get_sarvam_key() -> str | None:
    """Key from app.settings (f02) when present, else the SARVAM_API_KEY environment variable."""
    try:
        import app.settings as settings_module

        getter = getattr(settings_module, "get_settings", None)
        settings = getter() if callable(getter) else getattr(settings_module, "settings", None)
        key = getattr(settings, "sarvam_api_key", None)
        if key:
            return str(key)
    except ImportError:
        pass
    return os.environ.get("SARVAM_API_KEY") or None


def chat_model() -> str:
    return os.environ.get("SARVAM_CHAT_MODEL", CHAT_MODEL_DEFAULT)


def tts_model() -> str:
    return os.environ.get("SARVAM_TTS_MODEL", TTS_MODEL_DEFAULT)


def tts_speaker() -> str:
    return os.environ.get("SARVAM_TTS_SPEAKER", TTS_SPEAKER_DEFAULT)
