# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

"""
Core data models and state management for the Orchestrator.

This module contains shared data structures used by both the main orchestrator
logic and the dashboard service, avoiding circular imports.
"""

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Any

from a2a.types import AgentCard


class AgentStatus(str, Enum):
    """Status of an agent in the registry."""
    AVAILABLE = "AVAILABLE"
    BUSY = "BUSY"
    BROKEN = "BROKEN"


class BrokenReason(str, Enum):
    """Reason why an agent is marked as BROKEN."""
    OFFLINE = "OFFLINE"  # Agent was unreachable (network error, crashed)
    TASK_STUCK = "TASK_STUCK"  # Agent is reachable but a task timed out or is stuck


class TaskStatus(str, Enum):
    """Status of a task in the history."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


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
    
    @property
    def duration_ms(self) -> int | None:
        """Calculate duration in milliseconds."""
        if self.end_time and self.start_time:
            return int((self.end_time - self.start_time).total_seconds() * 1000)
        return None
    
    def to_dict(self) -> Dict[str, Any]:
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
            "error_message": self.error_message
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
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "error_id": self.error_id,
            "timestamp": self.timestamp.isoformat(),
            "message": self.message,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "module": self.module,
            "traceback_snippet": self.traceback_snippet
        }


class TaskHistory:
    """Thread-safe ring buffer for task history."""
    
    def __init__(self, max_size: int = 100):
        self._tasks: deque[TaskRecord] = deque(maxlen=max_size)
        self._lock = asyncio.Lock()
        self._tasks_by_id: Dict[str, TaskRecord] = {}
    
    async def add(self, task: TaskRecord) -> None:
        """Add a new task record."""
        async with self._lock:
            self._tasks.append(task)
            self._tasks_by_id[task.task_id] = task
    
    async def update(self, task_id: str, status: TaskStatus, 
                     end_time: datetime | None = None,
                     error_message: str | None = None) -> None:
        """Update an existing task record."""
        async with self._lock:
            if task_id in self._tasks_by_id:
                task = self._tasks_by_id[task_id]
                task.status = status
                if end_time:
                    task.end_time = end_time
                if error_message:
                    task.error_message = error_message
    
    async def get_all(self) -> List[TaskRecord]:
        """Get all task records, newest first."""
        async with self._lock:
            return list(reversed(self._tasks))
    
    async def get_by_id(self, task_id: str) -> TaskRecord | None:
        """Get a specific task by ID."""
        async with self._lock:
            return self._tasks_by_id.get(task_id)


class ErrorHistory:
    """Thread-safe ring buffer for error history."""
    
    def __init__(self, max_size: int = 50):
        self._errors: deque[ErrorRecord] = deque(maxlen=max_size)
        self._lock = asyncio.Lock()
    
    async def add(self, error: ErrorRecord) -> None:
        """Add a new error record."""
        async with self._lock:
            self._errors.append(error)
    
    async def get_all(self) -> List[ErrorRecord]:
        """Get all error records, newest first."""
        async with self._lock:
            return list(reversed(self._errors))
    
    async def get_recent(self, limit: int = 10) -> List[ErrorRecord]:
        """Get the most recent N errors."""
        async with self._lock:
            return list(reversed(list(self._errors)[-limit:]))


class AgentRegistry:
    """Registry for managing agent cards and their statuses."""
    
    def __init__(self):
        self._cards: Dict[str, AgentCard] = {}
        self._statuses: Dict[str, AgentStatus] = {}
        self._broken_reasons: Dict[str, BrokenReason] = {}
        self._stuck_task_ids: Dict[str, str] = {}  # agent_id -> last stuck task_id
        self._current_tasks: Dict[str, str] = {}  # agent_id -> current task_id
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
            self._cards[agent_id] = card
            if agent_id not in self._statuses:
                self._statuses[agent_id] = AgentStatus.AVAILABLE

    async def update_status(
            self,
            agent_id: str,
            status: AgentStatus,
            broken_reason: BrokenReason | None = None,
            stuck_task_id: str | None = None
    ):
        async with self._lock:
            if agent_id in self._cards:
                self._statuses[agent_id] = status
                if status == AgentStatus.BROKEN and broken_reason:
                    self._broken_reasons[agent_id] = broken_reason
                    if stuck_task_id:
                        self._stuck_task_ids[agent_id] = stuck_task_id
                elif status == AgentStatus.AVAILABLE:
                    # Clear broken context when agent becomes available
                    self._broken_reasons.pop(agent_id, None)
                    self._stuck_task_ids.pop(agent_id, None)
                    self._current_tasks.pop(agent_id, None)

    async def set_current_task(self, agent_id: str, task_id: str | None):
        """Set the current task for an agent."""
        async with self._lock:
            if task_id:
                self._current_tasks[agent_id] = task_id
            else:
                self._current_tasks.pop(agent_id, None)

    async def get_current_task(self, agent_id: str) -> str | None:
        """Get the current task for an agent."""
        async with self._lock:
            return self._current_tasks.get(agent_id)

    async def get_status(self, agent_id: str) -> AgentStatus:
        async with self._lock:
            return self._statuses.get(agent_id, AgentStatus.BROKEN)

    async def get_broken_context(self, agent_id: str) -> tuple[BrokenReason | None, str | None]:
        """Get the reason and stuck task ID for a broken agent."""
        async with self._lock:
            reason = self._broken_reasons.get(agent_id)
            task_id = self._stuck_task_ids.get(agent_id)
            return reason, task_id

    async def remove(self, agent_id: str):
        async with self._lock:
            self._cards.pop(agent_id, None)
            self._statuses.pop(agent_id, None)
            self._broken_reasons.pop(agent_id, None)
            self._stuck_task_ids.pop(agent_id, None)
            self._current_tasks.pop(agent_id, None)

    async def get_all_cards(self) -> Dict[str, AgentCard]:
        async with self._lock:
            return self._cards.copy()

    async def is_empty(self) -> bool:
        async with self._lock:
            return not self._cards

    async def contains(self, agent_id: str) -> bool:
        async with self._lock:
            return agent_id in self._cards

    async def get_valid_agents(self) -> List[str]:
        async with self._lock:
            return [aid for aid, status in self._statuses.items() 
                    if status != AgentStatus.BROKEN and aid in self._cards]

    async def get_agent_id_by_url(self, url: str) -> str | None:
        async with self._lock:
            for agent_id, card in self._cards.items():
                if card.url == url:
                    return agent_id
            return None

    async def get_broken_agents(self) -> Dict[str, tuple[BrokenReason | None, str | None]]:
        async with self._lock:
            result = {}
            for agent_id, status in self._statuses.items():
                if status == AgentStatus.BROKEN:
                    reason = self._broken_reasons.get(agent_id)
                    task_id = self._stuck_task_ids.get(agent_id)
                    result[agent_id] = (reason, task_id)
            return result


# Global instances - initialized once at module load
ORCHESTRATOR_START_TIME = datetime.now()
agent_registry = AgentRegistry()
task_history = TaskHistory(max_size=100)
error_history = ErrorHistory(max_size=50)
