# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import pytest
from unittest.mock import patch

from pydantic_ai.usage import RunUsage

import config
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


def test_cached_tokens_use_dedicated_rates_when_priced(monkeypatch):
    monkeypatch.setattr(
        config.BudgetConfig,
        "MODEL_PRICING",
        {"claude-opus-5": {"input": 5.0, "output": 25.0, "cache_read": 0.5, "cache_write": 6.25}},
    )
    cost = estimate_cost_usd(90, 10, "claude-opus-5", cache_read_tokens=7, cache_write_tokens=3)

    expected = (90 * 5.0 + 7 * 0.5 + 3 * 6.25 + 10 * 25.0) / 1_000_000
    assert cost == pytest.approx(expected)


def test_cached_tokens_fall_back_to_the_input_rate_when_unpriced(monkeypatch):
    monkeypatch.setattr(config.BudgetConfig, "MODEL_PRICING", {"gemini-3.5-flash": {"input": 0.3, "output": 2.5}})
    cost = estimate_cost_usd(90, 10, "google-gla:gemini-3.5-flash", cache_read_tokens=7, cache_write_tokens=3)

    expected = (100 * 0.3 + 10 * 2.5) / 1_000_000
    assert cost == pytest.approx(expected)


def test_operation_meter_cost_uses_the_cache_rates(monkeypatch):
    from common.token_usage import OperationMeter

    monkeypatch.setattr(
        config.BudgetConfig,
        "MODEL_PRICING",
        {"claude-sonnet-5": {"input": 2.0, "output": 10.0, "cache_read": 0.2, "cache_write": 2.5}},
    )
    meter = OperationMeter()
    meter.add(
        "main",
        "claude-sonnet-5",
        RunUsage(requests=1, input_tokens=110, output_tokens=10, cache_read_tokens=7, cache_write_tokens=3),
    )

    entry = meter.entries()[0]
    expected = (100 * 2.0 + 7 * 0.2 + 3 * 2.5 + 10 * 10.0) / 1_000_000
    assert entry.cost_usd == pytest.approx(expected)
