# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Best-effort terminal reporting for RAG sync runs."""

from datetime import UTC, datetime

import httpx

import config
from common import utils
from common.models import RagUpdateResult, SyncOutcome
from common.services.sync_lock_store import SyncOutcomeStore, scope_key
from common.services.vector_db_service import VectorDbService

logger = utils.get_logger("sync_outcome_reporting")


async def report_terminal_outcome(
    sync_type: str, scope_id: str, result: RagUpdateResult | None = None, error: Exception | None = None
) -> None:
    """Persist and optionally callback terminal status without changing the sync outcome."""
    # The runners report partial success as "completed-with-errors"; anything but a clean completion counts as such.
    status = "failed" if error else "completed_with_errors" if result and result.status != "completed" else "completed"
    outcome = SyncOutcome(
        sync_type=sync_type,
        scope=scope_key(sync_type, scope_id),
        status=status,
        processed_count=result.processed_count if result else 0,
        message=str(error) if error else result.status if result else "Sync completed.",
        updated_at=datetime.now(UTC).isoformat(),
    )
    service = VectorDbService(config.QdrantConfig.METADATA_COLLECTION_NAME)
    try:
        try:
            await SyncOutcomeStore(service).write(
                outcome.scope, outcome.status, outcome.message, outcome.processed_count, outcome.sync_type
            )
        except Exception:
            logger.exception("Unable to persist sync outcome.")
    finally:
        try:
            await service.close()
        except Exception:
            logger.exception("Unable to close sync outcome metadata client.")
    if not config.RagSyncConfig.CALLBACK_URL:
        return
    try:
        headers = {"X-API-Key": config.OrchestratorConfig.API_KEY or ""}
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(config.RagSyncConfig.CALLBACK_URL, json=outcome.model_dump(), headers=headers)
            response.raise_for_status()
    except Exception:
        logger.exception("Unable to report sync outcome callback.")
