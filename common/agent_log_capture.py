# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""
In-memory log handler for capturing agent execution logs.

This module provides a log handler that captures log records during agent
execution and can export them as a string for inclusion in task artifacts.
"""

import logging
import threading
from collections import deque


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
        self._drain_cursor: int = 0
        self.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        """Store the formatted log record in the buffer."""
        try:
            log_entry = self.format(record)
            with self._lock:
                self._buffer.append(log_entry)
        except Exception:
            self.handleError(record)

    def drain(self) -> list[str]:
        """Return lines appended since the last drain() and advance the cursor.

        Thread-safe. If the buffer has overflowed and old entries were dropped,
        the cursor is clamped to the current buffer length.
        """
        with self._lock:
            buffer_list = list(self._buffer)
            start = min(self._drain_cursor, len(buffer_list))
            new_items = buffer_list[start:]
            self._drain_cursor = len(buffer_list)
            return new_items
