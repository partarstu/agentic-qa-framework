# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

from datetime import UTC, datetime

import pytest
from a2a.types import AgentCapabilities, AgentCard, AgentExtension, AgentInterface

from common.streaming import LogEntryPayload
from orchestrator.dashboard_service import OrchestratorDashboardService, parse_agent_logs
from orchestrator.models import (
    TASK_CAPACITY_EXTENSION_URI,
    AgentRegistry,
    ErrorHistory,
    TaskHistory,
    TaskRecord,
    TaskStatus,
)


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


def test_parse_agent_logs_standard():
    raw_logs = [
        "2026-01-01 12:00:00,000 - agent - INFO - normal message",
        "2026-01-01 12:00:01,000 - agent - ERROR - error message",
    ]
    parsed = parse_agent_logs(raw_logs, "task-1", "agent-1")
    assert len(parsed) == 2
    assert parsed[0].level == "INFO"
    assert parsed[1].level == "ERROR"


def test_parse_agent_logs_json_with_error_field():
    # This matches the user's issue: JSON with "error" field should NOT be classified as ERROR level
    # if it doesn't look like a log line
    json_log = '{"error": "some data", "status": "failed"}'
    # Without timestamp, it might trigger fallback

    raw_logs = [json_log]
    parsed = parse_agent_logs(raw_logs, "task-1", "agent-1")

    assert len(parsed) == 1
    # Should default to INFO, not ERROR (which was the bug)
    assert parsed[0].level == "INFO"
    assert parsed[0].message == json_log


def test_parse_agent_logs_multiline_json():
    raw_logs = [
        "2026-01-01 12:00:00 - agent - INFO - Sending request:",
        "{",
        '  "error": "none",',
        '  "data": "value"',
        "}",
    ]
    parsed = parse_agent_logs(raw_logs, "task-1", "agent-1")

    assert len(parsed) == 5
    # First line is standard
    assert parsed[0].level == "INFO"

    # Subsequent lines (JSON parts) should NOT be detected as ERROR just because 'error' is in text
    assert parsed[2].level == "INFO"
    assert "error" in parsed[2].message


def test_parse_agent_logs_real_log_format():
    # Test with the format that comes from AgentLogCaptureHandler
    # '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    raw_logs = ['2026-01-06 16:20:30,123 - my_agent - INFO - {"error": "data"}']
    parsed = parse_agent_logs(raw_logs, "task-1", "agent-1")

    assert len(parsed) == 1
    assert parsed[0].level == "INFO"
    assert parsed[0].message == '{"error": "data"}'


def test_parse_agent_logs_fallback_timestamp():
    # Verify that when timestamp is missing, we get an empty string
    raw_logs = ["Just a message"]
    parsed = parse_agent_logs(raw_logs, "task-1", "agent-1")

    assert len(parsed) == 1
    # Check that timestamp is empty
    assert parsed[0].timestamp == ""


def test_parse_agent_logs_logback_format():
    # The UI agent emits logback/SLF4J lines: "HH:mm:ss.SSS LEVEL Logger - message".
    # These don't match the Python logging layout, so the level must be detected from the line
    # instead of defaulting to INFO.
    raw_logs = [
        "21:10:43.758 ERROR UiTestAgent - Error during knowledge-based execution",
        "21:10:43.754 DEBUG KnowledgeService - No procedure match found for description: 'x'",
        "21:10:42.918 INFO  KnowledgeBasedExecutionOrchestrator - Processing execution item",
    ]
    parsed = parse_agent_logs(raw_logs, "task-1", "agent-1")

    assert [entry.level for entry in parsed] == ["ERROR", "DEBUG", "INFO"]
    # The full original line is preserved as the message for these formats.
    assert parsed[0].message == raw_logs[0]


@pytest.mark.parametrize(
    ("line", "level"),
    [
        ("21:10:43.758 WARN UiTestAgent - something looks off", "WARNING"),
        ("2026-01-01 12:00:00,000 - agent - WARN - something looks off", "WARNING"),
        ("2026-01-01 12:00:00,000 - agent - fatal - out of memory", "CRITICAL"),
        (
            '{"timestamp": "2026-05-04T10:33:56+00:00", "level": "warn", "message": "slow", "logger": "ui_agent"}',
            "WARNING",
        ),
        (
            '{"timestamp": "2026-05-04T10:33:56+00:00", "level": "FATAL", "message": "down", "logger": "ui_agent"}',
            "CRITICAL",
        ),
    ],
)
def test_parse_agent_logs_normalises_level_aliases_in_every_format(line: str, level: str):
    [entry] = parse_agent_logs([line], "task-1", "agent-1")

    assert entry.level == level


def test_parse_agent_logs_numbers_the_non_empty_lines_of_the_task():
    parsed = parse_agent_logs(["first\n\nsecond", "   ", "third"], "task-1", "agent-1")

    assert [entry.to_dict()["id"] for entry in parsed] == ["task-1:1", "task-1:2", "task-1:3"]


