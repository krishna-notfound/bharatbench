"""Provider interfaces shared by the realtime pipeline (ported from Oryn providers/base.py).

Vendor code (Gnani, Sarvam) lives only in stt.py / tts.py adapters implementing these classes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass


class ProviderError(RuntimeError):
    """Raised by adapters. `retryable` says whether a retry (or the next provider) can help."""

    def __init__(self, provider: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class TranscriptEvent:
    text: str
    is_final: bool
    language: str | None = None


@dataclass(frozen=True, slots=True)
class SpeechStarted:
    """Provider-side VAD heard the user start (informational; the browser VAD drives turns)."""


STTEvent = TranscriptEvent | SpeechStarted


class SpeechToTextStream(ABC):
    """One live recognition stream. Adapters without true streaming buffer audio and
    transcribe on `finish()` - and say so in their `streaming` attribute."""

    streaming: bool = True

    async def begin_utterance(self) -> None:
        """The user started speaking (providers with manual endpointing need this)."""

    @abstractmethod
    async def send_audio(self, chunk: bytes) -> None:
        """Push 16 kHz mono PCM s16le."""

    @abstractmethod
    async def finish(self) -> None:
        """The user stopped speaking; flush and emit a final transcript."""

    @abstractmethod
    def events(self) -> AsyncIterator[STTEvent]:
        """Speech-start signals and partial/final transcripts, in order. Raises ProviderError."""

    @abstractmethod
    async def close(self) -> None:
        """Release the connection. Safe to call twice."""


class SpeechToText(ABC):
    name: str

    @abstractmethod
    async def open_stream(self, language: str) -> SpeechToTextStream: ...


class TextToSpeech(ABC):
    name: str
    sample_rate: int = 24_000

    @abstractmethod
    def synthesize(self, text: str, *, language: str, voice: str | None = None) -> AsyncIterator[bytes]:
        """Yield PCM s16le chunks (at `sample_rate`) as soon as they arrive. Closing the
        generator must stop the upstream request."""

    async def warm_up(self) -> None:
        """Open connections ahead of the first reply."""

    async def aclose(self) -> None:
        """Release pooled connections."""
