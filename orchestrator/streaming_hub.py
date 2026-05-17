# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

"""
Streaming hub for broadcasting SSE events to dashboard subscribers.

Started and stopped via the FastAPI lifespan. Publish methods are called from
the chunk-handling loop in _send_task_to_agent_with_message.
"""

import asyncio
from typing import AsyncIterator

from common import utils
from common.streaming import GapEvent

logger = utils.get_logger("streaming_hub")

_QUEUE_MAXSIZE = 256


class StreamingHub:
    """Pub/sub hub for global and per-agent SSE streams.

    Each subscriber gets a bounded asyncio.Queue. agent_activity events are
    coalesced in-place per task_id; overflow of non-coalesced types yields a
    single GapEvent sentinel instead of a silent drop.
    """

    def __init__(self) -> None:
        self._global_queues: list[asyncio.Queue] = []
        self._agent_queues: dict[str, list[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()
        self._seq: int = 0

    async def subscribe_global(self) -> AsyncIterator[dict]:
        """Yield events published to the global stream until the generator is cancelled."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        async with self._lock:
            self._global_queues.append(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            async with self._lock:
                try:
                    self._global_queues.remove(queue)
                except ValueError:
                    pass

    async def subscribe_agent(self, agent_id: str) -> AsyncIterator[dict]:
        """Yield events published for a specific agent until the generator is cancelled."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        async with self._lock:
            self._agent_queues.setdefault(agent_id, []).append(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            async with self._lock:
                queues = self._agent_queues.get(agent_id, [])
                try:
                    queues.remove(queue)
                except ValueError:
                    pass

    async def publish_global(self, event: dict) -> None:
        """Publish an event to all global subscribers."""
        async with self._lock:
            seq = self._seq
            self._seq += 1
            queues = list(self._global_queues)
        for queue in queues:
            self._put_to_queue(queue, event, seq)

    async def publish_agent(self, agent_id: str, event: dict) -> None:
        """Publish an event to all subscribers for a specific agent."""
        async with self._lock:
            seq = self._seq
            self._seq += 1
            queues = list(self._agent_queues.get(agent_id, []))
        for queue in queues:
            self._put_to_queue(queue, event, seq)

    def _put_to_queue(self, queue: asyncio.Queue, event: dict, seq: int) -> None:
        """Put an event into a subscriber queue.

        For agent_activity events, replace any existing entry for the same task_id
        in-place (coalescing). For all other types, emit a GapEvent if the queue is
        full rather than silently dropping.
        """
        if event.get("type") == "agent_activity" and event.get("task_id"):
            task_id = event["task_id"]
            inner = queue._queue  # type: ignore[attr-defined]  # collections.deque
            for i, item in enumerate(inner):
                if item.get("type") == "agent_activity" and item.get("task_id") == task_id:
                    inner[i] = event
                    return

        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            gap = GapEvent(reason="queue_overflow", since=seq, until=seq).model_dump()
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                queue.put_nowait(gap)
            except asyncio.QueueFull:
                logger.warning("Gap sentinel also dropped for a stuck subscriber (seq=%d).", seq)

    async def shutdown(self) -> None:
        """Drain all subscriber queues on lifespan shutdown."""
        async with self._lock:
            all_queues = list(self._global_queues) + [
                q for qs in self._agent_queues.values() for q in qs
            ]
        for queue in all_queues:
            while not queue.empty():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    break


streaming_hub = StreamingHub()
