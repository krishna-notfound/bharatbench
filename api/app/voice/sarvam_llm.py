"""Sarvam chat completions (OpenAI-compatible, tool calling supported)."""

from __future__ import annotations

from typing import Any

import httpx

from app.voice.config import HTTP_TIMEOUT, SARVAM_BASE_URL, chat_model
from app.voice.sarvam_stt import SarvamError


async def chat(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    api_key: str,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """One chat completion; returns the assistant message dict (content and/or tool_calls)."""
    model = chat_model()
    body: dict[str, Any] = {"model": model, "messages": messages, "max_tokens": 600}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    if model == "sarvam-105b":
        body["reasoning_effort"] = None  # reasoning off for low latency
    owned = client is None
    http = client or httpx.AsyncClient(timeout=HTTP_TIMEOUT * 2)
    try:
        resp = await http.post(
            f"{SARVAM_BASE_URL}/v1/chat/completions",
            headers={"api-subscription-key": api_key},
            json=body,
        )
        if resp.status_code != 200:
            raise SarvamError(f"chat completion failed ({resp.status_code})")
        return dict(resp.json()["choices"][0]["message"])
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        raise SarvamError(f"chat completion error: {type(exc).__name__}") from exc
    finally:
        if owned:
            await http.aclose()
