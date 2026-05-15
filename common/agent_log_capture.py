# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

"""
In-memory log handler for capturing agent execution logs.

This module provides a log handler that captures log records during agent
execution and can export them as a string for inclusion in task artifacts.
"""

import logging
import threading
from collections import deque
from dataclasses import dataclass


class AgentLogCaptureHandler(logging.Handler):
    """
    A logging handler that captures log records in memory during agent execution.

    This handler is designed to be attached temporarily to a logger during agent
    task execution, then detached and its logs extracted to be returned as artifacts.
    """

    def __init__(self, max_records: int = 10000):
        super().__init__()
        self._buffer: deque[str] = deque(maxlen=max_records)
        self._lock = threading.Lock()
        self.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        """Store the formatted log record in the buffer."""
        try:
            log_entry = self.format(record)
            with self._lock:
                self._buffer.append(log_entry)
        except Exception:
            self.handleError(record)

    def get_logs(self) -> str:
        """
        Get all captured logs as a single string.

        Returns:
            All captured log entries joined by newlines.
        """
        with self._lock:
            return "\n".join(self._buffer)

    def get_logs_list(self) -> list[str]:
        """
        Get all captured logs as a list of strings.

        Returns:
            List of log entry strings.
        """
        with self._lock:
            return list(self._buffer)

    def clear(self) -> None:
        """Clear all buffered logs."""
        with self._lock:
            self._buffer.clear()


class AgentLogCapture:
    """
    Context manager for capturing logs during agent execution.

    Usage:
        with AgentLogCapture("my_agent") as capture:
            # ... agent execution code ...
            logs = capture.get_logs()
    """

    def __init__(self, logger_name: str):
        """
        Initialize the log capture context.

        Args:
            logger_name: Name of the logger to capture logs from.
        """
        self.logger_name = logger_name
        self.handler = AgentLogCaptureHandler()
        self._logger: logging.Logger | None = None

    def __enter__(self) -> "AgentLogCapture":
        """Start capturing logs."""
        import config

        self._logger = logging.getLogger(self.logger_name)
        self._logger.addHandler(self.handler)
        # Use configured log level
        self.handler.setLevel(config.LOG_LEVEL)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Stop capturing logs."""
        if self._logger:
            self._logger.removeHandler(self.handler)

    def get_logs(self) -> str:
        """Get captured logs as a string."""
        return self.handler.get_logs()

    def get_logs_list(self) -> list[str]:
        """Get captured logs as a list."""
        return self.handler.get_logs_list()

    def clear(self) -> None:
        """Clear captured logs."""
        self.handler.clear()


@dataclass(slots=True)
class RawFilePart:
    """Raw file data for use with the a2a v1.0 Part type."""

    filename: str
    raw: bytes
    media_type: str


def create_log_file_part(logs: str, agent_name: str) -> RawFilePart:
    """
    Create a FilePart containing agent execution logs.

    Args:
        logs: The log content as a string.
        agent_name: Name of the agent (used in filename).

    Returns:
        A RawFilePart containing the logs as raw bytes.
    """
    safe_name = agent_name.replace(" ", "_").lower()
    filename = f"{safe_name}_execution_logs.txt"
    return RawFilePart(filename=filename, raw=logs.encode("utf-8"), media_type="text/plain")
