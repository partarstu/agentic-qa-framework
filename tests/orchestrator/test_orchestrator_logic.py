
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from orchestrator.main import _discover_agents, agent_registry, _fetch_agent_card, _select_agent, discovery_agent
from a2a.types import AgentCard, AgentCapabilities
import config

@pytest.fixture
async def clear_registry():
    # Clear registry before/after test
    agent_registry._cards.clear()
    agent_registry._statuses.clear()
    yield
    agent_registry._cards.clear()
    agent_registry._statuses.clear()

@pytest.fixture
def mock_agent_card():
    return AgentCard(
        name="Discovered Agent",
        description="Desc",
        url="http://localhost:8001",
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=False),
        skills=[],
        defaultInputModes=['text'],
        defaultOutputModes=['text']
    )

@pytest.mark.asyncio
async def test_fetch_agent_card_success(mock_agent_card):
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_agent_card.model_dump()
        mock_client.get.return_value = mock_response
        
        card = await _fetch_agent_card("http://localhost:8001")
        assert card.name == "Discovered Agent"

@pytest.mark.asyncio
async def test_fetch_agent_card_failure():
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        
        mock_client.get.side_effect = Exception("Connection error")
        
        card = await _fetch_agent_card("http://bad-url")
        assert card is None

@pytest.mark.asyncio
async def test_discover_agents_success(clear_registry, mock_agent_card):
    with patch("config.REMOTE_EXECUTION_AGENT_HOSTS", "http://localhost"), \
         patch("config.AGENT_DISCOVERY_PORTS", "8001-8001"), \
         patch("orchestrator.main._fetch_agent_card", return_value=mock_agent_card):
        
        await _discover_agents()
        
        assert not await agent_registry.is_empty()
        cards = await agent_registry.get_all_cards()
        assert len(cards) == 1
        assert list(cards.values())[0].name == "Discovered Agent"

@pytest.mark.asyncio
async def test_select_agent(clear_registry, mock_agent_card):
    # Register an agent first
    await agent_registry.register("test-id", mock_agent_card)
    
    # Mock LLM response
    mock_result = MagicMock()
    mock_result.output.id = "test-id"
    
    # Mock discovery agent run
    with patch.object(discovery_agent, "run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = mock_result
        
        agent_id = await _select_agent("some task")
        assert agent_id == "test-id"

@pytest.mark.asyncio
async def test_select_agent_none_found(clear_registry):
    # Registry empty
    agent_id = await _select_agent("some task")
    assert agent_id is None
