# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Best-effort durable dashboard state backed by payload-only Qdrant records."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from qdrant_client import models

import config
from common import utils
from common.services.vector_db_service import VectorDbService

logger = utils.get_logger("dashboard_state")


class DashboardStateStore:
    """Batch dashboard writes so observability never adds task latency."""

    def __init__(self, service: VectorDbService | None = None, max_queue_size: int = 10_000) -> None:
        self._service = service or VectorDbService(config.DashboardPersistenceConfig.COLLECTION_NAME)
        self._queue: asyncio.Queue[tuple[str, dict]] = asyncio.Queue(maxsize=max_queue_size)
        self._writer: asyncio.Task[None] | None = None
        self._maintenance: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start best-effort writer and maintenance tasks when persistence is enabled."""
        if not config.DashboardPersistenceConfig.ENABLED:
            return
        await self.rehydrate()
        self._writer = asyncio.create_task(self._write_loop())
        self._maintenance = asyncio.create_task(self._maintenance_loop())

    def enqueue(self, kind: str, payload: dict) -> None:
        """Queue one state update, dropping the oldest entry under sustained overload."""
        if not config.DashboardPersistenceConfig.ENABLED:
            return
        item = (kind, {**payload, "kind": kind, "stored_at": datetime.now(UTC).isoformat()})
        if self._queue.full():
            self._queue.get_nowait()
            logger.warning("Dashboard persistence queue full; dropped oldest record.")
        self._queue.put_nowait(item)

    async def _write_loop(self) -> None:
        while True:
            kind, payload = await self._queue.get()
            try:
                await self._service.upsert_payload_record(f"{kind}-{payload.get('id', uuid4())}", payload)
            except Exception:
                logger.exception("Dashboard state write failed; continuing without persistence.")
            finally:
                self._queue.task_done()

    async def rehydrate(self) -> None:
        """Restore persisted state, repairing tasks interrupted by a process restart."""
        try:
            records = await self._service.scroll_payload_records({})
        except Exception:
            logger.exception("Dashboard-state rehydration failed; maintenance will retry later.")
            return
        from orchestrator.models import ErrorRecord, TaskRecord, TaskStatus, error_history, task_history

        for record in records:
            payload = record.get("payload")
            if not isinstance(payload, dict):
                continue
            if record.get("kind") == "task":
                try:
                    task = TaskRecord(
                        task_id=payload["task_id"], agent_id=payload["agent_id"], agent_name=payload["agent_name"],
                        description=payload["description"], status=TaskStatus(payload["status"]),
                        start_time=datetime.fromisoformat(payload["start_time"]),
                        end_time=datetime.fromisoformat(payload["end_time"]) if payload.get("end_time") else None,
                        error_message=payload.get("error_message"), agent_logs=payload.get("agent_logs"),
                        current_activity=payload.get("current_activity"), token_usage=payload.get("token_usage"),
                    )
                    if task.status == TaskStatus.RUNNING:
                        task.status = TaskStatus.FAILED
                        task.end_time = datetime.now(UTC)
                        task.error_message = "Task was interrupted by an orchestrator restart."
                    await task_history.add(task)
                except (KeyError, TypeError, ValueError):
                    logger.warning("Ignoring malformed persisted task record.")
            elif record.get("kind") == "error":
                try:
                    await error_history.add(
                        ErrorRecord(
                            error_id=payload["error_id"], timestamp=datetime.fromisoformat(payload["timestamp"]),
                            message=payload["message"], task_id=payload.get("task_id"), agent_id=payload.get("agent_id"),
                            module=payload.get("module"), traceback_snippet=payload.get("traceback_snippet"),
                        )
                    )
                except (KeyError, TypeError, ValueError):
                    logger.warning("Ignoring malformed persisted error record.")

    async def _maintenance_loop(self) -> None:
        while True:
            await self.prune()
            await asyncio.sleep(config.DashboardPersistenceConfig.MAINTENANCE_INTERVAL_SECONDS)

    async def prune(self) -> None:
        """Delete expired persisted state on every first and subsequent maintenance tick."""
        try:
            await self._service.ensure_payload_collection()
            now = datetime.now(UTC)
            for kind, days in (
                ("log", config.DashboardPersistenceConfig.LOG_RETENTION_DAYS),
                ("task", config.DashboardPersistenceConfig.HISTORY_RETENTION_DAYS),
                ("error", config.DashboardPersistenceConfig.HISTORY_RETENTION_DAYS),
            ):
                cutoff = (now - timedelta(days=days)).isoformat()
                await self._service.delete_by_filter(
                    models.Filter(
                        must=[
                            models.FieldCondition(key="kind", match=models.MatchValue(value=kind)),
                            models.FieldCondition(key="stored_at", range=models.DatetimeRange(lt=cutoff)),
                        ]
                    )
                )
        except Exception:
            logger.exception("Dashboard-state maintenance could not reach Qdrant.")

    async def close(self) -> None:
        """Cancel background work and close the payload-only service."""
        for task in (self._writer, self._maintenance):
            if task is not None:
                task.cancel()
        await asyncio.gather(
            *(task for task in (self._writer, self._maintenance) if task is not None), return_exceptions=True
        )
        await self._service.close()


dashboard_state_store = DashboardStateStore()
