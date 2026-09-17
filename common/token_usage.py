# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Token usage and estimated cost captured from a single agent run."""

from contextvars import ContextVar

from pydantic import Field
from pydantic_ai.usage import RunUsage

import config
from common.models import JsonSerializableModel


class TokenUsage(JsonSerializableModel):
    """Token counts and an estimated USD cost for one agent run.

    The cost is indicative only: it is derived from the static price table in
    ``config.BudgetConfig.MODEL_PRICING`` and is ``None`` when the model is not priced.
    """

    model_name: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cache_read_tokens: int
    requests: int
    tool_calls: int
    cost_usd: float | None
    operations: list["OperationUsage"] = Field(default_factory=list)

    @classmethod
    def from_run_usage(cls, usage: RunUsage, model_name: str) -> "TokenUsage":
        return cls(
            model_name=model_name,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            requests=usage.requests,
            tool_calls=usage.tool_calls,
            cost_usd=estimate_cost_usd(
                max(0, usage.input_tokens - usage.cache_read_tokens - usage.cache_write_tokens),
                usage.output_tokens,
                model_name,
                cache_read_tokens=usage.cache_read_tokens,
                cache_write_tokens=usage.cache_write_tokens,
            ),
        )

    def summary_line(self) -> str:
        """One-line, log-friendly summary of the consumed tokens and estimated cost."""
        cost = f"${self.cost_usd:.4f}" if self.cost_usd is not None else "n/a"
        return (
            f"Token usage [{self.model_name}]: input={self.input_tokens}, output={self.output_tokens}, "
            f"total={self.total_tokens}, requests={self.requests}, tool_calls={self.tool_calls}, cost={cost}"
        )


class OperationUsage(JsonSerializableModel):
    """Usage counters attributed to one named LLM operation."""

    operation: str
    model_name: str
    requests: int = 0
    uncached_input_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0
    tool_calls: int = 0
    cost_usd: float | None = None


class OperationMeter:
    """Accumulate provider usage for one task without sharing state between tasks."""

    def __init__(self) -> None:
        self._operations: dict[tuple[str, str], OperationUsage] = {}

    def add(self, operation: str, model_name: str, usage: RunUsage) -> None:
        """Add a provider usage bucket, accounting for inclusive cache fields."""
        key = (operation, model_name)
        entry = self._operations.setdefault(key, OperationUsage(operation=operation, model_name=model_name))
        entry.requests += usage.requests
        entry.uncached_input_tokens += max(0, usage.input_tokens - usage.cache_read_tokens - usage.cache_write_tokens)
        entry.cache_read_tokens += usage.cache_read_tokens
        entry.cache_write_tokens += usage.cache_write_tokens
        entry.output_tokens += usage.output_tokens
        entry.tool_calls += usage.tool_calls
        entry.cost_usd = estimate_cost_usd(
            entry.uncached_input_tokens,
            entry.output_tokens,
            model_name,
            cache_read_tokens=entry.cache_read_tokens,
            cache_write_tokens=entry.cache_write_tokens,
        )

    def entries(self) -> list[OperationUsage]:
        """Return operation entries in a stable display order."""
        return sorted(self._operations.values(), key=lambda entry: (entry.operation, entry.model_name))


operation_meter: ContextVar[OperationMeter | None] = ContextVar("operation_meter", default=None)


def _pricing(model_name: str) -> dict[str, float] | None:
    """The price table entry of a model, matched on the bare model id without a provider prefix."""
    if model_name in config.BudgetConfig.MODEL_PRICING:
        return config.BudgetConfig.MODEL_PRICING[model_name]
    return config.BudgetConfig.MODEL_PRICING.get(model_name.split(":", 1)[-1])


def estimate_cost_usd(
    uncached_input_tokens: int,
    output_tokens: int,
    model_name: str,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float | None:
    """Estimate the USD cost of a run, or ``None`` when the model has no configured price.

    Cached tokens are priced at their own rates when the price table has them, and at the input
    rate otherwise.
    """
    pricing = _pricing(model_name)
    if pricing is None:
        return None
    input_rate = pricing["input"]
    cache_read_rate = pricing.get("cache_read", input_rate)
    cache_write_rate = pricing.get("cache_write", input_rate)
    total = (
        uncached_input_tokens * input_rate
        + cache_read_tokens * cache_read_rate
        + cache_write_tokens * cache_write_rate
        + output_tokens * pricing["output"]
    )
    return total / 1_000_000
