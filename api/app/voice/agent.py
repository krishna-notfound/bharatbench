"""LLM agent loop: tool rounds, sentence splitting, per-sentence TTS."""

from __future__ import annotations

import asyncio
import json
import re
from typing import TYPE_CHECKING, Any

from app.voice import sarvam_llm, sarvam_tts, tools
from app.voice.prompts import build_system_prompt
from app.voice.sarvam_stt import SarvamError

if TYPE_CHECKING:
    from app.voice.session import VoiceSession

MAX_TOOL_ROUNDS = 4
HISTORY_LIMIT = 20
_SENTENCE_END = re.compile(r"(?<=[.!?।])\s+")
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


def split_sentences(text: str) -> list[str]:
    cleaned = _THINK.sub("", text).strip()
    return [s.strip() for s in _SENTENCE_END.split(cleaned) if s.strip()]


def trim_history(history: list[dict[str, Any]]) -> None:
    """Keep the last HISTORY_LIMIT messages, starting at a user message so tool pairs stay intact."""
    del history[:-HISTORY_LIMIT]
    while history and history[0].get("role") != "user":
        del history[0]


def _parse_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


async def speak(session: VoiceSession, turn_id: str, text: str, spoken: list[str]) -> None:
    """Emit each sentence as assistant_text then its TTS audio, so playback starts after sentence one."""
    tts_ok = True
    for sentence in split_sentences(text):
        await session.emit(turn_id, {"type": "assistant_text", "text": sentence, "turn_id": turn_id})
        spoken.append(sentence)
        if not tts_ok:
            continue
        try:
            data, rate = await sarvam_tts.synthesize(sentence, session.language, session.api_key)
        except SarvamError as exc:
            tts_ok = False
            await session.emit(turn_id, {"type": "error", "message": str(exc)})
            continue
        await session.emit(
            turn_id,
            {"type": "audio", "turn_id": turn_id, "format": "wav", "sample_rate": rate, "data": data},
        )


async def run_turn(session: VoiceSession, turn_id: str, user_text: str) -> None:
    """One user turn. On cancellation history is rewritten to user text + spoken part '(interrupted)'."""
    history = session.history
    start = len(history)
    history.append({"role": "user", "content": user_text})
    spoken: list[str] = []
    try:
        for round_no in range(MAX_TOOL_ROUNDS + 1):
            schemas = tools.TOOL_SCHEMAS if round_no < MAX_TOOL_ROUNDS else None
            system = {"role": "system", "content": build_system_prompt(session.active_run_id)}
            message = await sarvam_llm.chat([system, *history], schemas, session.api_key)
            calls = message.get("tool_calls")
            if not calls:
                await speak(session, turn_id, message.get("content") or "", spoken)
                reply = " ".join(spoken)
                if reply:
                    history.append({"role": "assistant", "content": reply})
                return
            history.append(
                {"role": "assistant", "content": message.get("content") or "", "tool_calls": calls}
            )
            for call in calls:
                await _run_tool_call(session, turn_id, call)
    except asyncio.CancelledError:
        del history[start:]
        history.append({"role": "user", "content": user_text})
        if spoken:
            history.append({"role": "assistant", "content": " ".join(spoken) + " (interrupted)"})
        raise
    finally:
        trim_history(history)


async def _run_tool_call(session: VoiceSession, turn_id: str, call: dict[str, Any]) -> None:
    fn = call.get("function", {})
    name = str(fn.get("name", ""))
    args = _parse_args(fn.get("arguments"))
    await session.emit(turn_id, {"type": "tool_call", "name": name, "args": args, "turn_id": turn_id})
    result = await tools.dispatch(session.service(), name, args, session.tool_context())
    ok = "error" not in result
    summary = str(result.get("error") if not ok else json.dumps(result, default=str))[:200]
    await session.emit(turn_id, {"type": "tool_result", "name": name, "ok": ok, "summary": summary})
    session.history.append(
        {"role": "tool", "tool_call_id": call.get("id", ""), "content": json.dumps(result, default=str)}
    )
    if name == "start_test" and ok:
        session.watch_run(str(result["run_id"]))
    elif name in ("get_run_status", "list_findings") and ok and args.get("run_id"):
        session.active_run_id = session.active_run_id or str(args["run_id"])
