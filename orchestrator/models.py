# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Core data models and state management shared by the orchestrator logic and the dashboard service, kept here to avoid
circular imports.
"""

import asyncio
from collections import deque
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from a2a.types import AgentCard

from common import utils


class AgentStatus(StrEnum):
    """Status of an agent in the registry."""

    AVAILABLE = "AVAILABLE"
    BUSY = "BUSY"
    BROKEN = "BROKEN"


class BrokenReason(StrEnum):
    """Reason why an agent is marked as BROKEN."""

    OFFLINE = "OFFLINE"  # Agent was unreachable (network error, crashed)
    TASK_STUCK = "TASK_STUCK"  # Agent is reachable but a task timed out or is stuck


class TaskStatus(StrEnum):
    """Status of a task in the history."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


def iter_log_lines(raw_logs: Iterable[str]) -> Iterator[str]:
    """Yield the non-empty lines of a task's agent logs, whose chunks may hold several lines each."""
    for chunk in raw_logs:
        for line in chunk.splitlines():
            if line.strip():
                yield line


@dataclass
class TaskRecord:
    """Record of a task for history tracking."""

    task_id: str
    agent_id: str
    agent_name: str
    description: str
    status: TaskStatus
    start_time: datetime
    end_time: datetime | None = None
    error_message: str | None = None
    agent_logs: list[str] | None = None
    current_activity: str | None = None
    token_usage: dict[str, Any] | None = None

    @property
    def duration_ms(self) -> int | None:
        """Calculate duration in milliseconds."""
        if self.end_time and self.start_time:
            return int((self.end_time - self.start_time).total_seconds() * 1000)
        return None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "description": self.description,
            "status": self.status.value,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_ms": self.duration_ms,
            "error_message": self.error_message,
            "agent_logs": self.agent_logs,
            "current_activity": self.current_activity,
            "token_usage": self.token_usage,
        }


@dataclass
class ErrorRecord:
    """Record of an error for history tracking."""

    error_id: str
    timestamp: datetime
    message: str
    task_id: str | None = None
    agent_id: str | None = None
    module: str | None = None
    traceback_snippet: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "error_id": self.error_id,
            "timestamp": self.timestamp.isoformat(),
            "message": self.message,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "module": self.module,
            "traceback_snippet": self.traceback_snippet,
        }


