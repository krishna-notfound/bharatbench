"""Sarvam clients with HTTP mocked via respx: request shape, auth header, parsing, errors."""

from __future__ import annotations

import io
import json
import wave

import httpx
import pytest
import respx
from voice_fakes import SARVAM, WAV_B64, chat_reply, tool_call

from app.voice import sarvam_llm, sarvam_stt, sarvam_tts
from app.voice.agent import split_sentences, trim_history


def test_pcm_to_wav_is_valid_16k_mono() -> None:
    wav = sarvam_stt.pcm_to_wav(b"\x00\x00" * 1600)
    with wave.open(io.BytesIO(wav)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()) == (16000, 1, 2, 1600)


def test_split_pcm_caps_at_60s_in_30s_chunks() -> None:
    chunks = sarvam_stt.split_pcm(b"\x00" * (sarvam_stt.BYTES_PER_SECOND * 75))
    assert [len(c) for c in chunks] == [sarvam_stt.BYTES_PER_SECOND * 30] * 2


@respx.mock
async def test_transcribe_posts_multipart_with_key_and_returns_text() -> None:
    route = respx.post(f"{SARVAM}/speech-to-text").mock(
        return_value=httpx.Response(200, json={"transcript": "mera app test karo", "language_code": "hi-IN"})
    )
    text = await sarvam_stt.transcribe(b"\x01\x00" * 8000, "auto", "sk_test")
    assert text == "mera app test karo"
    req = route.calls.last.request
    assert req.headers["api-subscription-key"] == "sk_test"
    body = req.content
    assert b'name="model"' in body and b"saaras:v4" in body
    assert b"unknown" in body and b"RIFF" in body


@respx.mock
async def test_transcribe_error_status_raises_without_leaking_key() -> None:
    respx.post(f"{SARVAM}/speech-to-text").mock(return_value=httpx.Response(403))
    with pytest.raises(sarvam_stt.SarvamError) as exc:
        await sarvam_stt.transcribe(b"\x01\x00" * 8000, "hi-IN", "sk_secret")
    assert "sk_secret" not in str(exc.value)


@respx.mock
async def test_chat_sends_tools_and_returns_tool_calls() -> None:
    call = tool_call("list_runs", "{}")
    route = respx.post(f"{SARVAM}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=chat_reply(None, [call]))
    )
    from app.voice.tools import TOOL_SCHEMAS

    message = await sarvam_llm.chat([{"role": "user", "content": "hi"}], TOOL_SCHEMAS, "sk_test")
    assert message["tool_calls"][0]["function"]["name"] == "list_runs"
    sent = json.loads(route.calls.last.request.content)
    assert sent["model"] == "sarvam-105b-conversations"
    assert sent["tools"][0]["type"] == "function" and sent["tool_choice"] == "auto"
    assert route.calls.last.request.headers["api-subscription-key"] == "sk_test"


@respx.mock
async def test_chat_http_error_raises() -> None:
    respx.post(f"{SARVAM}/v1/chat/completions").mock(return_value=httpx.Response(429))
    with pytest.raises(sarvam_stt.SarvamError):
        await sarvam_llm.chat([{"role": "user", "content": "hi"}], None, "sk_test")


@respx.mock
async def test_tts_returns_base64_wav_and_picks_language_by_script() -> None:
    route = respx.post(f"{SARVAM}/text-to-speech").mock(
        return_value=httpx.Response(200, json={"audios": [WAV_B64]})
    )
    data, rate = await sarvam_tts.synthesize("टेस्ट पूरा हुआ।", "auto", "sk_test")
    assert (data, rate) == (WAV_B64, 24000)
    sent = json.loads(route.calls.last.request.content)
    assert sent["language_code"] == "hi-IN" and sent["output_audio_codec"] == "wav"
    assert sent["model"] == "bulbul:v3" and sent["speaker"] == "shubh"
    await sarvam_tts.synthesize("Test complete.", "auto", "sk_test")
    assert json.loads(route.calls.last.request.content)["language_code"] == "en-IN"


def test_split_sentences_handles_danda_and_think_tags() -> None:
    text = "<think>plan</think>Test complete. दो समस्याएँ मिलीं। Ask me!"
    assert split_sentences(text) == ["Test complete.", "दो समस्याएँ मिलीं।", "Ask me!"]


def test_trim_history_keeps_last_20_starting_at_user() -> None:
    history: list[dict[str, str]] = []
    for i in range(15):
        history += [{"role": "user", "content": str(i)}, {"role": "assistant", "content": str(i)}]
    trim_history(history)  # type: ignore[arg-type]
    assert len(history) <= 20 and history[0]["role"] == "user"
