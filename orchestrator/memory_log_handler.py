# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

"""
Custom logging handler that buffers log records in memory for the dashboard.
"""

import logging
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime


@dataclass
class LogEntry:
    """Represents a single log entry."""
    timestamp: str
    level: str
    logger_name: str
    message: str
    task_id: str | None = None
    agent_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "level": self.level,
            "logger": self.logger_name,
            "message": self.message,
            "task_id": self.task_id,
            "agent_id": self.agent_id
        }


class MemoryLogHandler(logging.Handler):
    """
    A logging handler that stores log records in a ring buffer.
    Thread-safe for use with asyncio and threading.
    """

    _instance: "MemoryLogHandler | None" = None
    _lock = threading.Lock()

    def __new__(cls, max_size: int = 50000):
        """Singleton pattern to ensure only one instance exists."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, max_size: int = 50000):
        if self._initialized:
            return
        super().__init__()
        self._buffer: deque[LogEntry] = deque(maxlen=max_size)
        self._buffer_lock = threading.Lock()
        self._initialized = True
        self.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))

    def emit(self, record: logging.LogRecord) -> None:
        """Store the log record in the buffer."""
        try:
            entry = LogEntry(
                timestamp=datetime.fromtimestamp(record.created).isoformat(),
                level=record.levelname,
                logger_name=record.name,
                message=self.format(record),
                task_id=getattr(record, "task_id", None),
                agent_id=getattr(record, "agent_id", None)
            )
            with self._buffer_lock:
                self._buffer.append(entry)
        except Exception:
            self.handleError(record)

    def get_logs(self, limit: int = 100, offset: int = 0, level: str | None = None,
                 task_id: str | None = None, agent_id: str | None = None) -> list[LogEntry]:
        """
        Get the most recent log entries.

        Args:
            limit: Maximum number of entries to return.
            level: Filter by log level (e.g., 'INFO', 'ERROR').
            task_id: Filter by task ID.
            agent_id: Filter by agent ID.

        Returns:
            List of LogEntry objects, newest first.
        """
        with self._buffer_lock:
            logs = list(self._buffer)

        # Filter by level if specified
        if level:
            level_upper = level.upper()
            logs = [log for log in logs if log.level == level_upper]

        if task_id:
            logs = [log for log in logs if log.task_id == task_id]

        if agent_id:
            logs = [log for log in logs if log.agent_id == agent_id]

        if not logs:
            return []

        # Return newest first, limited with offset
        # logs is [oldest, ..., newest]
        # with offset=0, limit=100 -> we want logs[-100:] reversed
        # with offset=100, limit=100 -> we want logs[-200:-100] reversed

        total_logs = len(logs)
        if offset >= total_logs:
            return []

        end = total_logs - offset
        start = max(0, end - limit)

        sliced_logs = logs[start:end]
        return list(reversed(sliced_logs))

    def clear(self) -> None:
        """Clear all buffered logs."""
        with self._buffer_lock:
            self._buffer.clear()


def setup_memory_logging(logger_name: str = "orchestrator") -> MemoryLogHandler:
    """
    Set up the memory log handler for a logger.

    Args:
        logger_name: Name of the logger to attach the handler to.

    Returns:
        The MemoryLogHandler instance.
    """
    handler = MemoryLogHandler()
    handler.setLevel(logging.DEBUG)

    # Attach to the specified logger
    logger = logging.getLogger(logger_name)

    # Avoid adding duplicate handlers
    if not any(isinstance(h, MemoryLogHandler) for h in logger.handlers):
        logger.addHandler(handler)

    return handler


# Global instance for easy access
memory_log_handler = MemoryLogHandler()
