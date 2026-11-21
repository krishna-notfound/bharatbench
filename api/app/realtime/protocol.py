"""Wire helpers for WS /ws/realtime: Oryn protocol v2 envelope plus BharatBench additions.

Text frames are JSON. Server events: {"v":2,"type",...,"session_id","turn_id"?,"generation_id"?,"seq","ts"}.
Binary server frames: uint32 BE generation_id + uint32 BE seq + PCM s16le at the rate in audio.started.
Binary client frames: 16 kHz mono PCM s16le.
"""

from __future__ import annotations

import json
import struct
import time
from typing import Any

PROTOCOL_VERSION = 2
INPUT_SAMPLE_RATE = 16_000
MAX_AUDIO_FRAME_BYTES = 32_768
MAX_TEXT_CHARS = 2_000
AUDIO_HEADER = struct.Struct(">II")

# state values (Oryn VoiceState, uppercase) plus the BharatBench addition WORKING (a tool is executing)
IDLE = "IDLE"
LISTENING = "LISTENING"
PROCESSING = "PROCESSING"
GENERATING = "GENERATING"
SPEAKING = "SPEAKING"
INTERRUPTED = "INTERRUPTED"
WORKING = "WORKING"
ERROR = "ERROR"


def encode_event(
    type_: str,
    *,
    session_id: str,
    seq: int,
    turn_id: int | None = None,
    generation_id: int | None = None,
    **fields: Any,
) -> str:
    envelope: dict[str, Any] = {"v": PROTOCOL_VERSION, "type": type_, "session_id": session_id}
    if turn_id is not None:
        envelope["turn_id"] = turn_id
    if generation_id is not None:
        envelope["generation_id"] = generation_id
    envelope["seq"] = seq
    envelope["ts"] = int(time.time() * 1000)
    return json.dumps(envelope | fields, ensure_ascii=False, separators=(",", ":"), default=str)


def pack_audio_frame(generation_id: int, seq: int, pcm: bytes) -> bytes:
    return AUDIO_HEADER.pack(generation_id, seq) + pcm


def parse_client_message(raw: str) -> dict[str, Any]:
    """Raises ValueError on malformed input."""
    msg = json.loads(raw)
    if not isinstance(msg, dict) or not isinstance(msg.get("type"), str):
        raise ValueError("message must be a JSON object with a string type")  # noqa: TRY004
    return msg
