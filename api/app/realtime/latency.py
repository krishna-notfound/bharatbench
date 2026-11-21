"""Per-turn latency marks (port of Oryn voice/latency.py) and rolling aggregates."""

from __future__ import annotations

import statistics
from collections import deque
from time import perf_counter
from typing import Any

WINDOW = 200
METRICS = (
    "stt_ms",
    "llm_ttft_ms",
    "segmentation_ms",
    "tts_ttfb_ms",
    "server_first_audio_ms",
    "speech_end_to_first_audio_ms",
    "interrupt_to_stop_ms",
)


class TurnTimer:
    """Monotonic stage timestamps; the first mark of a stage wins."""

    def __init__(self) -> None:
        self._marks: dict[str, float] = {}

    def mark(self, stage: str, at: float | None = None) -> None:
        self._marks.setdefault(stage, perf_counter() if at is None else at)

    def metrics(self) -> dict[str, Any]:
        def between(a: str, b: str) -> float | None:
            s, e = self._marks.get(a), self._marks.get(b)
            return None if s is None or e is None else round((e - s) * 1000, 1)

        out = {
            "stt_ms": between("speech_end", "stt_final"),
            "llm_ttft_ms": between("llm_request", "llm_first_token"),
            "segmentation_ms": between("llm_first_token", "first_segment"),
            "tts_ttfb_ms": between("tts_request", "tts_first_byte"),
            "server_first_audio_ms": between("turn_started", "first_audio_sent"),
            "speech_end_to_first_audio_ms": between("speech_end", "first_audio_sent"),
            "interrupt_to_stop_ms": between("cancel_requested", "cancel_completed"),
        }
        return {k: v for k, v in out.items() if v is not None}


class LatencyStats:
    def __init__(self) -> None:
        self._samples: dict[str, deque[float]] = {n: deque(maxlen=WINDOW) for n in METRICS}

    def record(self, metrics: dict[str, Any]) -> None:
        for name, value in metrics.items():
            if name in self._samples:
                self._samples[name].append(float(value))

    def summary(self) -> dict[str, dict[str, float]]:
        return {
            n: {"count": len(s), "p50": round(statistics.median(s), 1)} for n, s in self._samples.items() if s
        }


latency_stats = LatencyStats()
