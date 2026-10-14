# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import asyncio

import pytest
from a2a.types import AgentCapabilities, AgentCard, AgentExtension, AgentInterface

from orchestrator.models import (
    TASK_CAPACITY_EXTENSION_URI,
    AgentRegistry,
    AgentStatus,
    BrokenReason,
    task_capacity,
)


@pytest.fixture
def registry():
    return AgentRegistry()


@pytest.fixture
def sample_card():
    return AgentCard(
        name="Test Agent",
        description="A test agent",
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=False),
        skills=[],
        default_input_modes=["text"],
        default_output_modes=["text"],
        supported_interfaces=[AgentInterface(protocol_binding="JSONRPC", url="http://localhost:8000")],
    )


@pytest.mark.asyncio
async def test_register_and_get(registry, sample_card):
    agent_id = "agent-1"
    await registry.register(agent_id, sample_card)

    card = await registry.get_card(agent_id)
    assert card == sample_card
    assert await registry.get_name(agent_id) == "Test Agent"
    assert await registry.get_status(agent_id) == AgentStatus.AVAILABLE
    assert await registry.contains(agent_id)


@pytest.mark.asyncio
async def test_update_status(registry, sample_card):
    agent_id = "agent-1"
    await registry.register(agent_id, sample_card)

    await registry.update_status(agent_id, AgentStatus.BUSY)
    assert await registry.get_status(agent_id) == AgentStatus.BUSY


@pytest.mark.asyncio
async def test_update_status_with_broken_reason(registry, sample_card):
    """Test that update_status correctly tracks broken reason and task ID."""
    agent_id = "agent-1"
    await registry.register(agent_id, sample_card)

    # Mark as BROKEN with OFFLINE reason
    await registry.update_status(agent_id, AgentStatus.BROKEN, BrokenReason.OFFLINE)
    assert await registry.get_status(agent_id) == AgentStatus.BROKEN
    reason, task_id = await registry.get_broken_context(agent_id)
    assert reason == BrokenReason.OFFLINE
    assert task_id is None

    # Mark as BROKEN with TASK_STUCK reason and task ID
    await registry.update_status(agent_id, AgentStatus.BROKEN, BrokenReason.TASK_STUCK, "task-123")
    reason, task_id = await registry.get_broken_context(agent_id)
    assert reason == BrokenReason.TASK_STUCK
    assert task_id == "task-123"

    # Reset to AVAILABLE - should clear broken context
    await registry.update_status(agent_id, AgentStatus.AVAILABLE)
    assert await registry.get_status(agent_id) == AgentStatus.AVAILABLE
    reason, task_id = await registry.get_broken_context(agent_id)
    assert reason is None
    assert task_id is None


@pytest.mark.asyncio
async def test_remove(registry, sample_card):
    agent_id = "agent-1"
    await registry.register(agent_id, sample_card)

    await registry.remove(agent_id)
    assert await registry.get_card(agent_id) is None
    assert await registry.get_status(agent_id) == AgentStatus.BROKEN  # Default if not found
    assert not await registry.contains(agent_id)


@pytest.mark.asyncio
async def test_get_valid_agents(registry, sample_card):
    await registry.register("a1", sample_card)
    await registry.register("a2", sample_card)

    await registry.update_status("a1", AgentStatus.BROKEN, BrokenReason.OFFLINE)

    valid = await registry.get_valid_agents()
    assert "a2" in valid
    assert "a1" not in valid


@pytest.mark.asyncio
async def test_is_empty(registry, sample_card):
    assert await registry.is_empty()
    await registry.register("a1", sample_card)
    assert not await registry.is_empty()


@pytest.mark.asyncio
async def test_get_agent_id_by_url(registry, sample_card):
    """Test looking up agent by URL."""
    agent_id = "agent-1"
    await registry.register(agent_id, sample_card)

    found_id = await registry.get_agent_id_by_url("http://localhost:8000")
    assert found_id == agent_id

    # Non-existent URL should return None
    not_found = await registry.get_agent_id_by_url("http://unknown:9999")
    assert not_found is None


@pytest.mark.asyncio
async def test_get_broken_agents(registry, sample_card):
    """Test getting all broken agents with their context."""
    await registry.register("a1", sample_card)
    await registry.register("a2", sample_card)
    await registry.register("a3", sample_card)

    await registry.update_status("a1", AgentStatus.BROKEN, BrokenReason.OFFLINE)
    await registry.update_status("a2", AgentStatus.BROKEN, BrokenReason.TASK_STUCK, "task-456")
    # a3 remains AVAILABLE

    broken = await registry.get_broken_agents()
    assert len(broken) == 2
    assert "a1" in broken
    assert "a2" in broken
    assert "a3" not in broken

    assert broken["a1"] == (BrokenReason.OFFLINE, None)
    assert broken["a2"] == (BrokenReason.TASK_STUCK, "task-456")


