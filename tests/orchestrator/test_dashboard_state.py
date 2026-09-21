# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import asyncio
from collections import deque
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import config
from orchestrator.dashboard_state import DashboardStateStore
from orchestrator.memory_log_handler import LogEntry, MemoryLogHandler
from orchestrator.models import ErrorHistory, ErrorRecord, TaskHistory, TaskRecord, TaskStatus


@pytest.mark.asyncio
async def test_enqueue_writes_payload_only_record(monkeypatch):
    """Persist accepted state through metadata records without embeddings."""
    monkeypatch.setattr(config.DashboardPersistenceConfig, "ENABLED", True)
    service = AsyncMock()
    store = DashboardStateStore(service)
    store.enqueue("log", {"id": "log-1", "payload": {"message": "accepted"}})
    writer = __import__("asyncio").create_task(store._write_loop())
    await store._queue.join()
    writer.cancel()
    service.upsert_payload_record.assert_awaited_once()


@pytest.mark.asyncio
async def test_prune_tolerates_storage_failure():
    """Maintenance failures must not escape into orchestrator execution."""
    service = AsyncMock()
    service.ensure_payload_collection.side_effect = RuntimeError("offline")
    store = DashboardStateStore(service)
    await store.prune()


def _stored(kind: str, payload: dict, age: timedelta = timedelta(minutes=5)) -> dict:
    return {"kind": kind, "payload": payload, "stored_at": (datetime.now(UTC) - age).isoformat()}


def _task_payload(task_id: str, status: str, start: datetime) -> dict:
    return {
        "task_id": task_id,
        "agent_id": "agent-1",
        "agent_name": "Agent 1",
        "description": f"Task {task_id}",
        "status": status,
        "start_time": start.isoformat(),
        "end_time": None,
    }


def _log_payload(timestamp: datetime, message: str) -> dict:
    return {
        "timestamp": timestamp.isoformat(),
        "level": "INFO",
        "logger": "orchestrator",
        "message": message,
        "agent_name": "Agent 1",
    }


@pytest.fixture
def fresh_state(monkeypatch):
    """Empty in-memory histories, so rehydration is observable in isolation."""
    monkeypatch.setattr(config.DashboardPersistenceConfig, "ENABLED", True)
    tasks, errors, log_handler = TaskHistory(max_size=10), ErrorHistory(max_size=10), MagicMock()
    with (
        patch("orchestrator.models.task_history", tasks),
        patch("orchestrator.models.error_history", errors),
        patch("orchestrator.memory_log_handler.memory_log_handler", log_handler),
    ):
        yield tasks, errors, log_handler


