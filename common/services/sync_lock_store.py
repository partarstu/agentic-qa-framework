# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Scope locks and sync state stored in the Qdrant metadata collection (WS8).

One running sync per scope: ``jira:<project>`` or ``confluence:<space>``. There is no
atomic conditional write in Qdrant; the store relies on the orchestrator running as a
single instance (its acquisition path is serialized by an in-process mutex) and on the
TTL being longer than the job's task timeout.
"""

import secrets
import time
from datetime import UTC, datetime

from common import utils
from common.services.vector_db_service import VectorDbService

logger = utils.get_logger("sync_lock_store")

LOCK_RECORD_KIND = "sync-lock"
SYNC_STATE_RECORD_KIND = "sync-state"
SYNC_OUTCOME_RECORD_KIND = "sync-outcome"


def scope_key(source: str, scope_id: str) -> str:
    """Builds the canonical lock/scope key, e.g. ``jira:PROJ`` or ``confluence:DEV``."""
    return f"{source}:{scope_id}"


def _record_id(record_kind: str, scope: str) -> str:
    return f"{record_kind}-{scope}"


class LockState:
    """Outcome of one lock acquisition attempt."""

    def __init__(self, acquired: bool, lock_info: dict | None = None):
        self.acquired = acquired
        self.lock_info = lock_info


class SyncLockStore:
    """Acquire, verify and release per-scope sync locks in the metadata collection.

    A lock record holds a random holder token, the scope, the acquisition time, the
    expiry and whether a runner has started. A missing, expired or unclaimed-within-
    the-start-allowance record can be taken over; a live record cannot.
    """

    def __init__(self, metadata_db: VectorDbService, ttl_seconds: int, start_allowance_seconds: int):
        self._metadata_db = metadata_db
        self._ttl_seconds = ttl_seconds
        self._start_allowance_seconds = start_allowance_seconds

    async def acquire(self, scope: str) -> LockState:
        """Acquire the scope lock, or report the live lock that holds it.

        An in-process mutex (held by the caller, the orchestrator) serializes
        acquisitions; this method performs the check-then-write against the store.
        """
        existing = await self._read_lock(scope)
        now = time.time()
        if existing and not self._is_takeable(existing, now):
            return LockState(acquired=False, lock_info=existing)
        token = secrets.token_urlsafe(32)
        record = {
            "kind": LOCK_RECORD_KIND,
            "scope": scope,
            "holder_token": token,
            "acquired_at": now,
            "expires_at": now + self._ttl_seconds,
            "started": False,
        }
        await self._metadata_db.upsert_payload_record(_record_id(LOCK_RECORD_KIND, scope), record)
        return LockState(acquired=True, lock_info=record)

    def _is_takeable(self, lock: dict, now: float) -> bool:
        """A lock is takeable when it expired, or when no runner started within the allowance."""
        if lock.get("expires_at", 0) <= now:
            return True
        acquired_at = lock.get("acquired_at", 0)
        return not lock.get("started", False) and (now - acquired_at) >= self._start_allowance_seconds

    async def is_holder(self, scope: str, token: str) -> bool:
        """Whether ``token`` still owns the lock (checked before every write batch)."""
        lock = await self._read_lock(scope)
        return bool(lock) and lock.get("holder_token") == token

    async def mark_started(self, scope: str, token: str) -> bool:
        """The runner confirms it holds the lock and extends the expiry to now + TTL.

        Time spent waiting for the job to start doesn't shorten the lock.
        """
        if not await self.is_holder(scope, token):
            return False
        lock = await self._read_lock(scope)
        lock["started"] = True
        lock["expires_at"] = time.time() + self._ttl_seconds
        await self._metadata_db.upsert_payload_record(_record_id(LOCK_RECORD_KIND, scope), lock)
        return True

    async def release(self, scope: str, token: str) -> bool:
        """Release the lock, but only while still holding it."""
        if not await self.is_holder(scope, token):
            return False
        await self._metadata_db.delete_payload_record(_record_id(LOCK_RECORD_KIND, scope))
        return True

    async def _read_lock(self, scope: str) -> dict | None:
        return await self._metadata_db.get_payload_record(_record_id(LOCK_RECORD_KIND, scope))


class SyncStateStore:
    """Per-scope sync state: the cursor (last successful run) and its counters.

    The cursor is written only when a run finishes without item failures. Jira uses it
    for incremental fetching; Confluence records it but decides skips on version
    numbers and content hashes (WS9).
    """

    def __init__(self, metadata_db: VectorDbService):
        self._metadata_db = metadata_db

    async def get_cursor(self, scope: str) -> dict | None:
        return await self._metadata_db.get_payload_record(_record_id(SYNC_STATE_RECORD_KIND, scope))

    async def save_cursor(self, scope: str, cursor: dict) -> None:
        record = {"kind": SYNC_STATE_RECORD_KIND, "scope": scope, **cursor}
        await self._metadata_db.upsert_payload_record(_record_id(SYNC_STATE_RECORD_KIND, scope), record)

    async def reset(self, scope: str) -> None:
        await self._metadata_db.delete_payload_record(_record_id(SYNC_STATE_RECORD_KIND, scope))


class SyncOutcomeStore:
    """Persist reporting-only status for the most recent sync of each scope."""

    def __init__(self, metadata_db: VectorDbService):
        self._metadata_db = metadata_db

    async def write(
        self, scope: str, status: str, message: str, processed_count: int = 0, sync_type: str | None = None
    ) -> None:
        """Write an outcome while leaving sync behaviour untouched on storage failures."""
        now = datetime.now(UTC).isoformat()
        try:
            existing = await self._metadata_db.get_payload_record(_record_id(SYNC_OUTCOME_RECORD_KIND, scope))
            await self._metadata_db.upsert_payload_record(
                _record_id(SYNC_OUTCOME_RECORD_KIND, scope),
                {
                    "kind": SYNC_OUTCOME_RECORD_KIND,
                    "scope": scope,
                    "sync_type": sync_type or scope.split(":", 1)[0],
                    "status": status,
                    "message": message,
                    "processed_count": processed_count,
                    "updated_at": now,
                    # A new run starts with "running"; its terminal write keeps that run's start time.
                    "started_at": now if status == "running" else (existing or {}).get("started_at", now),
                },
            )
        except Exception:
            # Dashboard visibility must never convert a successful sync into a failure.
            logger.exception("Unable to persist sync outcome for %s.", scope)
