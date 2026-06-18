# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import asyncio

import pytest

from orchestrator.streaming_hub import _QUEUE_MAXSIZE, StreamingHub

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_one(subscriber) -> dict:
    """Pull the next event from a subscriber with a short timeout."""
    return await asyncio.wait_for(subscriber.get(), timeout=1.0)


# ---------------------------------------------------------------------------
# Global pub/sub
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_global_delivers_to_subscriber():
    hub = StreamingHub()
    async with hub.subscribe_global() as sub:
        await hub.publish_global({"type": "task_done", "task_id": "t1"})
        assert await _get_one(sub) == {"type": "task_done", "task_id": "t1"}


@pytest.mark.asyncio
async def test_publish_global_delivers_to_multiple_subscribers():
    hub = StreamingHub()
    async with hub.subscribe_global() as sub_a, hub.subscribe_global() as sub_b:
        await hub.publish_global({"type": "task_done", "task_id": "t1"})
        assert await _get_one(sub_a) == {"type": "task_done", "task_id": "t1"}
        assert await _get_one(sub_b) == {"type": "task_done", "task_id": "t1"}


# ---------------------------------------------------------------------------
# Per-agent pub/sub
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_agent_delivers_only_to_matching_subscriber():
    hub = StreamingHub()
    async with hub.subscribe_agent("agent-a") as sub_a, hub.subscribe_agent("agent-b") as sub_b:
        await hub.publish_agent("agent-a", {"type": "log_batch", "task_id": "t1"})

        assert await _get_one(sub_a) == {"type": "log_batch", "task_id": "t1"}

        # agent-b subscriber should not have received anything
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(sub_b.get(), timeout=0.1)


@pytest.mark.asyncio
async def test_subscribe_agent_cleans_up_empty_agent_key():
    hub = StreamingHub()
    async with hub.subscribe_agent("agent-a"):
        assert "agent-a" in hub._agent_subs
    # Last subscriber unsubscribed -> key removed.
    assert "agent-a" not in hub._agent_subs


# ---------------------------------------------------------------------------
# agent_activity coalescing: drop-oldest, keep-newest per task_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_activity_coalescing_replaces_older_entry():
    hub = StreamingHub()
    async with hub.subscribe_global() as sub:
        # Publish two activity events with the same task_id before consumer reads.
        await hub.publish_global({"type": "agent_activity", "task_id": "t1", "text": "old"})
        await hub.publish_global({"type": "agent_activity", "task_id": "t1", "text": "new"})

        event = await _get_one(sub)
        assert event["text"] == "new"

        # Only the coalesced event was buffered; nothing else remains.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(sub.get(), timeout=0.1)


@pytest.mark.asyncio
async def test_agent_activity_different_task_ids_not_coalesced():
    hub = StreamingHub()
    async with hub.subscribe_global() as sub:
        await hub.publish_global({"type": "agent_activity", "task_id": "t1", "text": "a"})
        await hub.publish_global({"type": "agent_activity", "task_id": "t2", "text": "b"})

        first = await _get_one(sub)
        second = await _get_one(sub)
        assert {first["task_id"], second["task_id"]} == {"t1", "t2"}


# ---------------------------------------------------------------------------
# Non-coalesced overflow → GapEvent instead of silent drop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_coalesced_overflow_emits_gap_sentinel():
    hub = StreamingHub()
    async with hub.subscribe_global() as sub:
        # Flood with step_summary events (non-coalesced) to overflow the bounded buffer.
        for i in range(_QUEUE_MAXSIZE + 5):
            await hub.publish_global({"type": "step_summary", "task_id": "t1", "seq": i})

        items = []
        while True:
            try:
                items.append(await asyncio.wait_for(sub.get(), timeout=0.1))
            except TimeoutError:
                break

        gap_items = [i for i in items if i.get("type") == "gap"]
        assert len(gap_items) >= 1
        assert gap_items[0]["reason"] == "queue_overflow"


# ---------------------------------------------------------------------------
# shutdown() drains all subscriber buffers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shutdown_drains_all_buffers():
    hub = StreamingHub()
    async with hub.subscribe_global() as global_sub, hub.subscribe_agent("agent-1") as agent_sub:
        await hub.publish_global({"type": "task_done", "task_id": "t1"})
        await hub.publish_agent("agent-1", {"type": "log_batch", "task_id": "t1"})

        await hub.shutdown()

        for sub in (global_sub, agent_sub):
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(sub.get(), timeout=0.1)