def _card_with_capacity(capacity: object) -> AgentCard:
    card = AgentCard(
        name="Knowledge Agent",
        capabilities=AgentCapabilities(
            streaming=True,
            extensions=[AgentExtension(uri=TASK_CAPACITY_EXTENSION_URI, required=False)],
        ),
        supported_interfaces=[AgentInterface(protocol_binding="JSONRPC", url="http://localhost:8007")],
    )
    card.capabilities.extensions[0].params.update({"capacity": capacity})
    return card


def test_task_capacity_reads_the_capacity_extension_of_the_card():
    assert task_capacity(_card_with_capacity(4)) == 4


def test_task_capacity_is_one_without_the_extension(sample_card):
    assert task_capacity(sample_card) == 1


@pytest.mark.parametrize("capacity", [0, 2.5, 33, "4"])
def test_task_capacity_is_one_when_the_declared_capacity_is_invalid(capacity):
    assert task_capacity(_card_with_capacity(capacity)) == 1


@pytest.mark.asyncio
async def test_agent_is_busy_only_when_its_running_tasks_reach_the_capacity(registry):
    await registry.register("agent-1", _card_with_capacity(2))

    assert await registry.reserve_task("agent-1", "task-1") is not None
    assert await registry.get_status("agent-1") == AgentStatus.AVAILABLE
    assert await registry.reserve_task("agent-1", "task-2") is not None
    assert await registry.get_status("agent-1") == AgentStatus.BUSY
    assert await registry.reserve_task("agent-1", "task-3") is None
    assert await registry.get_running_tasks("agent-1") == ["task-1", "task-2"]
    assert await registry.get_capacity("agent-1") == 2


@pytest.mark.asyncio
async def test_agent_without_capacity_extension_runs_one_task_at_a_time(registry, sample_card):
    await registry.register("agent-1", sample_card)

    await registry.reserve_task("agent-1", "task-1")

    assert await registry.get_status("agent-1") == AgentStatus.BUSY
    assert await registry.reserve_task("agent-1", "task-2") is None


@pytest.mark.asyncio
async def test_release_task_frees_the_slot_of_the_task(registry):
    await registry.register("agent-1", _card_with_capacity(2))
    await registry.reserve_task("agent-1", "task-1")
    await registry.reserve_task("agent-1", "task-2")

    await registry.release_task("agent-1", "task-1")

    assert await registry.get_status("agent-1") == AgentStatus.AVAILABLE
    assert await registry.get_running_tasks("agent-1") == ["task-2"]


@pytest.mark.asyncio
async def test_release_task_keeps_a_broken_agent_broken(registry, sample_card):
    await registry.register("agent-1", sample_card)
    await registry.reserve_task("agent-1", "task-1")
    await registry.update_status("agent-1", AgentStatus.BROKEN, BrokenReason.TASK_STUCK, "task-1")

    await registry.release_task("agent-1", "task-1")

    assert await registry.get_status("agent-1") == AgentStatus.BROKEN
    assert await registry.reserve_task("agent-1", "task-2") is None


@pytest.mark.asyncio
async def test_recovered_agent_keeps_the_slots_of_its_other_running_tasks(registry):
    await registry.register("agent-1", _card_with_capacity(2))
    await registry.reserve_task("agent-1", "task-1")
    await registry.reserve_task("agent-1", "task-2")
    await registry.update_status("agent-1", AgentStatus.BROKEN, BrokenReason.TASK_STUCK, "task-1")
    await registry.release_task("agent-1", "task-1")

    await registry.update_status("agent-1", AgentStatus.AVAILABLE)

    assert await registry.get_running_tasks("agent-1") == ["task-2"]
    assert await registry.get_status("agent-1") == AgentStatus.AVAILABLE
    await registry.reserve_task("agent-1", "task-3")
    assert await registry.get_status("agent-1") == AgentStatus.BUSY


@pytest.mark.asyncio
async def test_remove_unless_busy_keeps_an_agent_with_a_running_task_below_its_capacity(registry):
    await registry.register("agent-1", _card_with_capacity(4))
    await registry.reserve_task("agent-1", "task-1")

    assert not await registry.remove_unless_busy("agent-1")
    assert await registry.contains("agent-1")


@pytest.mark.asyncio
async def test_every_stuck_task_of_an_agent_is_kept_until_it_recovers(registry):
    await registry.register("agent-1", _card_with_capacity(2))
    await registry.update_status("agent-1", AgentStatus.BROKEN, BrokenReason.TASK_STUCK, "task-1")
    await registry.update_status("agent-1", AgentStatus.BROKEN, BrokenReason.TASK_STUCK, "task-2")

    assert await registry.get_stuck_task_ids("agent-1") == ["task-1", "task-2"]
    assert await registry.get_broken_context("agent-1") == (BrokenReason.TASK_STUCK, "task-2")

    await registry.update_status("agent-1", AgentStatus.AVAILABLE)

    assert await registry.get_stuck_task_ids("agent-1") == []