@pytest.mark.asyncio
async def test_streamed_batches_get_the_ids_of_a_page_of_the_same_task():
    tasks = TaskHistory()
    await tasks.add(
        TaskRecord(
            task_id="t1",
            agent_id="agent-1",
            agent_name="Agent",
            description="task",
            status=TaskStatus.RUNNING,
            start_time=datetime.now(UTC),
        )
    )
    streamed_ids = []
    for batch in (["2026-01-01 12:00:00 - agent - INFO - one", "", "21:10:43.758 INFO Ui - two"], ["three", "four"]):
        preceding_line_count = await tasks.append_log_batch("t1", batch)
        streamed_ids += [
            entry.entry_id
            for entry in parse_agent_logs(batch, "t1", "agent-1", preceding_line_count=preceding_line_count)
        ]
    service = OrchestratorDashboardService(AgentRegistry(), tasks, ErrorHistory())

    task_page = await service.get_logs(task_id="t1")
    agent_page = await service.get_logs(agent_id="agent-1")

    assert streamed_ids == ["t1:1", "t1:2", "t1:3", "t1:4"]
    assert sorted(entry["id"] for entry in task_page) == sorted(streamed_ids)
    assert sorted(entry["id"] for entry in agent_page) == sorted(streamed_ids)


def test_parse_agent_logs_keeps_an_unparsable_timestamp_as_given():
    [entry] = parse_agent_logs(["yesterday - agent - INFO - late"], "task-1", "agent-1")

    assert (entry.timestamp, entry.message) == ("yesterday", "late")


def test_parse_agent_logs_turns_a_structured_agent_name_into_text_for_the_stream_payload():
    [entry] = parse_agent_logs(['{"message": "x", "agent_name": 7}'], "task-1", "agent-1")

    assert LogEntryPayload.model_validate(entry.to_dict()).agent_name == "7"


@pytest.mark.asyncio
async def test_get_recent_tasks_leaves_out_the_agent_logs():
    tasks = TaskHistory()
    record = _task_with_usage("t1", 10, None)
    record.agent_logs = ["a log line"]
    await tasks.add(record)
    service = OrchestratorDashboardService(AgentRegistry(), tasks, ErrorHistory())

    [task] = await service.get_recent_tasks()

    assert "agent_logs" not in task
    assert task["task_id"] == "t1"
    assert (await tasks.get_by_id("t1")).to_dict()["agent_logs"] == ["a log line"]


@pytest.mark.asyncio
async def test_get_agents_status_reports_the_agent_version():
    registry = AgentRegistry()
    card = AgentCard(
        name="Agent 1",
        description="Model: test",
        version="2.5",
        supported_interfaces=[AgentInterface(protocol_binding="JSONRPC", url="http://agent-host:8001")],
    )
    await registry.register("agent-1", card)
    service = OrchestratorDashboardService(registry, TaskHistory(), ErrorHistory())

    agents = await service.get_agents_status()

    assert [agent["version"] for agent in agents] == ["2.5"]


def test_parse_agent_logs_reads_structured_fields_through_the_shared_renderer():
    line = (
        '{"timestamp": "2026-05-04T10:33:56+00:00", "level": "error", "message": "Failed", "logger": "ui_agent", '
        '"task_id": "remote-task", "agent_id": null, "agent_name": "UI Agent", "exception": "Traceback: boom"}'
    )

    parsed = parse_agent_logs([line], "task-1", "agent-1")

    assert len(parsed) == 1
    assert parsed[0].timestamp == "2026-05-04T10:33:56+00:00"
    assert parsed[0].level == "ERROR"
    assert parsed[0].logger_name == "ui_agent"
    assert parsed[0].message == "Failed\nTraceback: boom"
    assert parsed[0].task_id == "remote-task"
    assert parsed[0].agent_id == "agent-1"
    assert parsed[0].to_dict()["agent_name"] == "UI Agent"


@pytest.mark.asyncio
async def test_get_agents_status_lists_every_running_task_and_the_capacity():
    registry = AgentRegistry()
    card = AgentCard(
        name="Knowledge Agent",
        capabilities=AgentCapabilities(extensions=[AgentExtension(uri=TASK_CAPACITY_EXTENSION_URI)]),
        supported_interfaces=[AgentInterface(protocol_binding="JSONRPC", url="http://agent-host:8007")],
    )
    card.capabilities.extensions[0].params.update({"capacity": 3})
    await registry.register("agent-1", card)
    tasks = TaskHistory()
    for task_id in ("t1", "t2"):
        await tasks.add(
            TaskRecord(
                task_id=task_id,
                agent_id="agent-1",
                agent_name="Knowledge Agent",
                description=f"select procedures {task_id}",
                status=TaskStatus.RUNNING,
                start_time=datetime.now(),
            )
        )
        await registry.reserve_task("agent-1", task_id)
    service = OrchestratorDashboardService(registry, tasks, ErrorHistory())

    [agent] = await service.get_agents_status()

    assert [task["description"] for task in agent["running_tasks"]] == ["select procedures t1", "select procedures t2"]
    assert agent["task_capacity"] == 3
    assert agent["status"] == "AVAILABLE"