class TestRehydrate:
    @pytest.mark.asyncio
    async def test_restores_tasks_oldest_first_and_repairs_the_interrupted_ones(self, fresh_state):
        tasks, _, _ = fresh_state
        now = datetime.now(UTC)
        service = AsyncMock()
        service.scroll_payload_records.return_value = [
            _stored("task", _task_payload("newer", "RUNNING", now - timedelta(minutes=1))),
            _stored("task", _task_payload("older", "COMPLETED", now - timedelta(minutes=10))),
        ]
        store = DashboardStateStore(service)

        assert await store.rehydrate() is True

        restored = await tasks.get_all()
        assert [task.task_id for task in restored] == ["newer", "older"]  # newest first
        assert restored[0].status == TaskStatus.FAILED
        assert "interrupted by an orchestrator restart" in restored[0].error_message
        # Only the repaired task is written back; re-writing the others would reset their retention.
        assert [payload["id"] for _, payload in list(store._queue._queue)] == ["newer"]

    @pytest.mark.asyncio
    async def test_skips_records_older_than_their_retention_window(self, fresh_state, monkeypatch):
        tasks, _, log_handler = fresh_state
        monkeypatch.setattr(config.DashboardPersistenceConfig, "LOG_RETENTION_DAYS", 1)
        monkeypatch.setattr(config.DashboardPersistenceConfig, "HISTORY_RETENTION_DAYS", 7)
        now = datetime.now(UTC)
        service = AsyncMock()
        service.scroll_payload_records.return_value = [
            _stored("log", _log_payload(now, "fresh")),
            _stored("log", _log_payload(now, "expired"), age=timedelta(days=2)),
            _stored("task", _task_payload("kept", "COMPLETED", now), age=timedelta(days=2)),
            _stored("task", _task_payload("expired", "COMPLETED", now), age=timedelta(days=8)),
        ]

        await DashboardStateStore(service).rehydrate()

        assert [task.task_id for task in await tasks.get_all()] == ["kept"]
        restored_logs = log_handler.restore.call_args.args[0]
        assert [entry.message for entry in restored_logs] == ["fresh"]
        assert restored_logs[0].agent_name == "Agent 1"

    @pytest.mark.asyncio
    async def test_a_naive_stored_at_at_the_retention_boundary_is_kept(self, fresh_state, monkeypatch):
        """Pre- records carry naive timestamps, whose ISO string is a prefix of the aware cutoff's.

        Compared as strings, the shorter one always sorts first, so a record exactly at the
        boundary — not older than it — was discarded as expired.
        """
        _, _, log_handler = fresh_state
        monkeypatch.setattr(config.DashboardPersistenceConfig, "LOG_RETENTION_DAYS", 1)
        now = datetime.now(UTC)
        at_the_cutoff = _stored("log", _log_payload(now, "naive at the boundary"))
        at_the_cutoff["stored_at"] = (now - timedelta(days=1)).replace(tzinfo=None).isoformat()
        service = AsyncMock()
        service.scroll_payload_records.return_value = [at_the_cutoff]

        with patch("orchestrator.dashboard_state.datetime") as clock:
            clock.now.return_value = now
            clock.fromisoformat = datetime.fromisoformat
            await DashboardStateStore(service).rehydrate()

        assert [entry.message for entry in log_handler.restore.call_args.args[0]] == ["naive at the boundary"]

    @pytest.mark.asyncio
    async def test_a_failed_read_is_retried_by_the_maintenance_loop(self, fresh_state, monkeypatch):
        monkeypatch.setattr(config.DashboardPersistenceConfig, "MAINTENANCE_INTERVAL_SECONDS", 0)
        service = AsyncMock()
        service.scroll_payload_records.side_effect = [RuntimeError("offline"), []]
        store = DashboardStateStore(service)

        await store.start()
        assert store._rehydrated is False
        for _ in range(5):
            await asyncio.sleep(0)
        await store.close()

        assert store._rehydrated is True
        # Pruning ran on the first maintenance tick, before the retried read.
        service.ensure_payload_collection.assert_awaited()


@pytest.mark.asyncio
async def test_task_history_restore_merges_chronologically_with_live_tasks():
    history = TaskHistory(max_size=10)
    now = datetime.now(UTC)
    live = TaskRecord("live", "a", "A", "live task", TaskStatus.RUNNING, now)
    await history.add(live)
    restored = TaskRecord("old", "a", "A", "old task", TaskStatus.COMPLETED, now - timedelta(hours=1))

    await history.restore([restored, live])

    assert [task.task_id for task in await history.get_all()] == ["live", "old"]
    assert await history.get_by_id("old") is restored


@pytest.mark.asyncio
async def test_error_history_restore_merges_chronologically_with_live_errors():
    history = ErrorHistory(max_size=10)
    now = datetime.now(UTC)
    live = ErrorRecord("live", now, "live error")
    await history.add(live)

    await history.restore([ErrorRecord("old", now - timedelta(hours=1), "old error"), live])

    assert [error.error_id for error in await history.get_all()] == ["live", "old"]


def test_log_restore_keeps_the_newest_lines_in_chronological_order():
    handler = MemoryLogHandler()
    original = handler._buffer
    handler._buffer = deque([LogEntry("2026-01-01T00:00:03+00:00", "INFO", "boot", "boot line")], maxlen=2)
    try:
        handler.restore(
            [
                LogEntry("2026-01-01T00:00:01+00:00", "INFO", "old", "oldest"),
                LogEntry("2026-01-01T00:00:02+00:00", "INFO", "old", "older"),
            ]
        )
        assert [entry.message for entry in handler._buffer] == ["older", "boot line"]
    finally:
        handler._buffer = original
