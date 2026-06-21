# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""
Streaming hub for broadcasting SSE events to dashboard subscribers.

Started and stopped via the FastAPI lifespan. Publish methods are called from
the chunk-handling loop in _send_task_to_agent_with_message.
"""

import asyncio
import contextlib
from collections import deque
from collections.abc import AsyncIterator

from common import utils
from common.streaming import GapEvent

logger = utils.get_logger("streaming_hub")

_QUEUE_MAXSIZE = 256


class _Subscriber:
    """A single SSE subscriber's bounded buffer.

    Owns a deque + asyncio.Condition so that agent_activity coalescing and
    overflow handling are first-class operations instead of reaching into an
    asyncio.Queue's private internals. agent_activity events are coalesced in
    place per task_id; overflow of non-coalesced types replaces the oldest
    buffered event with a single GapEvent sentinel rather than dropping silently.
    """

    def __init__(self, maxsize: int = _QUEUE_MAXSIZE) -> None:
        self._maxsize = maxsize
        self._items: deque[dict] = deque()
        self._activity_index: dict[str, dict] = {}  # task_id -> currently buffered activity event
        self._cond = asyncio.Condition()

    async def get(self) -> dict:
        """Wait for and return the next buffered event."""
        async with self._cond:
            while not self._items:
                await self._cond.wait()
            item = self._items.popleft()
            self._discard_from_index(item)
            return item

    async def put(self, event: dict, seq: int) -> None:
        """Buffer an event, coalescing agent_activity and guarding overflow."""
        async with self._cond:
            self._put_locked(event, seq)
            self._cond.notify()

    def _put_locked(self, event: dict, seq: int) -> None:
        if event.get("type") == "agent_activity" and event.get("task_id"):
            existing = self._activity_index.get(event["task_id"])
            if existing is not None:
                # Replace the buffered activity in place: same dict object stays in the deque.
                existing.clear()
                existing.update(event)
                return
        self._append(event, seq)

    def _append(self, event: dict, seq: int) -> None:
        if len(self._items) >= self._maxsize:
            dropped = self._items.popleft()
            self._discard_from_index(dropped)
            gap = GapEvent(reason="queue_overflow", since=seq, until=seq).model_dump()
            self._items.append(gap)
            return
        self._items.append(event)
        if event.get("type") == "agent_activity" and event.get("task_id"):
            self._activity_index[event["task_id"]] = event

    def _discard_from_index(self, item: dict) -> None:
        if item.get("type") == "agent_activity" and item.get("task_id"):
            task_id = item["task_id"]
            if self._activity_index.get(task_id) is item:
                del self._activity_index[task_id]

    async def drain(self) -> None:
        """Discard all buffered events (used on lifespan shutdown)."""
        async with self._cond:
            self._items.clear()
            self._activity_index.clear()


class StreamingHub:
    """Pub/sub hub for global and per-agent SSE streams.

    Subscribers are handed out as async context managers that own a bounded
    _Subscriber buffer; consumers read directly from it via await subscriber.get().
    """

    def __init__(self) -> None:
        self._global_subs: list[_Subscriber] = []
        self._agent_subs: dict[str, list[_Subscriber]] = {}
        self._lock = asyncio.Lock()
        self._seq: int = 0

    @contextlib.asynccontextmanager
    async def subscribe_global(self) -> AsyncIterator[_Subscriber]:
        """Register a global subscriber for the lifetime of the context."""
        sub = _Subscriber()
        async with self._lock:
            self._global_subs.append(sub)
        try:
            yield sub
        finally:
            async with self._lock:
                with contextlib.suppress(ValueError):
                    self._global_subs.remove(sub)

    @contextlib.asynccontextmanager
    async def subscribe_agent(self, agent_id: str) -> AsyncIterator[_Subscriber]:
        """Register a per-agent subscriber for the lifetime of the context."""
        sub = _Subscriber()
        async with self._lock:
            self._agent_subs.setdefault(agent_id, []).append(sub)
        try:
            yield sub
        finally:
            async with self._lock:
                subs = self._agent_subs.get(agent_id, [])
                with contextlib.suppress(ValueError):
                    subs.remove(sub)
                if not subs:
                    self._agent_subs.pop(agent_id, None)

    async def publish_global(self, event: dict) -> None:
        """Publish an event to all global subscribers."""
        async with self._lock:
            seq = self._seq
            self._seq += 1
            subs = list(self._global_subs)
        for sub in subs:
            await sub.put(event, seq)

    async def publish_agent(self, agent_id: str, event: dict) -> None:
        """Publish an event to all subscribers for a specific agent."""
        async with self._lock:
            seq = self._seq
            self._seq += 1
            subs = list(self._agent_subs.get(agent_id, []))
        for sub in subs:
            await sub.put(event, seq)

    async def shutdown(self) -> None:
        """Drain all subscriber buffers on lifespan shutdown."""
        async with self._lock:
            all_subs = list(self._global_subs) + [s for subs in self._agent_subs.values() for s in subs]
        for sub in all_subs:
            await sub.drain()


streaming_hub = StreamingHub()
