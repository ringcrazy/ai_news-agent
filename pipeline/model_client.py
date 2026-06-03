"""Unified LLM client for OpenAI-compatible providers.

This module provides a small abstraction over OpenAI-compatible chat APIs so
that the application can switch between providers by environment variables.

Supported providers:
- DeepSeek
- Qwen
- OpenAI

The implementation intentionally uses ``httpx`` directly instead of the OpenAI
SDK to keep dependencies small and the transport layer explicit.
"""

from __future__ import annotations

import abc
import dataclasses
import logging
import math
import os
import time
from pathlib import Path
from typing import Any, Optional, Sequence, TypeVar

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency
    load_dotenv = None

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional dependency
    OpenAI = None


if load_dotenv is not None:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")

LOGGER = logging.getLogger(__name__)

DEFAULT_PROVIDER = "deepseek"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_TIMEOUT_SECONDS = 60.0
MAX_RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY_SECONDS = 1.0
TOKEN_CHARS_PER_TOKEN = 4.0

# Approximate USD pricing per 1M tokens.
PRICING_PER_1M_TOKENS = {
    "deepseek-chat": {"input": 0.14, "output": 0.28},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19},
    "qwen-plus": {"input": 0.40, "output": 0.80},
    "qwen-max": {"input": 0.80, "output": 2.40},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 5.00, "output": 15.00},
}

T = TypeVar("T")


@dataclasses.dataclass(frozen=True)
class Usage:
    """Token usage statistics.

    Attributes:
        prompt_tokens: Estimated or reported prompt token count.
        completion_tokens: Estimated or reported completion token count.
        total_tokens: Total token count.
        estimated: Whether the values are estimated instead of reported by API.
    """

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated: bool = False


@dataclasses.dataclass(frozen=True)
class LLMResponse:
    """Standard response returned by LLM providers.

    Attributes:
        content: Generated assistant text.
        usage: Token usage statistics.
        model: Model name used for the request.
        provider: Provider name used for the request.
        cost_usd: Estimated request cost in USD.
        raw_response: Optional raw response payload from the provider.
    """

    content: str
    usage: Usage
    model: str
    provider: str
    cost_usd: float = 0.0
    raw_response: Optional[dict[str, Any]] = None


