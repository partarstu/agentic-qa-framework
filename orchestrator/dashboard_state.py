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
        self._rehydrated = False

    async def start(self) -> None:
        """Start best-effort writer and maintenance tasks when persistence is enabled.

        A failed initial read doesn't disable persistence: the maintenance loop retries it.
        """
        if not config.DashboardPersistenceConfig.ENABLED:
            return
        self._rehydrated = await self.rehydrate()
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

    async def rehydrate(self) -> bool:
        """Restore the persisted state within the retention windows, merged chronologically with the state
        this process already has. A task still RUNNING was interrupted by the restart: it is marked FAILED
        and persisted, so the running count stays honest.

        Returns:
            False when the store could not be read; the maintenance loop then retries.
        """
        try:
            records = await self._service.scroll_payload_records({})
        except Exception:
            logger.exception("Dashboard-state rehydration failed; the maintenance loop retries it.")
            return False
        from orchestrator.memory_log_handler import LogEntry, memory_log_handler
        from orchestrator.models import ErrorRecord, TaskRecord, TaskStatus, error_history, task_history

        cutoffs = _retention_cutoffs()
        tasks: list[TaskRecord] = []
        errors: list[ErrorRecord] = []
        logs: list[LogEntry] = []
        for record in records:
            kind, payload = record.get("kind"), record.get("payload")
            if kind not in cutoffs or not isinstance(payload, dict) or str(record.get("stored_at", "")) < cutoffs[kind]:
                continue
            try:
                if kind == "task":
                    tasks.append(
                        TaskRecord(
                            task_id=payload["task_id"],
                            agent_id=payload["agent_id"],
                            agent_name=payload["agent_name"],
                            description=payload["description"],
                            status=TaskStatus(payload["status"]),
                            start_time=_utc(payload["start_time"]),
                            end_time=_utc(payload["end_time"]) if payload.get("end_time") else None,
                            error_message=payload.get("error_message"),
                            agent_logs=payload.get("agent_logs"),
                            current_activity=payload.get("current_activity"),
                            token_usage=payload.get("token_usage"),
                        )
                    )
                elif kind == "error":
                    errors.append(
                        ErrorRecord(
                            error_id=payload["error_id"],
                            timestamp=_utc(payload["timestamp"]),
                            message=payload["message"],
                            task_id=payload.get("task_id"),
                            agent_id=payload.get("agent_id"),
                            module=payload.get("module"),
                            traceback_snippet=payload.get("traceback_snippet"),
                        )
                    )
                else:
                    logs.append(
                        LogEntry(
                            timestamp=payload["timestamp"],
                            level=payload["level"],
                            logger_name=payload["logger"],
                            message=payload["message"],
                            task_id=payload.get("task_id"),
                            agent_id=payload.get("agent_id"),
                            agent_name=payload.get("agent_name"),
                        )
                    )
            except (KeyError, TypeError, ValueError):
                logger.warning("Ignoring a malformed persisted %s record.", kind)

        for task in tasks:
            if task.status == TaskStatus.RUNNING:
                task.status = TaskStatus.FAILED
                task.end_time = datetime.now(UTC)
                task.error_message = "Task was interrupted by an orchestrator restart."
                self.enqueue("task", {"id": task.task_id, "payload": task.to_dict()})
        await task_history.restore(tasks)
        await error_history.restore(errors)
        memory_log_handler.restore(logs)
        logger.info(
            "Restored %d task(s), %d error(s) and %d log line(s) of dashboard state.",
            len(tasks),
            len(errors),
            len(logs),
        )
        return True

    async def _maintenance_loop(self) -> None:
        while True:
            await self.prune()
            if not self._rehydrated:
                self._rehydrated = await self.rehydrate()
            await asyncio.sleep(config.DashboardPersistenceConfig.MAINTENANCE_INTERVAL_SECONDS)

    async def prune(self) -> None:
        """Delete expired persisted state on every first and subsequent maintenance tick."""
        try:
            await self._service.ensure_payload_collection()
            for kind, cutoff in _retention_cutoffs().items():
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


def _retention_cutoffs() -> dict[str, str]:
    """The oldest ``stored_at`` still retained, per record kind."""
    now = datetime.now(UTC)
    log_days = config.DashboardPersistenceConfig.LOG_RETENTION_DAYS
    history_days = config.DashboardPersistenceConfig.HISTORY_RETENTION_DAYS
    return {
        "log": (now - timedelta(days=log_days)).isoformat(),
        "task": (now - timedelta(days=history_days)).isoformat(),
        "error": (now - timedelta(days=history_days)).isoformat(),
    }


def _utc(value: str) -> datetime:
    """A persisted timestamp as an aware UTC datetime; records written before WS23 carry naive ones."""
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


dashboard_state_store = DashboardStateStore()
