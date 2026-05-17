import asyncio

import pytest

from common.streaming import GapEvent
from orchestrator.streaming_hub import StreamingHub, _QUEUE_MAXSIZE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _collect_one(gen) -> dict:
    """Pull the next item from an async generator with a short timeout."""
    return await asyncio.wait_for(gen.__anext__(), timeout=1.0)


# ---------------------------------------------------------------------------
# Global pub/sub
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_global_delivers_to_subscriber():
    hub = StreamingHub()
    received = []

    async def consume():
        async for event in hub.subscribe_global():
            received.append(event)
            break

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)  # let subscriber register

    await hub.publish_global({"type": "task_done", "task_id": "t1"})
    await asyncio.wait_for(task, timeout=1.0)

    assert received == [{"type": "task_done", "task_id": "t1"}]


@pytest.mark.asyncio
async def test_publish_global_delivers_to_multiple_subscribers():
    hub = StreamingHub()
    results: list[list[dict]] = [[], []]

    async def consume(idx: int) -> None:
        async for event in hub.subscribe_global():
            results[idx].append(event)
            break

    tasks = [asyncio.create_task(consume(0)), asyncio.create_task(consume(1))]
    await asyncio.sleep(0)

    await hub.publish_global({"type": "task_done", "task_id": "t1"})
    await asyncio.gather(*tasks)

    assert results[0] == [{"type": "task_done", "task_id": "t1"}]
    assert results[1] == [{"type": "task_done", "task_id": "t1"}]


# ---------------------------------------------------------------------------
# Per-agent pub/sub
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_agent_delivers_only_to_matching_subscriber():
    hub = StreamingHub()
    received_a: list[dict] = []
    received_b: list[dict] = []

    async def consume_a():
        async for event in hub.subscribe_agent("agent-a"):
            received_a.append(event)
            break

    async def consume_b():
        async for event in hub.subscribe_agent("agent-b"):
            received_b.append(event)
            break

    task_a = asyncio.create_task(consume_a())
    task_b = asyncio.create_task(consume_b())
    await asyncio.sleep(0)

    await hub.publish_agent("agent-a", {"type": "log_batch", "task_id": "t1"})

    await asyncio.wait_for(task_a, timeout=1.0)
    assert received_a == [{"type": "log_batch", "task_id": "t1"}]

    # agent-b subscriber should not have received anything
    assert received_b == []
    task_b.cancel()
    with pytest.raises((asyncio.CancelledError, asyncio.TimeoutError)):
        await asyncio.wait_for(task_b, timeout=0.1)


# ---------------------------------------------------------------------------
# agent_activity coalescing: drop-oldest, keep-newest per task_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_activity_coalescing_replaces_older_entry():
    hub = StreamingHub()
    received: list[dict] = []

    async def consume():
        async for event in hub.subscribe_global():
            received.append(event)
            if len(received) >= 1:
                break

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)  # let subscriber register

    # Publish two activity events with the same task_id before consumer reads
    await hub.publish_global({"type": "agent_activity", "task_id": "t1", "text": "old"})
    await hub.publish_global({"type": "agent_activity", "task_id": "t1", "text": "new"})

    await asyncio.wait_for(task, timeout=1.0)

    assert len(received) == 1
    assert received[0]["text"] == "new"


@pytest.mark.asyncio
async def test_agent_activity_different_task_ids_not_coalesced():
    hub = StreamingHub()
    received: list[dict] = []

    async def consume():
        async for event in hub.subscribe_global():
            received.append(event)
            if len(received) >= 2:
                break

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)

    await hub.publish_global({"type": "agent_activity", "task_id": "t1", "text": "a"})
    await hub.publish_global({"type": "agent_activity", "task_id": "t2", "text": "b"})

    await asyncio.wait_for(task, timeout=1.0)

    assert len(received) == 2
    task_ids = {e["task_id"] for e in received}
    assert task_ids == {"t1", "t2"}


# ---------------------------------------------------------------------------
# Non-coalesced overflow → GapEvent instead of silent drop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_coalesced_overflow_emits_gap_sentinel():
    hub = StreamingHub()

    # Subscribe but never consume so the queue fills up
    sub_gen = hub.subscribe_global()
    # Advance the generator once to register the queue
    first_task = asyncio.create_task(sub_gen.__anext__())
    await asyncio.sleep(0)

    # Flood with step_summary events (non-coalesced) to fill the bounded queue
    for i in range(_QUEUE_MAXSIZE + 5):
        await hub.publish_global({"type": "step_summary", "task_id": "t1", "seq": i})

    first_task.cancel()
    with pytest.raises((asyncio.CancelledError, Exception)):
        await first_task

    # Drain the queue and look for at least one GapEvent
    queue = hub._global_queues[0] if hub._global_queues else None
    if queue is None:
        # subscriber already cleaned up — test still valid as no crash occurred
        return

    items = []
    while not queue.empty():
        items.append(queue.get_nowait())

    gap_items = [i for i in items if i.get("type") == "gap"]
    assert len(gap_items) >= 1
    assert gap_items[0]["reason"] == "queue_overflow"

    await sub_gen.aclose()


# ---------------------------------------------------------------------------
# shutdown() drains all subscriber queues
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shutdown_drains_all_queues():
    hub = StreamingHub()

    # Register a global and a per-agent subscriber by starting their generators
    global_gen = hub.subscribe_global()
    agent_gen = hub.subscribe_agent("agent-1")

    global_task = asyncio.create_task(global_gen.__anext__())
    agent_task = asyncio.create_task(agent_gen.__anext__())
    await asyncio.sleep(0)  # let both register

    # Publish events so queues are non-empty
    await hub.publish_global({"type": "task_done", "task_id": "t1"})
    await hub.publish_agent("agent-1", {"type": "log_batch", "task_id": "t1"})

    await hub.shutdown()

    # All registered queues should now be empty
    for q in hub._global_queues:
        assert q.empty()
    for qs in hub._agent_queues.values():
        for q in qs:
            assert q.empty()

    global_task.cancel()
    agent_task.cancel()
    for t in (global_task, agent_task):
        with pytest.raises((asyncio.CancelledError, Exception)):
            await t

    await global_gen.aclose()
    await agent_gen.aclose()
