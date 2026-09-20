# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Orchestrator-side trigger for the RAG sync runtime (WS8).

The mode comes from configuration: job mode (a Cloud Run job is configured) starts a
job execution through the Cloud Run Admin API with the orchestrator's runtime identity,
passing the scope options and the lock token as per-execution container arguments
(never secrets). Local mode (only the local sync service URL is configured) forwards
the request and awaits the result. Neither configured: a clear error naming the
missing configuration.
"""

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx

import config
from common import utils
from common.models import SyncRequest
from common.services.sync_lock_store import SyncLockHeldError, SyncLockStore, SyncOutcomeStore, scope_key
from common.services.vector_db_service import VectorDbService

logger = utils.get_logger("rag_sync_trigger")


class SyncTriggerError(Exception):
    """The sync could not be started; carries a definitive/unconfirmed flag."""

    def __init__(self, message: str, start_confirmed: bool):
        super().__init__(message)
        self.start_confirmed = start_confirmed


@dataclass(frozen=True, slots=True)
class SyncStartResult:
    """What starting a sync produced: 202 plus the execution in job mode, the runner's answer locally."""

    status_code: int
    execution: str | None = None
    response: Any = None


class RagSyncTrigger:
    """Acquires the scope lock, then starts the sync in the configured mode."""

    def __init__(self, metadata_db: VectorDbService):
        self._metadata_db = metadata_db
        self._lock_store = SyncLockStore(
            metadata_db,
            ttl_seconds=config.RagSyncConfig.LOCK_TTL_SECONDS,
            start_allowance_seconds=config.RagSyncConfig.START_ALLOWANCE_SECONDS,
        )
        self._outcomes = SyncOutcomeStore(metadata_db)

    async def trigger(self, source: str, scope_id: str, request: SyncRequest) -> SyncStartResult:
        """Acquire the scope lock, then start the sync.

        Args:
            source: The sync source, ``jira``, ``test_cases``, ``sharepoint`` or ``confluence``.
            scope_id: The project key, drive ID or space key identifying the scope.
            request: The validated scope of the sync.

        Returns:
            The start result: 202 plus the execution name in job mode, the forwarded
            response's status and parsed JSON in local mode.

        Raises:
            SyncLockHeldError: When the scope lock is already held.
            SyncTriggerError: When no mode is configured or the start failed.
                ``start_confirmed`` False means the failure kept the lock.
        """
        token = await self.acquire(source, scope_id)
        await self._outcomes.write(scope_key(source, scope_id), "running", "Sync start requested.", sync_type=source)
        return await self.start(source, scope_id, request, token)

    async def acquire(self, source: str, scope_id: str) -> str:
        """Verifies a sync mode is configured and acquires the scope lock.

        Splitting this from :meth:`start` lets the caller hold its in-process mutex
        only around the lock acquisition, not around the (potentially long) start.

        Returns:
            The holder token of the acquired lock.

        Raises:
            SyncLockHeldError: When the scope lock is already held.
            SyncTriggerError: With ``start_confirmed=True`` when no mode is configured.
        """
        if not config.RagSyncConfig.JOB_NAME and not config.RagSyncConfig.SERVICE_URL:
            raise SyncTriggerError(
                "No RAG sync runtime is configured: set RAG_SYNC_JOB_NAME (job mode) or "
                "RAG_SYNC_SERVICE_URL (local mode).",
                start_confirmed=True,
            )

        scope = scope_key(source, scope_id)
        state = await self._lock_store.acquire(scope)
        if not state.acquired:
            lock = state.lock_info or {}
            raise SyncLockHeldError(
                f"A sync is already running for scope {scope} (started at "
                f"{lock.get('acquired_at')}, lock expires at {lock.get('expires_at')})."
            )
        return state.lock_info["holder_token"]

    async def start(self, source: str, scope_id: str, request: SyncRequest, token: str) -> SyncStartResult:
        """Starts the sync in the configured mode, holding the given lock token.

        Raises:
            SyncTriggerError: When the start failed. ``start_confirmed`` False means an
                execution may still exist, so the lock is kept for the start allowance.
        """
        scope = scope_key(source, scope_id)
        try:
            if config.RagSyncConfig.JOB_NAME:
                return await self._start_job(source, request, token)
            return await self._run_locally(source, request, token)
        except SyncTriggerError as exc:
            status = "failed" if exc.start_confirmed else "running"
            message = str(exc) if exc.start_confirmed else f"Sync start unconfirmed: {exc}"
            await self._outcomes.write(scope, status, message, sync_type=source)
            raise
        except Exception as e:
            if _is_definite_start_failure(e):
                # The Admin API rejected the request, so no execution exists: the lock
                # is released immediately instead of waiting out the start allowance.
                await self.release_on_definite_failure(source, scope_id)
                raise SyncTriggerError(
                    f"Failed to start the RAG sync for scope {scope}: {e}", start_confirmed=True
                ) from e
            # The start failed; whether an execution exists is unconfirmed. The lock is
            # kept so the start allowance can expire before a takeover.
            raise SyncTriggerError(f"Failed to start the RAG sync for scope {scope}: {e}", start_confirmed=False) from e

    async def _start_job(self, source: str, request: SyncRequest, token: str) -> SyncStartResult:
        """Starts a Cloud Run job execution with per-execution container argument overrides.

        Scope options and the lock token travel as container arguments, never secrets.
        The orchestrator's runtime identity needs ``run.jobs.runWithOverrides``.
        """
        # Deferred: the Cloud Run Admin API client is only needed in job mode, and importing it
        # costs a noticeable share of the orchestrator's start-up.
        import google.auth
        from google.cloud.run_v2 import RunJobRequest  # type: ignore[import-untyped]
        from google.cloud.run_v2.services.jobs import JobsAsyncClient  # type: ignore[import-untyped]

        credentials, _project = await asyncio.to_thread(google.auth.default)
        jobs_client = JobsAsyncClient(credentials=credentials)
        request = RunJobRequest(
            name=config.RagSyncConfig.JOB_NAME,
            overrides={
                "container_overrides": [
                    {
                        "args": [source, *request.to_cli_args(), "--lock-token", token],
                    }
                ]
            },
        )
        operation = await jobs_client.run_job(request=request)
        execution_name = operation.operation.name if operation else None
        logger.info("Started RAG sync job execution %s for scope %s.", execution_name, source)
        return SyncStartResult(status_code=202, execution=execution_name)

    async def _run_locally(self, source: str, request: SyncRequest, token: str) -> SyncStartResult:
        """Forwards the request to the local sync service and awaits the result."""
        # The lock is already held by this request, so the runner must continue under its token
        # instead of trying (and failing) to acquire the same lock again.
        payload = {**request.model_dump(exclude_none=True), "lock_token": token}
        headers = {}
        if config.INTERNAL_SERVICE_API_KEY:
            headers["X-API-Key"] = config.INTERNAL_SERVICE_API_KEY
        async with httpx.AsyncClient(timeout=config.RagSyncConfig.JOB_TASK_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{config.RagSyncConfig.SERVICE_URL}/sync/{source}", json=payload, headers=headers
            )
        if response.status_code >= 500:
            raise SyncTriggerError(
                f"The local sync service failed: {response.status_code} {response.text}", start_confirmed=False
            )
        try:
            body = response.json()
        except ValueError:
            # A proxy answering with HTML is still a definite answer from the local mode;
            # the caller must see its status, not an unconfirmed start.
            body = {"detail": response.text}
        return SyncStartResult(status_code=response.status_code, response=body)

    async def release_on_definite_failure(self, source: str, scope_id: str) -> None:
        """Releases the lock when the start definitely failed (the Admin API rejected it)."""
        scope = scope_key(source, scope_id)
        # Only the holder path releases; the orchestrator is the only writer of new locks,
        # and this lock belongs to this trigger request, so release by scope is safe here.
        lock = await self._lock_store.read(scope)
        if lock and lock.get("holder_token"):
            await self._lock_store.release(scope, lock["holder_token"])


def _is_definite_start_failure(error: Exception) -> bool:
    """True when the Cloud Run Admin API itself rejected the start (4xx class).

    Permission denied, job not found and invalid-argument errors mean no execution
    was created. Timeouts, dropped connections and 5xx responses stay unconfirmed, as do
    transport-level failures, which carry no status code at all.
    """
    from google.api_core.exceptions import GoogleAPICallError  # type: ignore[import-untyped]

    code = getattr(error, "code", None)
    return isinstance(error, GoogleAPICallError) and code is not None and 400 <= code < 500
