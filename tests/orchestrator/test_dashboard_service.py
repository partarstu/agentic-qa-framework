# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from orchestrator.dashboard_service import OrchestratorDashboardService
from orchestrator.models import AgentRegistry, ErrorHistory, TaskHistory, TaskRecord, TaskStatus


@pytest.fixture
def mock_dashboard_service():
    registry = MagicMock(spec=AgentRegistry)
    tasks = MagicMock(spec=TaskHistory)
    errors = MagicMock(spec=ErrorHistory)
    return OrchestratorDashboardService(registry, tasks, errors)


def _task_with_usage(task_id: str, total_tokens: int, cost_usd: float | None) -> TaskRecord:
    return TaskRecord(
        task_id=task_id,
        agent_id="agent-1",
        agent_name="Agent",
        description="task",
        status=TaskStatus.COMPLETED,
        start_time=datetime.now(),
        token_usage={"total_tokens": total_tokens, "cost_usd": cost_usd},
    )


@pytest.mark.asyncio
async def test_get_summary_aggregates_tokens_and_cost():
    registry = AgentRegistry()
    tasks = TaskHistory()
    errors = ErrorHistory()
    await tasks.add(_task_with_usage("t1", 1000, 0.01))
    await tasks.add(_task_with_usage("t2", 500, 0.005))
    await tasks.add(_task_with_usage("t3", 200, None))  # unpriced model: tokens count, cost ignored
    service = OrchestratorDashboardService(registry, tasks, errors)

    summary = await service.get_summary()

    assert summary["tokens_total"] == 1700
    assert summary["cost_usd_total"] == 0.015


@pytest.mark.asyncio
async def test_get_summary_cost_none_when_no_priced_tasks():
    registry = AgentRegistry()
    tasks = TaskHistory()
    errors = ErrorHistory()
    await tasks.add(_task_with_usage("t1", 200, None))
    service = OrchestratorDashboardService(registry, tasks, errors)

    summary = await service.get_summary()

    assert summary["tokens_total"] == 200
    assert summary["cost_usd_total"] is None


def test_parse_agent_logs_standard(mock_dashboard_service):
    raw_logs = [
        "2026-01-01 12:00:00,000 - agent - INFO - normal message",
        "2026-01-01 12:00:01,000 - agent - ERROR - error message",
    ]
    parsed = mock_dashboard_service._parse_agent_logs(raw_logs, "task-1", "agent-1")
    assert len(parsed) == 2
    assert parsed[0].level == "INFO"
    assert parsed[1].level == "ERROR"


def test_parse_agent_logs_json_with_error_field(mock_dashboard_service):
    # This matches the user's issue: JSON with "error" field should NOT be classified as ERROR level
    # if it doesn't look like a log line
    json_log = '{"error": "some data", "status": "failed"}'
    # Without timestamp, it might trigger fallback

    raw_logs = [json_log]
    parsed = mock_dashboard_service._parse_agent_logs(raw_logs, "task-1", "agent-1")

    assert len(parsed) == 1
    # Should default to INFO, not ERROR (which was the bug)
    assert parsed[0].level == "INFO"
    assert parsed[0].message == json_log


def test_parse_agent_logs_multiline_json(mock_dashboard_service):
    raw_logs = [
        "2026-01-01 12:00:00 - agent - INFO - Sending request:",
        "{",
        '  "error": "none",',
        '  "data": "value"',
        "}",
    ]
    parsed = mock_dashboard_service._parse_agent_logs(raw_logs, "task-1", "agent-1")

    assert len(parsed) == 5
    # First line is standard
    assert parsed[0].level == "INFO"

    # Subsequent lines (JSON parts) should NOT be detected as ERROR just because 'error' is in text
    assert parsed[2].level == "INFO"
    assert "error" in parsed[2].message


def test_parse_agent_logs_real_log_format(mock_dashboard_service):
    # Test with the format that comes from AgentLogCaptureHandler
    # '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    raw_logs = ['2026-01-06 16:20:30,123 - my_agent - INFO - {"error": "data"}']
    parsed = mock_dashboard_service._parse_agent_logs(raw_logs, "task-1", "agent-1")

    assert len(parsed) == 1
    assert parsed[0].level == "INFO"
    assert parsed[0].message == '{"error": "data"}'


def test_parse_agent_logs_fallback_timestamp(mock_dashboard_service):
    # Verify that when timestamp is missing, we get an empty string
    raw_logs = ["Just a message"]
    parsed = mock_dashboard_service._parse_agent_logs(raw_logs, "task-1", "agent-1")

    assert len(parsed) == 1
    # Check that timestamp is empty
    assert parsed[0].timestamp == ""


def test_parse_agent_logs_logback_format(mock_dashboard_service):
    # The UI agent emits logback/SLF4J lines: "HH:mm:ss.SSS LEVEL Logger - message".
    # These don't match the Python logging layout, so the level must be detected from the line
    # instead of defaulting to INFO.
    raw_logs = [
        "21:10:43.758 ERROR UiTestAgent - Error during knowledge-based execution",
        "21:10:43.754 DEBUG KnowledgeService - No procedure match found for description: 'x'",
        "21:10:42.918 INFO  KnowledgeBasedExecutionOrchestrator - Processing execution item",
    ]
    parsed = mock_dashboard_service._parse_agent_logs(raw_logs, "task-1", "agent-1")

    assert [entry.level for entry in parsed] == ["ERROR", "DEBUG", "INFO"]
    # The full original line is preserved as the message for these formats.
    assert parsed[0].message == raw_logs[0]


def test_parse_agent_logs_warn_alias_normalised(mock_dashboard_service):
    raw_logs = ["21:10:43.758 WARN UiTestAgent - something looks off"]
    parsed = mock_dashboard_service._parse_agent_logs(raw_logs, "task-1", "agent-1")

    assert parsed[0].level == "WARNING"
