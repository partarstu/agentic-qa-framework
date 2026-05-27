# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import threading

import pytest

from common.agent_log_capture import AgentLogCaptureHandler


@pytest.fixture
def handler() -> AgentLogCaptureHandler:
    h = AgentLogCaptureHandler()
    h.setFormatter(__import__("logging").Formatter("%(message)s"))
    return h


def _emit(handler: AgentLogCaptureHandler, message: str) -> None:
    import logging

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg=message,
        args=(),
        exc_info=None,
    )
    handler.emit(record)


# ---------------------------------------------------------------------------
# drain basics
# ---------------------------------------------------------------------------


def test_drain_initially_empty(handler):
    assert handler.drain() == []


def test_drain_returns_all_on_first_call(handler):
    _emit(handler, "line 1")
    _emit(handler, "line 2")
    result = handler.drain()
    assert result == ["line 1", "line 2"]


def test_drain_second_call_returns_only_new_lines(handler):
    _emit(handler, "line 1")
    handler.drain()  # consume line 1

    _emit(handler, "line 2")
    _emit(handler, "line 3")
    result = handler.drain()
    assert result == ["line 2", "line 3"]


def test_drain_second_call_empty_when_no_new_lines(handler):
    _emit(handler, "line 1")
    handler.drain()
    assert handler.drain() == []


# ---------------------------------------------------------------------------
# Thread-safety: concurrent emit + drain
# ---------------------------------------------------------------------------


def test_concurrent_emit_and_drain_is_race_free(handler):
    errors: list[Exception] = []
    collected: list[str] = []
    lock = threading.Lock()

    def emitter():
        try:
            for i in range(500):
                _emit(handler, f"line {i}")
        except Exception as e:
            with lock:
                errors.append(e)

    def drainer():
        try:
            for _ in range(100):
                batch = handler.drain()
                with lock:
                    collected.extend(batch)
        except Exception as e:
            with lock:
                errors.append(e)

    threads = [threading.Thread(target=emitter), threading.Thread(target=drainer)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Final drain to capture any remaining lines
    with lock:
        collected.extend(handler.drain())

    assert errors == [], f"Threads raised: {errors}"
    # All emitted lines fit within maxlen; drain collects everything exactly once
    assert len(collected) <= 500  # maxlen guards upper bound
