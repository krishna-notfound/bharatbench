from app.voice.prompts import build_system_prompt, detect_reply_language


def test_plain_english_gets_english():
    assert detect_reply_language("Show my recent sessions", "auto") == "en"


def test_devanagari_gets_hindi():
    assert detect_reply_language("मेरे टेस्ट दिखाओ", "auto") == "hi"


def test_latin_hindi_gets_hinglish():
    assert detect_reply_language("Mere test runs batao, sabse bada issue kya hai?", "auto") == "hinglish"


def test_single_ambiguous_word_stays_english():
    # "ke"/"ka" alone can appear in names; one weak marker must not flip English to Hinglish.
    assert detect_reply_language("What did the ka test find?", "auto") == "en"


def test_explicit_preference_wins():
    assert detect_reply_language("Show my sessions", "hi-IN") == "hi"
    assert detect_reply_language("मेरे टेस्ट", "en-IN") == "en"


def test_prompt_carries_language_instruction():
    assert "Reply in English" in build_system_prompt(None, "Show my recent sessions", "auto")
    assert "Hinglish" in build_system_prompt(None, "kya haal hai, mera app test karo", "auto")
