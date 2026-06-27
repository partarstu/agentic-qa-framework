# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

from unittest.mock import patch

from pydantic_ai.usage import RunUsage

from common.token_usage import TokenUsage, estimate_cost_usd

_PRICED_MODEL = "test:priced-model"
_PRICING = {_PRICED_MODEL: {"input": 1.0, "output": 2.0}}


def test_estimate_cost_uses_per_million_pricing():
    with patch("config.BudgetConfig.MODEL_PRICING", _PRICING):
        # 1M input * $1 + 1M output * $2 = $3
        assert estimate_cost_usd(1_000_000, 1_000_000, _PRICED_MODEL) == 3.0


def test_estimate_cost_unknown_model_is_none():
    with patch("config.BudgetConfig.MODEL_PRICING", _PRICING):
        assert estimate_cost_usd(100, 100, "unknown:model") is None


def test_from_run_usage_populates_fields_and_cost():
    usage = RunUsage(input_tokens=1000, output_tokens=500, requests=2, tool_calls=3)
    with patch("config.BudgetConfig.MODEL_PRICING", _PRICING):
        token_usage = TokenUsage.from_run_usage(usage, _PRICED_MODEL)

    assert token_usage.model_name == _PRICED_MODEL
    assert token_usage.input_tokens == 1000
    assert token_usage.output_tokens == 500
    assert token_usage.total_tokens == 1500
    assert token_usage.requests == 2
    assert token_usage.tool_calls == 3
    # 1000 * $1/1e6 + 500 * $2/1e6 = 0.002
    assert token_usage.cost_usd == 0.002


def test_round_trip_serialization():
    usage = TokenUsage(
        model_name=_PRICED_MODEL,
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        cache_read_tokens=0,
        requests=1,
        tool_calls=0,
        cost_usd=0.0,
    )
    assert TokenUsage.model_validate_json(usage.model_dump_json()) == usage


def test_summary_line_handles_missing_cost():
    usage = TokenUsage.from_run_usage(RunUsage(input_tokens=1, output_tokens=1), "unknown:model")
    assert "cost=n/a" in usage.summary_line()
