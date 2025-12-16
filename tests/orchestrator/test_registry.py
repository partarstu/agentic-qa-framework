
import pytest
import asyncio
from orchestrator.main import AgentRegistry, AgentStatus
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
    
    await registry.update_status("a1", AgentStatus.BROKEN)
    
    valid = await registry.get_valid_agents()
    assert "a2" in valid
    assert "a1" not in valid

@pytest.mark.asyncio
async def test_is_empty(registry, sample_card):
    assert await registry.is_empty()
    await registry.register("a1", sample_card)
    assert not await registry.is_empty()
