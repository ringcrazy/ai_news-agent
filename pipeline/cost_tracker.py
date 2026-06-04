"""LLM cost tracking utilities.

This module keeps an in-memory running total of LLM token usage and estimated
costs. It is intentionally lightweight so the pipeline can import and use it
without adding extra dependencies.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from model_client import Usage

LOGGER = logging.getLogger(__name__)

# 价格表单位为「元 / 百万 tokens」
# 这里按你的项目约定，记录的是国产模型的估算成本，便于流水线结束后汇总。
PRICING_PER_1M_TOKENS_CNY = {
    "deepseek": {"input": 1.0, "output": 2.0},
    "qwen": {"input": 4.0, "output": 12.0},
    "openai": {"input": 150.0, "output": 600.0},
}


@dataclasses.dataclass
class _CostRecord:
    """Aggregate token usage and cost for one provider.

    This is the internal storage unit used by ``CostTracker``. Each provider has
    one record that accumulates:

    - prompt token count
    - completion token count
    - total token count
    - estimated total cost in CNY
    """

    provider: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_cny: float = 0.0


class CostTracker:
    """Track token usage and estimated cost for LLM calls.

    The tracker is intentionally stateful and in-memory. The workflow is:

    1. A model call succeeds.
    2. The caller passes the returned ``Usage`` object into ``record()``.
    3. The tracker accumulates usage for that provider.
    4. ``report()`` can be called at the end of the pipeline to print a summary.
    """

    def __init__(self) -> None:
        """Initialize an empty in-memory record map."""

        self._records: dict[str, _CostRecord] = {}

    def record(self, usage: Usage, provider: str) -> None:
        """Record one successful LLM API call.

        Args:
            usage: Token usage data returned by the provider.
            provider: Provider name, for example ``deepseek``, ``qwen`` or
                ``openai``.
        """

        provider_name = provider.strip().lower()
        cost_cny = self._estimate_cost_cny(provider_name, usage)

        # 如果这个 provider 之前没有记录过，就先创建一个空记录。
        record = self._records.get(provider_name)
        if record is None:
            record = _CostRecord(provider=provider_name)
            self._records[provider_name] = record

        # 累计 token 和成本，便于在整个 pipeline 结束后查看总消耗。
        record.prompt_tokens += usage.prompt_tokens
        record.completion_tokens += usage.completion_tokens
        record.total_tokens += usage.total_tokens
        record.cost_cny += cost_cny

    def estimated_cost(self, provider: str) -> float:
        """Return the accumulated estimated cost for a provider.

        Args:
            provider: Provider name.

        Returns:
            Accumulated estimated cost in CNY. If the provider has never been
            recorded, returns ``0.0``.
        """

        record = self._records.get(provider.strip().lower())
        return round(record.cost_cny, 6) if record is not None else 0.0

    def report(self, provider: Optional[str] = None) -> None:
        """Log a GitHub Actions friendly cost report.

        Args:
            provider: Optional provider name. If provided, only the matching
                provider is reported. If omitted, all providers are reported.
        """

        prefix = "::notice::"
        if provider is not None:
            provider_name = provider.strip().lower()
            record = self._records.get(provider_name)
            if record is None:
                LOGGER.info("%sCost report for %s: no usage recorded", prefix, provider_name)
                return

            LOGGER.info(
                "%sCost report | provider=%s | prompt_tokens=%s | completion_tokens=%s | total_tokens=%s | cost_cny=%.6f",
                prefix,
                provider_name,
                record.prompt_tokens,
                record.completion_tokens,
                record.total_tokens,
                record.cost_cny,
            )
            return

        if not self._records:
            LOGGER.info("%sCost report: no usage recorded", prefix)
            return

        total_cost = 0.0
        total_tokens = 0

        for record in self._records.values():
            total_cost += record.cost_cny
            total_tokens += record.total_tokens
            LOGGER.info(
                "%sCost report | provider=%s | prompt_tokens=%s | completion_tokens=%s | total_tokens=%s | cost_cny=%.6f",
                prefix,
                record.provider,
                record.prompt_tokens,
                record.completion_tokens,
                record.total_tokens,
                record.cost_cny,
            )

        LOGGER.info(
            "%sCost report summary | providers=%s | total_tokens=%s | total_cost_cny=%.6f",
            prefix,
            len(self._records),
            total_tokens,
            total_cost,
        )

    @staticmethod
    def _estimate_cost_cny(provider: str, usage: Usage) -> float:
        """Estimate the cost for a single call.

        Args:
            provider: Provider name.
            usage: Token usage for this call.

        Returns:
            Estimated cost in CNY. If the provider is unknown, returns ``0.0``.
        """

        pricing = PRICING_PER_1M_TOKENS_CNY.get(provider)
        if pricing is None:
            return 0.0

        return (
            usage.prompt_tokens * pricing["input"]
            + usage.completion_tokens * pricing["output"]
        ) / 1_000_000


# 全局单例：方便 pipeline 在任何地方记录调用成本，结束时统一汇总。
GLOBAL_COST_TRACKER = CostTracker()


def get_cost_tracker() -> CostTracker:
    """Return the global cost tracker instance."""

    return GLOBAL_COST_TRACKER
