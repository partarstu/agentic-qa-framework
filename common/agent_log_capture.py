# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""In-memory log handler that captures agent execution logs for inclusion in task artifacts."""

import logging
import threading
from collections import deque

from common.utils import StructuredJsonFormatter


class AgentLogCaptureHandler(logging.Handler):
    """A logging handler that captures log records in memory while an agent task runs."""

    def __init__(self, max_records: int = 10000):
        super().__init__()
        self._buffer: deque[str] = deque(maxlen=max_records)
        self._lock = threading.Lock()
        self._drain_cursor: int = 0
        self._emitted_total: int = 0
        self.setFormatter(StructuredJsonFormatter())

    def emit(self, record: logging.LogRecord) -> None:
        """Store the formatted log record in the buffer."""
        try:
            log_entry = self.format(record)
            with self._lock:
                self._buffer.append(log_entry)
                self._emitted_total += 1
        except Exception:
            self.handleError(record)

    def drain(self) -> list[str]:
        """Return the lines appended since the last drain and advance the cursor."""
        # Emitted records are counted by a monotonic total so draining survives an overflow of the
        # bounded buffer: the oldest lines are then unrecoverable and only the buffered tail is returned.
        with self._lock:
            new_count = self._emitted_total - self._drain_cursor
            self._drain_cursor = self._emitted_total
            if new_count <= 0:
                return []
            buf_len = len(self._buffer)
            k = min(new_count, buf_len)
            return [self._buffer[buf_len - i] for i in range(k, 0, -1)]
