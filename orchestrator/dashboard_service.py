# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""
Dashboard service for aggregating orchestrator state for the Web UI.
"""

import re
from datetime import datetime
from typing import Any

from google.protobuf.json_format import MessageToDict

import config
from common import utils
from orchestrator.memory_log_handler import LogEntry, memory_log_handler
from orchestrator.models import (
    ORCHESTRATOR_START_TIME,
    AgentRegistry,
    AgentStatus,
    ErrorHistory,
    TaskHistory,
    agent_registry,
    error_history,
    task_history,
)

logger = utils.get_logger("orchestrator_dashboard")

# Uppercase log-level tokens used as a fallback for agent log formats that don't match the
# Python logging layout (e.g. the logback/SLF4J format "HH:mm:ss.SSS LEVEL Logger - message"
# emitted by the UI agent). Matching is case-sensitive on purpose so a lowercase "error"
# inside a JSON payload is not mistaken for an ERROR-level line.
_LEVEL_TOKEN_PATTERN = re.compile(r"\b(CRITICAL|FATAL|ERROR|WARNING|WARN|INFO|DEBUG|TRACE)\b")
_LEVEL_ALIASES = {"WARN": "WARNING", "FATAL": "CRITICAL"}


def _detect_log_level(line: str) -> str | None:
    """Return the first recognised uppercase log-level token in a line, normalising aliases."""
    match = _LEVEL_TOKEN_PATTERN.search(line)
    if match is None:
        return None
    token = match.group(1)
    return _LEVEL_ALIASES.get(token, token)


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
        uptime_seconds = int((datetime.now() - ORCHESTRATOR_START_TIME).total_seconds())

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
            "current_time": datetime.now().isoformat(),
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
            current_task_id = await self.registry.get_current_task(agent_id)

            # Get current task details if available
            current_task_info = None
            if current_task_id:
                task = await self.tasks.get_by_id(current_task_id)
                if task:
                    current_task_info = {
                        "task_id": task.task_id,
                        "description": task.description,
                        "start_time": task.start_time.isoformat(),
                    }

            result.append(
                {
                    "id": agent_id,
                    "name": card.name,
                    "version": card.version,
                    "description": card.description,
                    "url": card.supported_interfaces[0].url if card.supported_interfaces else None,
                    "status": status.value,
                    "capabilities": MessageToDict(card.capabilities) if card.HasField("capabilities") else None,
                    "current_task": current_task_info,
                    "broken_reason": broken_reason.value if broken_reason else None,
                    "stuck_task_id": stuck_task_id,
                }
            )

        return result

    async def get_recent_tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        """Returns recent tasks with their details."""
        tasks = await self.tasks.get_all()
        return [task.to_dict() for task in tasks[:limit]]

    async def get_recent_errors(self, limit: int = 20) -> list[dict[str, Any]]:
        """Returns recent errors with context."""
        errors = await self.errors.get_recent(limit)
        return [error.to_dict() for error in errors]

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
                result_entries = self._parse_agent_logs(task_record.agent_logs, task_id, task_record.agent_id)

        # If agent_id is provided (and no task_id), return agent logs from all tasks of this agent
        elif agent_id:
            all_tasks = await self.tasks.get_all()
            # Filter tasks for this agent
            agent_tasks = [t for t in all_tasks if t.agent_id == agent_id]
            for task in agent_tasks:  # Check all tasks for this agent
                if task.agent_logs:
                    result_entries.extend(self._parse_agent_logs(task.agent_logs, task.task_id, agent_id))

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

    @staticmethod
    def _parse_agent_logs(raw_logs: list[str], task_id: str, agent_id: str) -> list[LogEntry]:
        """Parse raw agent log strings into LogEntry objects.

        The expected log format from AgentLogCaptureHandler is:
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        Example: '2026-01-06 16:20:30,123 - my_agent - INFO - Some message'
        """
        entries = []
        for log_chunk in raw_logs:
            # Agent logs might be one big string or lines
            lines = log_chunk.splitlines()
            for line in lines:
                if not line.strip():
                    continue

                # Default values in case parsing fails
                timestamp = None
                level = "INFO"
                logger_name = f"agent.{agent_id}"
                message = line

                # Parse the log format: "timestamp - logger - level - message"
                parts = line.split(" - ", 3)
                if len(parts) >= 4:
                    # Full format: timestamp - logger - level - message
                    raw_timestamp, parsed_logger, parsed_level, parsed_message = parts

                    # Try to parse the timestamp
                    try:
                        # Format from logging: "2026-01-06 16:20:30,123"
                        parsed_dt = datetime.strptime(raw_timestamp.strip(), "%Y-%m-%d %H:%M:%S,%f")
                        timestamp = parsed_dt.isoformat()
                    except ValueError:
                        # Fallback: try without milliseconds
                        try:
                            parsed_dt = datetime.strptime(raw_timestamp.strip(), "%Y-%m-%d %H:%M:%S")
                            timestamp = parsed_dt.isoformat()
                        except ValueError:
                            # Keep the raw timestamp string if parsing fails
                            timestamp = raw_timestamp.strip()

                    logger_name = parsed_logger.strip()
                    level = parsed_level.strip().upper()
                    message = parsed_message
                else:
                    # Formats that don't match the Python logging layout (e.g. the UI agent's
                    # logback format): fall back to scanning the line for a level token.
                    detected_level = _detect_log_level(line)
                    if detected_level is not None:
                        level = detected_level

                # If timestamp parsing failed completely, use empty string as fallback
                if timestamp is None:
                    timestamp = ""

                entries.append(
                    LogEntry(
                        timestamp=timestamp,
                        level=level,
                        logger_name=logger_name,
                        message=message,
                        task_id=task_id,
                        agent_id=agent_id,
                    )
                )
        return entries


# Global service instance
dashboard_service = OrchestratorDashboardService(registry=agent_registry, tasks=task_history, errors=error_history)
