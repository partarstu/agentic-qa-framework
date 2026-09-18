# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""
Custom logging handler that buffers log records in memory for the dashboard.
"""

import logging
import threading
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime

from common.utils import StructuredJsonFormatter


@dataclass
class LogEntry:
    """Represents a single log entry."""

    timestamp: str
    level: str
    logger_name: str
    message: str
    task_id: str | None = None
    agent_id: str | None = None
    agent_name: str | None = None

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "level": self.level,
            "logger": self.logger_name,
            "message": self.message,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
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
        self.setFormatter(StructuredJsonFormatter())

    def emit(self, record: logging.LogRecord) -> None:
        """Store the log record in the buffer."""
        try:
            entry = LogEntry(
                timestamp=datetime.fromtimestamp(record.created, UTC).isoformat(),
                level=record.levelname,
                logger_name=record.name,
                message=record.getMessage(),
                task_id=getattr(record, "task_id", None),
                agent_id=getattr(record, "agent_id", None),
                agent_name=getattr(record, "agent_name", None),
            )
            with self._buffer_lock:
                self._buffer.append(entry)
            from orchestrator.dashboard_state import dashboard_state_store

            # Log lines are never updated, so each one gets a fresh record id from the store.
            dashboard_state_store.enqueue("log", {"payload": entry.to_dict()})
        except Exception:
            self.handleError(record)

    def restore(self, entries: list[LogEntry]) -> None:
        """Merge persisted log lines with the lines of this process chronologically, so the restored history
        does not push the fresh boot sequence out of the fixed-size buffer."""
        with self._buffer_lock:
            merged = sorted([*entries, *self._buffer], key=lambda entry: entry.timestamp)
            self._buffer = deque(merged, maxlen=self._buffer.maxlen)

    def get_logs(
        self,
        limit: int = 100,
        offset: int = 0,
        level: str | None = None,
    ) -> list[LogEntry]:
        """
        Get the most recent log entries.

        Args:
            limit: Maximum number of entries to return.
            offset: Number of entries (from the newest) to skip.
            level: Filter by log level (e.g., 'INFO', 'ERROR').

        Returns:
            List of LogEntry objects, newest first.
        """
        with self._buffer_lock:
            logs = list(self._buffer)

        if level:
            level_upper = level.upper()
            logs = [log for log in logs if log.level == level_upper]

        if not logs:
            return []

        total_logs = len(logs)
        if offset >= total_logs:
            return []

        end = total_logs - offset
        start = max(0, end - limit)

        return list(reversed(logs[start:end]))


class _NoiseFilter(logging.Filter):
    """Exclude high-volume library loggers from the in-memory dashboard buffer."""

    _EXCLUDED_PREFIXES = ("uvicorn.access", "httpx", "hpack", "h11", "httpcore", "anyio")

    def filter(self, record: logging.LogRecord) -> bool:
        return not any(record.name.startswith(p) for p in self._EXCLUDED_PREFIXES)


def setup_memory_logging() -> MemoryLogHandler:
    """
    Set up the memory log handler on the root logger to capture all application logs.

    Returns:
        The MemoryLogHandler instance.
    """
    handler = MemoryLogHandler()
    handler.setLevel(logging.DEBUG)

    root_logger = logging.getLogger()
    if not any(isinstance(h, MemoryLogHandler) for h in root_logger.handlers):
        handler.addFilter(_NoiseFilter())
        root_logger.addHandler(handler)

    return handler


# Global instance for easy access
memory_log_handler = MemoryLogHandler()
