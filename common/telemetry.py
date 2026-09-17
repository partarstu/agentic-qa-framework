# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""OpenTelemetry metrics for the per-operation token usage of agent tasks (WS13).

On task completion the executor records each operation's counters into the
``gen_ai.client.token.usage`` histogram (GenAI semantic conventions): one data point per
operation and token type, with the operation and agent name as attributes. Export goes to
``OTEL_EXPORTER_OTLP_ENDPOINT`` when configured; without it the default no-op meter is used,
so nothing fails when no collector exists.

The meter provider is created once per process and flushed on shutdown, because agents are
short-lived and the periodic export interval could otherwise outlive them.
"""

import atexit

from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

import config
from common import utils
from common.token_usage import OperationUsage

logger = utils.get_logger("telemetry")

TOKEN_USAGE_HISTOGRAM = "gen_ai.client.token.usage"

# Provider names per the GenAI semantic conventions, derived from the pydantic-ai model prefix.
_PROVIDER_BY_PREFIX = {
    "google-gla:": "gcp.genai",
    "google-vertex:": "gcp.vertex",
    "anthropic:": "anthropic",
    "openai:": "openai",
    "qwen:": "qwen",
}

_meter: metrics.Meter | None = None
_meter_provider: MeterProvider | None = None


def get_meter() -> metrics.Meter:
    """The process-wide meter, created once with the service name as resource."""
    global _meter, _meter_provider
    if _meter is None:
        resource = Resource.create({"service.name": "quaia-agent"})
        exporter = OTLPMetricExporter(endpoint=config.OPEN_TELEMETRY_URL) if config.OPEN_TELEMETRY_URL else None
        readers = [PeriodicExportingMetricReader(exporter)] if exporter is not None else []
        _meter_provider = MeterProvider(metric_readers=readers, resource=resource)
        metrics.set_meter_provider(_meter_provider)
        _meter = metrics.get_meter("quaia.gen_ai")
        atexit.register(_shutdown)
    return _meter


def record_operation_usage(agent_name: str, entries: list[OperationUsage]) -> None:
    """Record the counters of one completed task, one data point per operation and token type."""
    if not entries:
        return
    histogram = get_meter().create_histogram(
        TOKEN_USAGE_HISTOGRAM,
        unit="{token}",
        description="Tokens consumed per LLM operation and token type.",
    )
    for entry in entries:
        base_attributes = {
            "gen_ai.operation.name": "invoke_agent",
            "gen_ai.provider.name": _provider_name(entry.model_name),
            "gen_ai.request.model": entry.model_name,
            "gen_ai.agent.name": agent_name,
            "quaia.operation": entry.operation,
        }
        # Per the conventions, the input type is the full input (cached tokens included) and the
        # cache types are breakdowns of it.
        token_types = {
            "input": entry.uncached_input_tokens + entry.cache_read_tokens + entry.cache_write_tokens,
            "output": entry.output_tokens,
            "cache_read": entry.cache_read_tokens,
            "cache_creation": entry.cache_write_tokens,
        }
        for token_type, value in token_types.items():
            histogram.record(
                value,
                attributes={**base_attributes, "gen_ai.token.type": token_type},
            )


def _provider_name(model_name: str) -> str:
    for prefix, provider in _PROVIDER_BY_PREFIX.items():
        if model_name.startswith(prefix):
            return provider
    return "unknown"


def _shutdown() -> None:
    global _meter_provider
    if _meter_provider is not None:
        try:
            _meter_provider.force_flush()
            _meter_provider.shutdown()
        except Exception:
            logger.exception("Failed to flush the OpenTelemetry meter provider on shutdown.")
        finally:
            _meter_provider = None