class TaskHistory:
    """Thread-safe ring buffer for task history."""

    def __init__(self, max_size: int = 100):
        self._tasks: deque[TaskRecord] = deque(maxlen=max_size)
        self._lock = asyncio.Lock()
        self._tasks_by_id: dict[str, TaskRecord] = {}

    async def add(self, task: TaskRecord) -> None:
        """Add a new task record."""
        async with self._lock:
            self._tasks.append(task)
            self._tasks_by_id[task.task_id] = task
        self._persist("task", task.task_id, task.to_dict())

    async def restore(self, tasks: list[TaskRecord]) -> None:
        """Merge persisted tasks with the ones this process already recorded, chronologically, without
        persisting them again (which would reset their retention)."""
        async with self._lock:
            merged = [task for task in tasks if task.task_id not in self._tasks_by_id] + list(self._tasks)
            merged.sort(key=lambda task: task.start_time)
            self._tasks = deque(merged, maxlen=self._tasks.maxlen)
            self._tasks_by_id = {task.task_id: task for task in self._tasks}

    @staticmethod
    def _persist(kind: str, record_id: str, payload: dict[str, Any]) -> None:
        """Queue dashboard persistence without coupling state mutations to Qdrant availability."""
        from orchestrator.dashboard_state import dashboard_state_store

        dashboard_state_store.enqueue(kind, {"id": record_id, "payload": payload})

    async def update(
        self, task_id: str, status: TaskStatus, end_time: datetime | None = None, error_message: str | None = None
    ) -> None:
        """Update an existing task record."""
        async with self._lock:
            if task_id in self._tasks_by_id:
                task = self._tasks_by_id[task_id]
                task.status = status
                if end_time:
                    task.end_time = end_time
                if error_message:
                    task.error_message = error_message
                self._persist("task", task_id, task.to_dict())

    async def get_all(self) -> list[TaskRecord]:
        """Get all task records, newest first."""
        async with self._lock:
            return list(reversed(self._tasks))

    async def update_logs(self, task_id: str, logs: list[str]) -> None:
        """Update task with agent logs."""
        async with self._lock:
            if task_id in self._tasks_by_id:
                task = self._tasks_by_id[task_id]
                task.agent_logs = logs
                self._persist("task", task_id, task.to_dict())

    async def update_usage(self, task_id: str, usage: dict[str, Any]) -> None:
        """Update task with the agent's token usage and estimated cost."""
        async with self._lock:
            if task_id in self._tasks_by_id:
                self._tasks_by_id[task_id].token_usage = usage
                self._persist("task", task_id, self._tasks_by_id[task_id].to_dict())

    async def get_by_id(self, task_id: str) -> TaskRecord | None:
        """Get a specific task by ID."""
        async with self._lock:
            return self._tasks_by_id.get(task_id)

    async def set_current_activity(self, task_id: str, text: str) -> None:
        """Set the live activity text for a running task."""
        async with self._lock:
            if task_id in self._tasks_by_id:
                self._tasks_by_id[task_id].current_activity = text

    async def clear_current_activity(self, task_id: str) -> None:
        """Clear the activity text when a task reaches a terminal state."""
        async with self._lock:
            if task_id in self._tasks_by_id:
                self._tasks_by_id[task_id].current_activity = None

    async def append_log_batch(self, task_id: str, lines: list[str]) -> int:
        """Append streamed log lines to the task's log buffer and return the number of its log lines before them."""
        async with self._lock:
            task = self._tasks_by_id.get(task_id)
            if task is None:
                return 0
            if task.agent_logs is None:
                task.agent_logs = []
            preceding_line_count = sum(1 for _ in iter_log_lines(task.agent_logs))
            task.agent_logs.extend(lines)
            self._persist("task", task_id, task.to_dict())
            return preceding_line_count


class ErrorHistory:
    """Thread-safe ring buffer for error history."""

    def __init__(self, max_size: int = 50):
        self._errors: deque[ErrorRecord] = deque(maxlen=max_size)
        self._lock = asyncio.Lock()

    async def add(self, error: ErrorRecord) -> None:
        """Add a new error record."""
        async with self._lock:
            self._errors.append(error)
        TaskHistory._persist("error", error.error_id, error.to_dict())

    async def restore(self, errors: list[ErrorRecord]) -> None:
        """Merge persisted errors with the ones this process already recorded, chronologically, without
        persisting them again."""
        async with self._lock:
            known_ids = {error.error_id for error in self._errors}
            merged = [error for error in errors if error.error_id not in known_ids] + list(self._errors)
            merged.sort(key=lambda error: error.timestamp)
            self._errors = deque(merged, maxlen=self._errors.maxlen)

    async def get_all(self) -> list[ErrorRecord]:
        """Get all error records, newest first."""
        async with self._lock:
            return list(reversed(self._errors))

    async def get_recent(self, limit: int = 10) -> list[ErrorRecord]:
        """Get the most recent N errors."""
        async with self._lock:
            return list(reversed(list(self._errors)[-limit:]))


TASK_CAPACITY_EXTENSION_URI = "urn:quaia:extensions:task-capacity:v1"
_TASK_CAPACITY_PARAM = "capacity"
_DEFAULT_TASK_CAPACITY = 1
# An agent's card is external input, so the capacity it declares is capped.
_MAX_TASK_CAPACITY = 32

logger = utils.get_logger("orchestrator_registry")


def task_capacity(card: AgentCard) -> int:
    """Return the number of tasks the card's capacity extension declares, or 1 when it declares no valid one."""
    for extension in card.capabilities.extensions:
        if extension.uri != TASK_CAPACITY_EXTENSION_URI:
            continue
        value = extension.params.fields.get(_TASK_CAPACITY_PARAM)
        capacity = value.number_value if value is not None and value.WhichOneof("kind") == "number_value" else None
        if capacity is not None and capacity.is_integer() and _DEFAULT_TASK_CAPACITY <= capacity <= _MAX_TASK_CAPACITY:
            return int(capacity)
        logger.warning("Agent '%s' declares an invalid task capacity; it runs one task at a time.", card.name)
    return _DEFAULT_TASK_CAPACITY


