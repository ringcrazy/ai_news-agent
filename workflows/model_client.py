"""Workflow-facing LLM client helpers.

This module exposes a small compatibility layer for workflow code and the
router. It reuses the underlying provider implementation from
``pipeline.model_client`` but presents a simpler tuple-based interface:

- ``chat(...)`` -> returns ``(text, usage)``
- ``chat_json(...)`` -> returns ``(parsed_json, usage)``

The router depends on these helpers for intent classification and direct chat
responses.
"""

from __future__ import annotations

import json
from typing import Any, Sequence

try:
    from pipeline.model_client import (
        LLMResponse,
        Usage,
        chat_with_retry,
        estimate_token_usage,
    )
except ImportError:  # pragma: no cover - fallback for lint/runtime edge cases
    from pipeline.model_client import (  # type: ignore
        LLMResponse,
        Usage,
        chat_with_retry,
        estimate_token_usage,
    )


def chat(
    messages: Sequence[dict[str, str]],
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
) -> tuple[str, Usage]:
    """Send a chat request and return text plus usage."""

    response: LLMResponse = chat_with_retry(
        messages=messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.content, response.usage


def chat_json(
    messages: Sequence[dict[str, str]],
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
) -> tuple[dict[str, Any], Usage]:
    """Send a chat request expecting JSON output."""

    text, usage = chat(messages, model=model, temperature=temperature, max_tokens=max_tokens)
    parsed = _parse_json(text)
    return parsed, usage


def _parse_json(text: str) -> dict[str, Any]:
    """Parse a JSON object from model output.

    The helper is intentionally forgiving: it first tries a direct JSON parse,
    then falls back to extracting the first JSON object embedded in the text.
    """

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
        return {"value": data}
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1]
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
            return {"value": data}
        except json.JSONDecodeError:
            pass

    return {"text": text}


def estimate_usage(prompt: str, completion: str = "") -> Usage:
    """Expose token estimation for callers that need a fallback."""

    return estimate_token_usage(prompt, completion)


if __name__ == "__main__":
    sample_text, sample_usage = chat([{"role": "user", "content": "用一句话解释 Router 路由模式。"}])
    print(sample_text)
    print(sample_usage)
