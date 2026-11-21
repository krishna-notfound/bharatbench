import json

import httpx
import pytest

from app.realtime import providers
from app.realtime.tts import SarvamStreamTTS
from app.voice import languages
from app.voice.prompts import build_system_prompt, detect_reply_language, language_reminder

SCRIPT_SAMPLES = {
    "bn": "আমার সর্বশেষ পরীক্ষা কেমন হলো?",
    "pa": "ਮੇਰਾ ਆਖਰੀ ਟੈਸਟ ਕਿਵੇਂ ਰਿਹਾ?",
    "gu": "મારો છેલ્લો ટેસ્ટ કેવો રહ્યો?",
    "od": "ମୋର ଶେଷ ପରୀକ୍ଷା କେମିତି ହେଲା?",
    "ta": "என் சமீபத்திய சோதனை எப்படி போனது?",
    "te": "నా తాజా పరీక్ష ఎలా జరిగింది?",
    "kn": "ನನ್ನ ಇತ್ತೀಚಿನ ಪರೀಕ್ಷೆ ಹೇಗೆ ನಡೆಯಿತು?",
    "ml": "എന്റെ ഏറ്റവും പുതിയ ടെസ്റ്റ് എങ്ങനെ പോയി?",
    "hi": "मेरा पिछला टेस्ट कैसा रहा?",
}


@pytest.mark.parametrize(("key", "text"), SCRIPT_SAMPLES.items())
def test_script_detection(key, text):
    assert detect_reply_language(text, "auto") == key


def test_marathi_by_markers_and_stt_code():
    assert detect_reply_language("माझी शेवटची चाचणी कशी झाली?", "auto") == "mr"
    assert detect_reply_language("मेरा टेस्ट कैसा रहा", "auto", "hi-IN") == "hi"
    assert detect_reply_language("मेरा टेस्ट कैसा रहा", "auto", "mr-IN") == "mr"  # STT code decides


def test_english_and_hinglish():
    assert detect_reply_language("how did my latest test go?", "auto") == "en"
    assert detect_reply_language("mera latest test kaisa raha, batao", "auto") == "hinglish"
    assert detect_reply_language("show me the report", "auto", "en-IN") == "en"


def test_explicit_selection_wins():
    assert detect_reply_language("मेरा टेस्ट कैसा रहा", "ta-IN") == "ta"
    assert detect_reply_language("how did my test go", "bn-IN") == "bn"
    assert detect_reply_language("আমার টেস্ট", "en-IN") == "en"
    assert detect_reply_language("anything", "mr-IN", "hi-IN") == "mr"


def test_reply_rule_names_language_and_script():
    prompt = build_system_prompt(None, "என் சோதனை", "auto")
    assert "Tamil" in prompt and "Tamil script" in prompt and "ANR" in prompt
    reminder = language_reminder("hi", "mr-IN")
    assert "Marathi" in reminder and "Devanagari" in reminder
    assert "Hinglish" in build_system_prompt(None, "mera test kya hua hai", "auto")


def test_human_style_in_prompt():
    prompt = build_system_prompt(None, "hello")
    assert "contractions" in prompt and "As an AI" in prompt and "about 45 percent" in prompt


def test_every_supported_code_has_key_and_rule():
    assert len(languages.LANGUAGES) == 11
    for lang in languages.LANGUAGES:
        assert languages.code_to_key(lang.code) == lang.key
        assert languages.reply_rule(lang.key)
        assert providers.pick_language("x", lang.code) == lang.code
    assert "auto" in languages.SESSION_LANGUAGES and "hi-IN" in languages.SESSION_LANGUAGES


def test_tts_language_from_text_and_context():
    assert providers.pick_language("இது சரி", None) == "ta-IN"
    assert providers.pick_language("ఇది సరే", None) == "te-IN"
    assert providers.pick_language("ही चाचणी झाली", None) == "mr-IN"
    assert providers.pick_language("यह टेस्ट हुआ", None, "mr-IN") == "mr-IN"
    assert providers.pick_language("The test passed", None) == "en-IN"
    # A Latin reply to a Hinglish user is spoken with the Hindi voice
    assert providers.pick_language("Test pass ho gaya", None, None, "mera test kya hua hai") == "hi-IN"
    assert providers.pick_language("Test passed", "ta-IN") == "ta-IN"  # explicit wins


def test_tts_speaker_per_language(monkeypatch):
    monkeypatch.delenv("SARVAM_TTS_SPEAKER", raising=False)
    assert languages.tts_speaker("bn-IN", "shubh") == "rehan"
    assert languages.tts_speaker("ta-IN", "shubh") == "ratan"
    assert languages.tts_speaker("hi-IN", "shubh") == "shubh"
    monkeypatch.setenv("SARVAM_TTS_SPEAKER", "priya")
    assert languages.tts_speaker("bn-IN", "priya") == "priya"


async def test_tts_request_carries_language_code_and_speaker(monkeypatch):
    monkeypatch.delenv("SARVAM_TTS_SPEAKER", raising=False)
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, content=b"\x00\x01" * 100)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        tts = SarvamStreamTTS(client, "k")
        chunks = [c async for c in tts.synthesize("இது ஒரு சோதனை", language="auto")]
    assert chunks
    assert seen["language_code"] == "ta-IN" and seen["speaker"] == "ratan"
