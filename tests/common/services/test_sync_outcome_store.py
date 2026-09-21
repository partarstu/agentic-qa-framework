# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

from unittest.mock import AsyncMock

import pytest

from common.services.sync_lock_store import SyncOutcomeStore


@pytest.mark.asyncio
async def test_outcome_write_preserves_running_start_timestamp():
    metadata = AsyncMock()
    metadata.get_payload_record.return_value = {"started_at": "2026-01-01T00:00:00+00:00"}
    store = SyncOutcomeStore(metadata)
    await store.write("jira:PROJ", "completed", "done", 2, "jira")
    payload = metadata.upsert_payload_record.await_args.args[1]
    assert payload["sync_type"] == "jira"
    assert payload["started_at"] == "2026-01-01T00:00:00+00:00"
    assert payload["processed_count"] == 2


@pytest.mark.asyncio
async def test_a_new_run_resets_the_start_timestamp():
    metadata = AsyncMock()
    metadata.get_payload_record.return_value = {"started_at": "2026-01-01T00:00:00+00:00"}
    store = SyncOutcomeStore(metadata)

    await store.write("jira:PROJ", "running", "Sync start requested.", sync_type="jira")

    payload = metadata.upsert_payload_record.await_args.args[1]
    assert payload["started_at"] == payload["updated_at"]
    assert payload["started_at"] != "2026-01-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_a_failed_outcome_write_is_swallowed():
    metadata = AsyncMock()
    metadata.upsert_payload_record.side_effect = RuntimeError("qdrant down")

    await SyncOutcomeStore(metadata).write("jira:PROJ", "completed", "done")
