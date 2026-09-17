# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

from unittest.mock import AsyncMock

import pytest

import config
from orchestrator.dashboard_state import DashboardStateStore


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
