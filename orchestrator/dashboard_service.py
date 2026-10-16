# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Dashboard service for aggregating orchestrator state for the Web UI."""

import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from google.protobuf.json_format import MessageToDict

import config
from common import utils
from common.services.sync_lock_store import SYNC_OUTCOME_RECORD_KIND
from common.services.vector_db_service import VectorDbService
from orchestrator.memory_log_handler import LogEntry, memory_log_handler
from orchestrator.models import (
    ORCHESTRATOR_START_TIME,
    AgentRegistry,
    AgentStatus,
    ErrorHistory,
    TaskHistory,
    agent_registry,
    error_history,
    iter_log_lines,
    task_history,
)

logger = utils.get_logger("orchestrator_dashboard")

# Uppercase log-level tokens used as a fallback for agent log formats that don't match the
# Python logging layout (e.g. the logback/SLF4J format "HH:mm:ss.SSS LEVEL Logger - message"
# emitted by the UI agent). Matching is case-sensitive on purpose so a lowercase "error"
# inside a JSON payload is not mistaken for an ERROR-level line.
_LEVEL_TOKEN_PATTERN = re.compile(r"\b(CRITICAL|FATAL|ERROR|WARNING|WARN|INFO|DEBUG|TRACE)\b")
_LEVEL_ALIASES = {"WARN": "WARNING", "FATAL": "CRITICAL"}
_TASK_LOGS_KEY = "agent_logs"


def _normalise_level(level: str) -> str:
    level = level.upper()
    return _LEVEL_ALIASES.get(level, level)


def _detect_log_level(line: str) -> str | None:
    """Return the first recognised uppercase log-level token in a line, normalising aliases."""
    match = _LEVEL_TOKEN_PATTERN.search(line)
    if match is None:
        return None
    return _normalise_level(match.group(1))


def parse_agent_logs(
    raw_logs: Iterable[str], task_id: str, agent_id: str, *, preceding_line_count: int = 0
) -> list[LogEntry]:
    """Parse raw agent log lines into entries whose id ``<task_id>:<n>`` counts the task's non-empty lines after the preceding ones."""
    return [
        _parse_agent_log_line(line, f"{task_id}:{number}", task_id, agent_id)
        for number, line in enumerate(iter_log_lines(raw_logs), start=preceding_line_count + 1)
    ]


def _parse_agent_log_line(line: str, entry_id: str, task_id: str, agent_id: str) -> LogEntry:
    """Parse a structured JSON record, a ``timestamp - logger - level - message`` line, or any other line as its own message."""
    structured = utils.parse_log_record(line)
    if structured is not None:
        agent_name = structured.get("agent_name")
        return LogEntry(
            timestamp=str(structured.get("timestamp", "")),
            level=_normalise_level(str(structured.get("level", "INFO"))),
            logger_name=str(structured.get("logger", f"agent.{agent_id}")),
            message=utils.render_log_message(structured),
            task_id=str(structured.get("task_id") or task_id),
            agent_id=str(structured.get("agent_id") or agent_id),
            agent_name=None if agent_name is None else str(agent_name),
            entry_id=entry_id,
        )

    parts = line.split(" - ", 3)
    if len(parts) < 4:
        return LogEntry(
            timestamp="",
            level=_detect_log_level(line) or "INFO",
            logger_name=f"agent.{agent_id}",
            message=line,
            task_id=task_id,
            agent_id=agent_id,
            entry_id=entry_id,
        )

    raw_timestamp, parsed_logger, parsed_level, parsed_message = parts
    return LogEntry(
        timestamp=_parse_log_timestamp(raw_timestamp.strip()),
        level=_normalise_level(parsed_level.strip()),
        logger_name=parsed_logger.strip(),
        message=parsed_message,
        task_id=task_id,
        agent_id=agent_id,
        entry_id=entry_id,
    )


