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

import httpx

import config
from common import utils
from common.services.sync_lock_store import SyncLockStore, SyncOutcomeStore, scope_key
from common.services.vector_db_service import VectorDbService

logger = utils.get_logger("rag_sync_trigger")


class SyncTriggerError(Exception):
    """The sync could not be started; carries a definitive/unconfirmed flag."""

    def __init__(self, message: str, start_confirmed: bool):
        super().__init__(message)
        self.start_confirmed = start_confirmed


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

    async def trigger(
        self,
        source: str,
        scope_id: str,
        runner_args: list[str],
    ):
        """Acquire the scope lock, then start the sync.

        Args:
            source: The sync source, ``jira`` or ``confluence``.
            scope_id: The project key or space key identifying the scope.
            runner_args: The runner arguments AFTER the source (e.g. ["--project-key", "PROJ"]).

        Returns:
            A dict: job mode - ``{"status_code": 202, "execution": <name>}``;
            local mode - the forwarded response's parsed JSON and status code.

        Raises:
            SyncTriggerError: When no mode is configured, the lock is held, or the
                start failed. ``start_confirmed`` False means the failure kept the lock.
        """
        token = await self.acquire(source, scope_id)
        await self._outcomes.write(scope_key(source, scope_id), "running", "Sync start requested.", sync_type=source)
        return await self.start(source, scope_id, runner_args, token)

    async def acquire(self, source: str, scope_id: str) -> str:
        """Verifies a sync mode is configured and acquires the scope lock.

        Splitting this from :meth:`start` lets the caller hold its in-process mutex
        only around the lock acquisition, not around the (potentially long) start.

        Returns:
            The holder token of the acquired lock.

        Raises:
            SyncTriggerError: With ``start_confirmed=True`` when no mode is configured
                or the scope lock is already held.
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
            raise SyncTriggerError(
                f"A sync is already running for scope {scope} (started at "
                f"{lock.get('acquired_at')}, lock expires at {lock.get('expires_at')}).",
                start_confirmed=True,
            )
        return state.lock_info["holder_token"]

    async def start(self, source: str, scope_id: str, runner_args: list[str], token: str):
        """Starts the sync in the configured mode, holding the given lock token.

        Raises:
            SyncTriggerError: When the start failed. ``start_confirmed`` False means an
                execution may still exist, so the lock is kept for the start allowance.
        """
        scope = scope_key(source, scope_id)
        try:
            if config.RagSyncConfig.JOB_NAME:
                return await self._start_job(source, runner_args, token)
            return await self._run_locally(source, runner_args, token)
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
                raise SyncTriggerError(f"Failed to start the RAG sync for scope {scope}: {e}", start_confirmed=True) from e
            # The start failed; whether an execution exists is unconfirmed. The lock is
            # kept so the start allowance can expire before a takeover.
            raise SyncTriggerError(f"Failed to start the RAG sync for scope {scope}: {e}", start_confirmed=False) from e

    async def _start_job(self, source: str, runner_args: list[str], token: str):
        """Starts a Cloud Run job execution with per-execution container argument overrides.

        Scope options and the lock token travel as container arguments, never secrets.
        The orchestrator's runtime identity needs ``run.jobs.runWithOverrides``.
        """
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
                        "args": [source, *runner_args, "--lock-token", token],
                    }
                ]
            },
        )
        operation = await jobs_client.run_job(request=request)
        execution_name = operation.operation.name if operation else None
        logger.info(f"Started RAG sync job execution {execution_name} for scope {source}.")
        return {"status_code": 202, "execution": execution_name}

    async def _run_locally(self, source: str, runner_args: list[str], token: str):
        """Forwards the request to the local sync service and awaits the result."""
        # The lock is already held by this request, so the runner must continue under its token
        # instead of trying (and failing) to acquire the same lock again.
        payload = {**self._local_payload(source, runner_args), "lock_token": token}
        headers = {}
        if config.INTERNAL_SERVICE_API_KEY:
            headers["X-API-Key"] = config.INTERNAL_SERVICE_API_KEY
        async with httpx.AsyncClient(timeout=config.RagSyncConfig.JOB_TASK_TIMEOUT_SECONDS) as client:
            response = await client.post(f"{config.RagSyncConfig.SERVICE_URL}/sync/{source}", json=payload, headers=headers)
        if response.status_code >= 500:
            raise SyncTriggerError(
                f"The local sync service failed: {response.status_code} {response.text}", start_confirmed=False
            )
        return {"status_code": response.status_code, "response": response.json()}

    @staticmethod
    def _local_payload(source: str, runner_args: list[str]) -> dict:
        """Rebuilds the local service's JSON payload from the runner arguments."""
        payload: dict = {}

        def arg(name: str) -> str | None:
            return runner_args[runner_args.index(name) + 1] if name in runner_args else None

        match source:
            case "jira":
                payload["project_key"] = arg("--project-key")
            case "confluence":
                payload["space_key"] = arg("--space-key")
                if (page_id := arg("--page-id")) is not None:
                    payload["page_id"] = int(page_id)
                if (pattern := arg("--attachment-name-pattern")) is not None:
                    payload["attachment_name_pattern"] = pattern
                if "--skip-page-body" in runner_args:
                    payload["skip_page_body"] = True
            case _:
                raise SyncTriggerError(f"Unknown sync source '{source}'.", start_confirmed=True)
        return payload

    async def release_on_definite_failure(self, source: str, scope_id: str) -> None:
        """Releases the lock when the start definitely failed (the Admin API rejected it)."""
        scope = scope_key(source, scope_id)
        # Only the holder path releases; the orchestrator is the only writer of new locks,
        # and this lock belongs to this trigger request, so release by scope is safe here.
        lock = await self._metadata_db.get_payload_record(f"sync-lock-{scope}")
        if lock and lock.get("holder_token"):
            await self._lock_store.release(scope, lock["holder_token"])


def _is_definite_start_failure(error: Exception) -> bool:
    """True when the Cloud Run Admin API itself rejected the start (4xx class).

    Permission denied, job not found and invalid-argument errors mean no execution
    was created. Timeouts, dropped connections and 5xx responses stay unconfirmed.
    """
    try:
        from google.api_core.exceptions import GoogleAPICallError  # type: ignore[import-untyped]
    except ImportError:
        return False
    return isinstance(error, GoogleAPICallError) and 400 <= error.code < 500
