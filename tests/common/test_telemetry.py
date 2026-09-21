# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for the per-operation token-usage metrics."""

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from pydantic_ai.usage import RunUsage

from common import telemetry
from common.token_usage import OperationMeter, OperationUsage


def _reader_meter(monkeypatch) -> InMemoryMetricReader:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    monkeypatch.setattr(telemetry, "get_meter", lambda: provider.get_meter("test"))
    # The instrument is cached process-wide, so each test starts from an unbuilt one.
    monkeypatch.setattr(telemetry, "_histogram", None)
    return reader


def _data_points(reader, histogram_name):
    data = reader.get_metrics_data()
    if data is None:
        return []
    for resource_metric in data.resource_metrics:
        for scope_metric in resource_metric.scope_metrics:
            for metric in scope_metric.metrics:
                if metric.name == histogram_name:
                    return metric.data.data_points
    return []


def test_operation_counters_are_recorded_per_token_type_and_operation(monkeypatch):
    reader = _reader_meter(monkeypatch)
    meter = OperationMeter()
    meter.add("main", "google-gla:gemini-3.5-flash", RunUsage(requests=2, input_tokens=110, output_tokens=20))
    meter.add(
        "duplicate_detector", "google-gla:gemini-3.5-flash", RunUsage(requests=1, input_tokens=55, output_tokens=8)
    )

    telemetry.record_operation_usage("incident_creation", meter.entries())

    points = _data_points(reader, telemetry.TOKEN_USAGE_HISTOGRAM)
    by_operation_and_type = {
        (point.attributes["quaia.operation"], point.attributes["gen_ai.token.type"]): point.sum for point in points
    }
    assert by_operation_and_type[("main", "input")] == 110
    assert by_operation_and_type[("main", "output")] == 20
    assert by_operation_and_type[("duplicate_detector", "input")] == 55
    for point in points:
        assert point.attributes["gen_ai.operation.name"] == "invoke_agent"
        assert point.attributes["gen_ai.provider.name"] == "gcp.genai"
        assert point.attributes["gen_ai.request.model"] == "google-gla:gemini-3.5-flash"
        assert point.attributes["gen_ai.agent.name"] == "incident_creation"


def test_cache_breakdown_token_types_are_recorded(monkeypatch):
    reader = _reader_meter(monkeypatch)
    entry = OperationUsage(
        operation="main",
        model_name="claude-opus-5",
        requests=1,
        uncached_input_tokens=90,
        cache_read_tokens=7,
        cache_write_tokens=3,
        output_tokens=12,
    )

    telemetry.record_operation_usage("test_case_review", [entry])

    points = _data_points(reader, telemetry.TOKEN_USAGE_HISTOGRAM)
    by_type = {point.attributes["gen_ai.token.type"]: point.sum for point in points}
    assert by_type == {"input": 100, "output": 12, "cache_read": 7, "cache_creation": 3}


def test_no_metrics_are_recorded_without_entries(monkeypatch):
    reader = _reader_meter(monkeypatch)

    telemetry.record_operation_usage("incident_creation", [])

    assert _data_points(reader, telemetry.TOKEN_USAGE_HISTOGRAM) == []


def test_the_instrument_is_built_once_across_tasks(monkeypatch):
    """A second create_histogram for the same name makes the SDK log a duplicate registration."""
    _reader_meter(monkeypatch)
    entry = OperationUsage(operation="main", model_name="claude-opus-5", requests=1, output_tokens=1)

    telemetry.record_operation_usage("test_case_review", [entry])
    first = telemetry.get_histogram()
    telemetry.record_operation_usage("test_case_review", [entry])

    assert telemetry.get_histogram() is first