def _parse_log_timestamp(raw_timestamp: str) -> str:
    """Return the Python logging timestamp (``2026-01-06 16:20:30,123``, milliseconds optional) in ISO form, else as given."""
    for timestamp_format in ("%Y-%m-%d %H:%M:%S,%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw_timestamp, timestamp_format).isoformat()
        except ValueError:
            continue
    return raw_timestamp


class OrchestratorDashboardService:
    """Service for providing dashboard data to the Web UI."""

    def __init__(self, registry: AgentRegistry, tasks: TaskHistory, errors: ErrorHistory):
        self.registry = registry
        self.tasks = tasks
        self.errors = errors

    async def get_summary(self) -> dict[str, Any]:
        """Returns high-level statistics for the dashboard."""
        cards = await self.registry.get_all_cards()
        total_agents = len(cards)
        available = 0
        busy = 0
        broken = 0

        for agent_id in cards:
            status = await self.registry.get_status(agent_id)
            if status == AgentStatus.AVAILABLE:
                available += 1
            elif status == AgentStatus.BUSY:
                busy += 1
            elif status == AgentStatus.BROKEN:
                broken += 1

        # Get task counts
        all_tasks = await self.tasks.get_all()
        running_tasks = sum(1 for t in all_tasks if t.status.value == "RUNNING")
        completed_tasks = sum(1 for t in all_tasks if t.status.value == "COMPLETED")
        failed_tasks = sum(1 for t in all_tasks if t.status.value == "FAILED")

        # Aggregate token consumption and estimated cost across recorded tasks. Cost is summed
        # only over tasks with a known (priced) cost; it stays None when none are priced.
        tokens_total = 0
        cost_usd_total = 0.0
        cost_known = False
        for task in all_tasks:
            usage = task.token_usage
            if not usage:
                continue
            tokens_total += usage.get("total_tokens") or 0
            cost = usage.get("cost_usd")
            if cost is not None:
                cost_usd_total += cost
                cost_known = True

        # Get error count
        all_errors = await self.errors.get_all()

        # Calculate uptime
        uptime_seconds = int((datetime.now(UTC) - ORCHESTRATOR_START_TIME).total_seconds())

        return {
            "agents_total": total_agents,
            "agents_available": available,
            "agents_busy": busy,
            "agents_broken": broken,
            "tasks_running": running_tasks,
            "tasks_completed": completed_tasks,
            "tasks_failed": failed_tasks,
            "tasks_total": len(all_tasks),
            "errors_total": len(all_errors),
            "tokens_total": tokens_total,
            "cost_usd_total": round(cost_usd_total, 4) if cost_known else None,
            "orchestrator_start_time": ORCHESTRATOR_START_TIME.isoformat(),
            "uptime_seconds": uptime_seconds,
            "current_time": datetime.now(UTC).isoformat(),
            "orchestrator_model": config.OrchestratorConfig.MODEL_NAME,
            "orchestrator_version": config.OrchestratorConfig.VERSION,
        }

    async def get_agents_status(self) -> list[dict[str, Any]]:
        """Returns detailed list of agents with their current state."""
        cards = await self.registry.get_all_cards()
        result = []

        for agent_id, card in cards.items():
            status = await self.registry.get_status(agent_id)
            broken_reason, stuck_task_id = await self.registry.get_broken_context(agent_id)
            running_tasks = []
            for task_id in await self.registry.get_running_tasks(agent_id):
                task = await self.tasks.get_by_id(task_id)
                if task:
                    running_tasks.append(
                        {
                            "task_id": task.task_id,
                            "description": task.description,
                            "start_time": task.start_time.isoformat(),
                        }
                    )

            result.append(
                {
                    "id": agent_id,
                    "name": card.name,
                    "version": card.version,
                    "description": card.description,
                    "url": card.supported_interfaces[0].url if card.supported_interfaces else None,
                    "status": status.value,
                    "capabilities": MessageToDict(card.capabilities) if card.HasField("capabilities") else None,
                    "running_tasks": running_tasks,
                    "task_capacity": await self.registry.get_capacity(agent_id),
                    "broken_reason": broken_reason.value if broken_reason else None,
                    "stuck_task_id": stuck_task_id,
                }
            )

        return result

    async def get_recent_tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return the recent tasks without their agent logs, which the log endpoint serves."""
        tasks = await self.tasks.get_all()
        return [
            {key: value for key, value in task.to_dict().items() if key != _TASK_LOGS_KEY} for task in tasks[:limit]
        ]

    async def get_recent_errors(self, limit: int = 20) -> list[dict[str, Any]]:
        """Returns recent errors with context."""
        errors = await self.errors.get_recent(limit)
        return [error.to_dict() for error in errors]

    async def get_rag_sync_status(self) -> list[dict[str, Any]]:
        """Return durable sync outcomes without making dashboard availability depend on Qdrant."""
        service = VectorDbService(config.QdrantConfig.METADATA_COLLECTION_NAME)
        try:
            outcomes = await service.scroll_payload_records({"kind": SYNC_OUTCOME_RECORD_KIND})
            for outcome in outcomes:
                stale = False
                if outcome.get("status") == "running":
                    try:
                        stale = (
                            datetime.now(UTC) - datetime.fromisoformat(outcome["updated_at"])
                        ).total_seconds() > config.RagSyncConfig.JOB_TASK_TIMEOUT_SECONDS
                    except (KeyError, ValueError):
                        stale = True
                outcome["stale"] = stale
            return sorted(outcomes, key=lambda outcome: outcome.get("updated_at", ""), reverse=True)
        except Exception:
            logger.warning("Unable to load RAG sync outcomes for dashboard.", exc_info=True)
            return []
        finally:
            await service.close()

    async def get_logs(
        self,
        limit: int = 100,
        offset: int = 0,
        level: str | None = None,
        task_id: str | None = None,
        agent_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Returns recent application logs.

        When task_id or agent_id is provided, returns only agent execution logs
        from task artifacts. When neither is provided, returns orchestrator logs only.
        """
        result_entries: list[LogEntry] = []

        # If task_id is provided, return only agent logs from that specific task
        if task_id:
            task_record = await self.tasks.get_by_id(task_id)
            if task_record and task_record.agent_logs:
                result_entries = parse_agent_logs(task_record.agent_logs, task_id, task_record.agent_id)

        # If agent_id is provided (and no task_id), return agent logs from all tasks of this agent
        elif agent_id:
            all_tasks = await self.tasks.get_all()
            # Filter tasks for this agent
            agent_tasks = [t for t in all_tasks if t.agent_id == agent_id]
            for task in agent_tasks:  # Check all tasks for this agent
                if task.agent_logs:
                    result_entries.extend(parse_agent_logs(task.agent_logs, task.task_id, agent_id))

        # If neither task_id nor agent_id is provided, return orchestrator logs only
        else:
            result_entries = memory_log_handler.get_logs(limit=100000, offset=0, level=level)

        # Filter by level if specified and we have agent logs
        if level and (task_id or agent_id):
            level_upper = level.upper()
            result_entries = [log for log in result_entries if log.level == level_upper]

        # Sort by timestamp
        result_entries.sort(key=lambda x: x.timestamp)

        # Apply limit - take the last 'limit' items (most recent) with offset
        # result_entries is sorted oldest to newest (by timestamp sorting)
        total_logs = len(result_entries)
        if offset >= total_logs:
            return []

        end = total_logs - offset
        start = max(0, end - limit)

        sliced_logs = result_entries[start:end]

        # We need to return them reversed (newest first) to match get_logs behavior
        return [entry.to_dict() for entry in reversed(sliced_logs)]


# Global service instance
dashboard_service = OrchestratorDashboardService(registry=agent_registry, tasks=task_history, errors=error_history)