class LLMProvider(abc.ABC):
    """Abstract base class for chat model providers."""

    @abc.abstractmethod
    def chat(
        self,
        messages: Sequence[dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """Send a chat request.

        Args:
            messages: Chat messages in OpenAI format.
            model: Optional model override.
            temperature: Sampling temperature.
            max_tokens: Optional upper bound for completion tokens.

        Returns:
            A normalized LLM response.
        """

    @property
    @abc.abstractmethod
    def provider_name(self) -> str:
        """Return the provider identifier."""


class OpenAICompatibleProvider(LLMProvider):
    """Provider implementation for OpenAI-compatible chat APIs."""

    def __init__(
        self,
        *,
        provider_name: str,
        api_key: str,
        base_url: str,
        default_model: str,
    ) -> None:
        """Initialize the provider.

        Args:
            provider_name: Human-readable provider name.
            api_key: API key for authentication.
            base_url: OpenAI-compatible base URL.
            default_model: Default model to use when not specified.
        """

        if OpenAI is None:
            raise ProviderConfigError(
                "The openai package is required for NVIDIA-compatible usage. "
                "Install it with: pip install openai"
            )

        self._provider_name = provider_name
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._client = OpenAI(api_key=api_key, base_url=self._base_url)

    @property
    def provider_name(self) -> str:
        """Return provider name."""

        return self._provider_name

    def chat(
        self,
        messages: Sequence[dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """Send a chat completion request.

        Args:
            messages: Chat messages in OpenAI format.
            model: Optional model override.
            temperature: Sampling temperature.
            max_tokens: Optional upper bound for completion tokens.

        Returns:
            Normalized LLM response.

        Raises:
            httpx.HTTPError: If the request fails.
            ValueError: If the response payload is invalid.
        """

        target_model = model or self._default_model
        LOGGER.debug(
            "Sending chat request provider=%s model=%s base_url=%s",
            self._provider_name,
            target_model,
            self._base_url,
        )
        response = self._client.chat.completions.create(
            model=target_model,
            messages=list(messages),
            temperature=temperature,
            top_p=0.95,
            max_tokens=max_tokens or 16384,
            extra_body={"chat_template_kwargs": {"thinking": False}},
            stream=False,
        )

        data = response.model_dump()
        content = _extract_content(data)
        usage = _extract_usage(data, messages, content)
        cost_usd = calculate_cost_usd(target_model, usage)

        return LLMResponse(
            content=content,
            usage=usage,
            model=target_model,
            provider=self._provider_name,
            cost_usd=cost_usd,
            raw_response=data,
        )

    def close(self) -> None:
        """Close the underlying HTTP client."""

        self._client.close()

    def __enter__(self) -> "OpenAICompatibleProvider":
        """Enter context manager."""

        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        """Exit context manager and close the client."""

        self.close()


class ProviderConfigError(RuntimeError):
    """Raised when provider configuration is invalid."""


def get_env_provider() -> LLMProvider:
    """Create a provider based on environment variables.

    The function first attempts to load variables from a local ``.env`` file
    located at the project root, then falls back to the existing process
    environment.

    Environment variables:
        LLM_PROVIDER: Provider name, defaults to ``deepseek``.
        NVIDIA_API_KEY: API key for NVIDIA's OpenAI-compatible endpoint.
        DEEPSEEK_API_KEY: API key for DeepSeek.
        QWEN_API_KEY: API key for Qwen.
        OPENAI_API_KEY: API key for OpenAI.

    Returns:
        Configured provider instance.

    Raises:
        ProviderConfigError: If required configuration is missing.
    """

    provider = os.getenv("LLM_PROVIDER", DEFAULT_PROVIDER).strip().lower()
    if provider == "nvidia":
        return OpenAICompatibleProvider(
            provider_name="nvidia",
            api_key=_require_env("NVIDIA_API_KEY"),
            base_url=os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
            default_model=os.getenv("NVIDIA_MODEL", "deepseek-ai/deepseek-v4-pro"),
        )
    if provider == "deepseek":
        return OpenAICompatibleProvider(
            provider_name="deepseek",
            api_key=_require_env("DEEPSEEK_API_KEY"),
            base_url=os.getenv(
                "DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"
            ),
            default_model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        )
    if provider == "qwen":
        return OpenAICompatibleProvider(
            provider_name="qwen",
            api_key=_require_env("QWEN_API_KEY"),
            base_url=os.getenv(
                "QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
            ),
            default_model=os.getenv("QWEN_MODEL", "qwen-plus"),
        )
    if provider == "openai":
        return OpenAICompatibleProvider(
            provider_name="openai",
            api_key=_require_env("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            default_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        )

    raise ProviderConfigError(f"Unsupported LLM_PROVIDER: {provider!r}")


def chat_with_retry(
    messages: Sequence[dict[str, str]],
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
) -> LLMResponse:
    """Call the configured provider with retries.

    Args:
        messages: Chat messages in OpenAI format.
        model: Optional model override.
        temperature: Sampling temperature.
        max_tokens: Optional upper bound for completion tokens.

    Returns:
        Normalized LLM response.

    Raises:
        Exception: Re-raises the last error after all retry attempts fail.
    """

    provider = get_env_provider()
    try:
        for attempt in range(1, MAX_RETRY_ATTEMPTS + 1):
            try:
                return provider.chat(
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except (httpx.TimeoutException, httpx.HTTPError, ValueError):
                if attempt >= MAX_RETRY_ATTEMPTS:
                    LOGGER.exception("LLM request failed after retries")
                    raise
                delay = RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
                LOGGER.warning(
                    "LLM request failed, retrying in %.1f seconds (attempt %s/%s)",
                    delay,
                    attempt,
                    MAX_RETRY_ATTEMPTS,
                )
                time.sleep(delay)
    finally:
        close_fn = getattr(provider, "close", None)
        if callable(close_fn):
            close_fn()

    raise RuntimeError("Unexpected retry flow failure")


def create_provider() -> LLMProvider:
    """Compatibility alias for creating the configured provider."""

    return get_env_provider()


def quick_chat(prompt: str, model: Optional[str] = None) -> str:
    """Convenience helper for a one-shot user prompt.

    Args:
        prompt: User prompt text.
        model: Optional model override.

    Returns:
        Assistant response text.
    """

    response = chat_with_retry(
        messages=[{"role": "user", "content": prompt}],
        model=model,
    )
    return response.content


def estimate_token_usage(
    prompt: str,
    completion: str = "",
) -> Usage:
    """Estimate token usage from text length.

    Args:
        prompt: Prompt text.
        completion: Completion text.

    Returns:
        Estimated usage statistics.
    """

    prompt_tokens = max(1, math.ceil(len(prompt) / TOKEN_CHARS_PER_TOKEN))
    completion_tokens = max(0, math.ceil(len(completion) / TOKEN_CHARS_PER_TOKEN))
    total_tokens = prompt_tokens + completion_tokens
    return Usage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        estimated=True,
    )


def calculate_cost_usd(model: str, usage: Usage) -> float:
    """Estimate USD cost for a request.

    Args:
        model: Model name.
        usage: Usage statistics.

    Returns:
        Estimated cost in USD.
    """

    pricing = PRICING_PER_1M_TOKENS.get(model.lower())
    if pricing is None:
        return 0.0

    input_cost = usage.prompt_tokens * pricing["input"] / 1_000_000
    output_cost = usage.completion_tokens * pricing["output"] / 1_000_000
    return round(input_cost + output_cost, 8)


def _require_env(name: str) -> str:
    """Read a required environment variable.

    Args:
        name: Environment variable name.

    Returns:
        Environment variable value.

    Raises:
        ProviderConfigError: If the variable is missing.
    """

    value = os.getenv(name, "").strip()
    if not value:
        raise ProviderConfigError(f"Missing required environment variable: {name}")
    return value


def _extract_content(data: dict[str, Any]) -> str:
    """Extract assistant content from an OpenAI-compatible response."""

    choices = data.get("choices") or []
    if not choices:
        raise ValueError("Response does not contain choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not isinstance(content, str):
        raise ValueError("Response message content is missing or invalid")
    return content


def _extract_usage(
    data: dict[str, Any],
    messages: Sequence[dict[str, str]],
    content: str,
) -> Usage:
    """Extract or estimate usage statistics from a response."""

    usage_data = data.get("usage") or {}
    prompt_tokens = usage_data.get("prompt_tokens")
    completion_tokens = usage_data.get("completion_tokens")
    total_tokens = usage_data.get("total_tokens")

    if all(isinstance(value, int) for value in (prompt_tokens, completion_tokens, total_tokens)):
        return Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            estimated=False,
        )

    prompt_text = "\n".join(
        str(message.get("content", "")) for message in messages
    )
    estimated = estimate_token_usage(prompt_text, content)
    return estimated


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        result = quick_chat("请用一句话介绍什么是 RAG。")
        LOGGER.info("LLM response: %s", result)
    except Exception:
        LOGGER.exception("Quick chat test failed")