class AgentRegistry:
    """Registry of the agent cards, their statuses and their running tasks; an agent is BUSY when its running tasks reach
    the capacity its card declares.
    """

    def __init__(self):
        self._cards: dict[str, AgentCard] = {}
        self._statuses: dict[str, AgentStatus] = {}
        self._broken_reasons: dict[str, BrokenReason] = {}
        self._stuck_task_ids: dict[str, list[str]] = {}
        self._running_tasks: dict[str, list[str]] = {}
        self._capacities: dict[str, int] = {}
        self._discovery_urls: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def get_card(self, agent_id: str) -> AgentCard | None:
        async with self._lock:
            return self._cards.get(agent_id)

    async def get_name(self, agent_id: str) -> str:
        async with self._lock:
            card = self._cards.get(agent_id)
            return card.name if card else "Unknown"

    async def register(self, agent_id: str, card: AgentCard):
        async with self._lock:
            self._set_card_locked(agent_id, card)

    async def register_or_refresh(self, discovery_url: str, card: AgentCard) -> str:
        """Register a card by the reachable discovery URL without losing its state."""
        async with self._lock:
            for agent_id, url in self._discovery_urls.items():
                if url == discovery_url:
                    self._set_card_locked(agent_id, card)
                    return agent_id
            agent_id = str(uuid4())
            self._discovery_urls[agent_id] = discovery_url
            self._set_card_locked(agent_id, card)
            return agent_id

    def _set_card_locked(self, agent_id: str, card: AgentCard) -> None:
        """Store the card and its capacity, keeping a BROKEN status; the caller holds the registry lock."""
        self._cards[agent_id] = card
        self._capacities[agent_id] = task_capacity(card)
        if self._statuses.get(agent_id) != AgentStatus.BROKEN:
            self._statuses[agent_id] = self._load_status_locked(agent_id)

    def _load_status_locked(self, agent_id: str) -> AgentStatus:
        """Return BUSY when the agent runs as many tasks as its capacity allows, AVAILABLE otherwise."""
        running = len(self._running_tasks.get(agent_id, []))
        return (
            AgentStatus.BUSY
            if running >= self._capacities.get(agent_id, _DEFAULT_TASK_CAPACITY)
            else AgentStatus.AVAILABLE
        )

    async def reserve_task(self, agent_id: str, task_id: str) -> AgentCard | None:
        """Add the task to an AVAILABLE agent's running tasks and return its card, or None when the agent has no free slot."""
        async with self._lock:
            card = self._cards.get(agent_id)
            if card is None or self._statuses.get(agent_id) != AgentStatus.AVAILABLE:
                return None
            self._running_tasks.setdefault(agent_id, []).append(task_id)
            self._statuses[agent_id] = self._load_status_locked(agent_id)
            return card

    async def release_task(self, agent_id: str, task_id: str) -> None:
        """Remove the task from the agent's running tasks, freeing its slot unless the agent is BROKEN."""
        async with self._lock:
            running = self._running_tasks.get(agent_id, [])
            if task_id in running:
                running.remove(task_id)
            if agent_id in self._cards and self._statuses.get(agent_id) != AgentStatus.BROKEN:
                self._statuses[agent_id] = self._load_status_locked(agent_id)

    async def get_running_tasks(self, agent_id: str) -> list[str]:
        async with self._lock:
            return list(self._running_tasks.get(agent_id, []))

    async def get_capacity(self, agent_id: str) -> int:
        async with self._lock:
            return self._capacities.get(agent_id, _DEFAULT_TASK_CAPACITY)

    async def get_discovery_url(self, agent_id: str) -> str | None:
        """Return the URL used to reach an agent during discovery."""
        async with self._lock:
            return self._discovery_urls.get(agent_id)

    async def update_status(
        self,
        agent_id: str,
        status: AgentStatus,
        broken_reason: BrokenReason | None = None,
        stuck_task_id: str | None = None,
    ):
        async with self._lock:
            if agent_id in self._cards:
                self._statuses[agent_id] = status
                if status == AgentStatus.BROKEN and broken_reason:
                    self._broken_reasons[agent_id] = broken_reason
                    # Several tasks of an agent with a capacity above one can get stuck before its recovery.
                    if stuck_task_id and stuck_task_id not in self._stuck_task_ids.setdefault(agent_id, []):
                        self._stuck_task_ids[agent_id].append(stuck_task_id)
                elif status == AgentStatus.AVAILABLE:
                    # A recovered agent may still run other tasks, which keep their slots.
                    self._broken_reasons.pop(agent_id, None)
                    self._stuck_task_ids.pop(agent_id, None)
                    self._statuses[agent_id] = self._load_status_locked(agent_id)

    async def get_status(self, agent_id: str) -> AgentStatus:
        async with self._lock:
            return self._statuses.get(agent_id, AgentStatus.BROKEN)

    async def get_broken_context(self, agent_id: str) -> tuple[BrokenReason | None, str | None]:
        """Get the reason and stuck task ID for a broken agent."""
        async with self._lock:
            reason = self._broken_reasons.get(agent_id)
            return reason, self._last_stuck_task_id_locked(agent_id)

    async def get_stuck_task_ids(self, agent_id: str) -> list[str]:
        async with self._lock:
            return list(self._stuck_task_ids.get(agent_id, []))

    def _last_stuck_task_id_locked(self, agent_id: str) -> str | None:
        stuck_task_ids = self._stuck_task_ids.get(agent_id)
        return stuck_task_ids[-1] if stuck_task_ids else None

    async def remove(self, agent_id: str):
        async with self._lock:
            self._remove_locked(agent_id)

    async def remove_unless_busy(self, agent_id: str) -> bool:
        """Remove an agent unless it runs a task, True when it was removed, with the check under the removal's lock."""
        async with self._lock:
            if agent_id not in self._cards or self._running_tasks.get(agent_id):
                return False
            self._remove_locked(agent_id)
            return True

    def _remove_locked(self, agent_id: str) -> None:
        """Drop every trace of an agent; the caller holds the registry lock."""
        self._cards.pop(agent_id, None)
        self._statuses.pop(agent_id, None)
        self._broken_reasons.pop(agent_id, None)
        self._stuck_task_ids.pop(agent_id, None)
        self._running_tasks.pop(agent_id, None)
        self._capacities.pop(agent_id, None)
        self._discovery_urls.pop(agent_id, None)

    async def get_all_cards(self) -> dict[str, AgentCard]:
        async with self._lock:
            return self._cards.copy()

    async def is_empty(self) -> bool:
        async with self._lock:
            return not self._cards

    async def contains(self, agent_id: str) -> bool:
        async with self._lock:
            return agent_id in self._cards

    async def get_valid_agents(self) -> list[str]:
        async with self._lock:
            return [
                aid for aid, status in self._statuses.items() if status != AgentStatus.BROKEN and aid in self._cards
            ]

    async def get_available_agents(self) -> list[str]:
        """Get agents that are AVAILABLE for new tasks (not BUSY or BROKEN)."""
        async with self._lock:
            return [
                aid for aid, status in self._statuses.items() if status == AgentStatus.AVAILABLE and aid in self._cards
            ]

    async def get_agent_id_by_url(self, url: str) -> str | None:
        async with self._lock:
            for agent_id, card in self._cards.items():
                if card.supported_interfaces and card.supported_interfaces[0].url == url:
                    return agent_id
            return None

    async def get_broken_agents(self) -> dict[str, tuple[BrokenReason | None, str | None]]:
        async with self._lock:
            result = {}
            for agent_id, status in self._statuses.items():
                if status == AgentStatus.BROKEN:
                    reason = self._broken_reasons.get(agent_id)
                    task_id = self._last_stuck_task_id_locked(agent_id)
                    result[agent_id] = (reason, task_id)
            return result


# Global instances - initialized once at module load
ORCHESTRATOR_START_TIME = datetime.now(UTC)
agent_registry = AgentRegistry()
task_history = TaskHistory(max_size=10000)
error_history = ErrorHistory(max_size=50)
