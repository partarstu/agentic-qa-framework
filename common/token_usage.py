# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Token usage and estimated cost captured from a single agent run."""

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
            cost_usd=estimate_cost_usd(usage.input_tokens, usage.output_tokens, model_name),
        )

    def summary_line(self) -> str:
        """One-line, log-friendly summary of the consumed tokens and estimated cost."""
        cost = f"${self.cost_usd:.4f}" if self.cost_usd is not None else "n/a"
        return (
            f"Token usage [{self.model_name}]: input={self.input_tokens}, output={self.output_tokens}, "
            f"total={self.total_tokens}, requests={self.requests}, tool_calls={self.tool_calls}, cost={cost}"
        )


def estimate_cost_usd(input_tokens: int, output_tokens: int, model_name: str) -> float | None:
    """Estimate the USD cost of a run, or ``None`` when the model has no configured price."""
    pricing = config.BudgetConfig.MODEL_PRICING.get(model_name)
    if pricing is None:
        return None
    return (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000
