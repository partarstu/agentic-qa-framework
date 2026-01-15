
import pytest
import asyncio
from orchestrator.models import AgentRegistry, AgentStatus, BrokenReason
from a2a.types import AgentCard, AgentCapabilities

@pytest.fixture
def registry():
    return AgentRegistry()

@pytest.fixture
def sample_card():
    return AgentCard(
        name="Test Agent",
        description="A test agent",
        url="http://localhost:8000",
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=False),
        skills=[],
        defaultInputModes=['text'],
        defaultOutputModes=['text']
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
    assert await registry.get_status(agent_id) == AgentStatus.BROKEN # Default if not found
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

