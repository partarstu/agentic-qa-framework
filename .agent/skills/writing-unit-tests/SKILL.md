---
name: Writing Unit Tests
description: Comprehensive guide for writing unit tests for agents and orchestrator components in QuAIA
---

# Writing Unit Tests

This skill provides a comprehensive guide for writing unit tests for the QuAIA™ framework, covering agents, orchestrator logic, and common utilities.

## Overview

The QuAIA test suite uses:
- **pytest** as the test framework
- **pytest-asyncio** for async test support
- **unittest.mock** for mocking dependencies
- **monkeypatch** (pytest fixture) for configuration overrides

Tests are organized in the `tests/` directory:
```
tests/
├── conftest.py          # Shared fixtures and test setup
├── agents/              # Agent-specific tests
├── orchestrator/        # Orchestrator logic tests
├── common/              # Common utilities tests
└── scripts/             # Script tests
```

## Test Configuration

### conftest.py Setup

The root `tests/conftest.py` sets up global test configuration:

```python
import os
import sys
from unittest.mock import MagicMock

# Set dummy API keys for test environment
os.environ["OPENAI_API_KEY"] = "dummy"
os.environ["GOOGLE_API_KEY"] = "dummy"

# Mock heavy dependencies to avoid loading during test collection
mock_sentence_transformers = MagicMock()
sys.modules["sentence_transformers"] = mock_sentence_transformers

import pytest  # noqa: E402

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
```

## Writing Agent Tests

### Basic Agent Test Structure

Agent tests verify:
1. Agent initialization with correct configuration
2. Custom tools work as expected
3. Thinking budget and request limits are properly returned

```python
# tests/agents/test_<agent_name>.py

from unittest.mock import MagicMock, patch

import pytest

import config
from agents.<agent_name>.main import <AgentName>Agent


@pytest.fixture
def mock_config(monkeypatch):
    """Mock configuration values for testing."""
    monkeypatch.setattr(config.<AgentName>AgentConfig, "OWN_NAME", "Test Agent")
    monkeypatch.setattr(config.<AgentName>AgentConfig, "PORT", 8099)
    monkeypatch.setattr(config.<AgentName>AgentConfig, "EXTERNAL_PORT", 8099)
    monkeypatch.setattr(config.<AgentName>AgentConfig, "PROTOCOL", "http")
    monkeypatch.setattr(config.<AgentName>AgentConfig, "MODEL_NAME", "test")
    monkeypatch.setattr(config.<AgentName>AgentConfig, "THINKING_BUDGET", 100)
    monkeypatch.setattr(config.<AgentName>AgentConfig, "MAX_REQUESTS_PER_TASK", 5)
    monkeypatch.setattr(config, "AGENT_BASE_URL", "http://localhost")
    # Add any agent-specific config mocks here


@patch("agents.<agent_name>.main.<AgentName>SystemPrompt")
@patch("agents.<agent_name>.main.AgentBase.__init__")
def test_agent_init(mock_super_init, mock_prompt_cls, mock_config):
    """Test agent initializes with correct configuration."""
    mock_prompt_instance = MagicMock()
    mock_prompt_instance.get_prompt.return_value = "system prompt"
    mock_prompt_cls.return_value = mock_prompt_instance

    agent = <AgentName>Agent()

    mock_super_init.assert_called_once()
    _, kwargs = mock_super_init.call_args
    assert kwargs["agent_name"] == "Test Agent"
    assert kwargs["instructions"] == "system prompt"

    assert agent.get_thinking_budget() == 100
    assert agent.get_max_requests_per_task() == 5
```

### Testing Custom Agent Tools

For agents with custom tools, test them separately:

```python
@pytest.mark.asyncio
async def test_custom_tool_success(mock_config):
    """Test custom tool returns expected result."""
    with patch("agents.<agent_name>.main.AgentBase.__init__"):
        agent = <AgentName>Agent()
        
        # Mock any external dependencies the tool uses
        with patch("agents.<agent_name>.main.external_service") as mock_service:
            mock_service.call.return_value = "expected result"
            
            result = await agent.custom_tool("input")
            
            assert result == "expected result"
            mock_service.call.assert_called_once_with("input")


@pytest.mark.asyncio
async def test_custom_tool_handles_error(mock_config):
    """Test custom tool handles errors gracefully."""
    with patch("agents.<agent_name>.main.AgentBase.__init__"):
        agent = <AgentName>Agent()
        
        with patch("agents.<agent_name>.main.external_service") as mock_service:
            mock_service.call.side_effect = Exception("Service unavailable")
            
            with pytest.raises(RuntimeError):
                await agent.custom_tool("input")
```

## Writing Orchestrator Tests

### Testing Orchestrator Logic Functions

```python
# tests/orchestrator/test_orchestrator_logic.py

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from a2a.types import AgentCapabilities, AgentCard

import config
from orchestrator.main import (
    AgentStatus,
    BrokenReason,
    _discover_agents,
    _fetch_agent_card,
    _select_agent,
    agent_registry,
    discovery_agent,
)


@pytest.fixture
async def clear_registry():
    """Clear agent registry before and after each test."""
    agent_registry._cards.clear()
    agent_registry._statuses.clear()
    agent_registry._broken_reasons.clear()
    agent_registry._stuck_task_ids.clear()
    yield
    agent_registry._cards.clear()
    agent_registry._statuses.clear()
    agent_registry._broken_reasons.clear()
    agent_registry._stuck_task_ids.clear()


@pytest.fixture
def mock_agent_card():
    """Create a mock AgentCard for testing."""
    return AgentCard(
        name="Test Agent",
        description="Test description",
        url="http://localhost:8001",
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=False),
        skills=[],
        defaultInputModes=['text'],
        defaultOutputModes=['text']
    )


@pytest.mark.asyncio
async def test_fetch_agent_card_success(mock_agent_card):
    """Test successful agent card fetch."""
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_agent_card.model_dump()
        mock_client.get.return_value = mock_response

        card = await _fetch_agent_card("http://localhost:8001")
        assert card.name == "Test Agent"


@pytest.mark.asyncio
async def test_fetch_agent_card_failure():
    """Test agent card fetch handles connection errors."""
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_client.get.side_effect = Exception("Connection error")

        card = await _fetch_agent_card("http://bad-url")
        assert card is None
```

### Testing Artifact Parsing Functions

```python
# tests/orchestrator/test_parsing_logic.py

from unittest.mock import AsyncMock, patch

import pytest
from a2a.types import Artifact, FilePart, FileWithBytes, Part, TextPart

from common.models import AgentExecutionError, JsonSerializableModel
from orchestrator.main import (
    _get_model_from_artifacts,
    _get_text_content_from_artifacts,
)


def _create_text_artifact(texts: list[str]) -> Artifact:
    """Helper to create an artifact with text parts."""
    parts = [Part(root=TextPart(text=text)) for text in texts]
    return Artifact(artifactId="test-artifact", parts=parts)


def _create_file_artifact(filename: str = "test.txt") -> Artifact:
    """Helper to create an artifact with a file part."""
    file_part = FilePart(file=FileWithBytes(name=filename, mimeType="text/plain", bytes=b"content"))
    return Artifact(artifactId="file-artifact", parts=[Part(root=file_part)])


class SampleModel(JsonSerializableModel):
    """Sample model for testing."""
    name: str
    value: int


@pytest.fixture
def mock_error_history():
    """Mock error_history to prevent asyncio event loop issues."""
    with patch("orchestrator.main.error_history") as mock:
        mock.add = AsyncMock()
        yield mock


class TestGetTextContentFromArtifacts:
    """Tests for _get_text_content_from_artifacts function."""

    def test_single_artifact_single_text_part(self):
        """Test extracting text from a single artifact with one text part."""
        artifacts = [_create_text_artifact(["Hello, World!"])]
        result = _get_text_content_from_artifacts(artifacts, "test task")
        assert result == ["Hello, World!"]

    def test_multiple_artifacts_multiple_parts(self):
        """Test extracting text from multiple artifacts."""
        artifacts = [
            _create_text_artifact(["Part 1", "Part 2"]),
            _create_text_artifact(["Part 3"]),
        ]
        result = _get_text_content_from_artifacts(artifacts, "test task")
        assert result == ["Part 1", "Part 2", "Part 3"]

    @pytest.mark.asyncio
    async def test_empty_artifacts_raises_exception(self, mock_error_history):
        """Test empty artifacts raises exception when content expected."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _get_text_content_from_artifacts([], "test task", any_content_expected=True)
        
        assert exc_info.value.status_code == 500

    def test_empty_artifacts_returns_empty_when_not_expected(self):
        """Test empty artifacts returns empty list when content not expected."""
        result = _get_text_content_from_artifacts([], "test task", any_content_expected=False)
        assert result == []


class TestGetModelFromArtifacts:
    """Tests for _get_model_from_artifacts function."""

    def test_parse_valid_model(self):
        """Test parsing valid JSON into model."""
        json_content = '{"name": "test", "value": 42}'
        artifacts = [_create_text_artifact([json_content])]
        
        result = _get_model_from_artifacts(artifacts, "test task", SampleModel)
        
        assert isinstance(result, SampleModel)
        assert result.name == "test"
        assert result.value == 42

    def test_parse_agent_execution_error(self):
        """Test AgentExecutionError is correctly recognized."""
        error_json = '{"error_message": "Something went wrong"}'
        artifacts = [_create_text_artifact([error_json])]
        
        result = _get_model_from_artifacts(artifacts, "test task", SampleModel)
        
        assert isinstance(result, AgentExecutionError)
        assert result.error_message == "Something went wrong"

    @pytest.mark.asyncio
    async def test_invalid_json_raises_exception(self, mock_error_history):
        """Test invalid JSON raises exception."""
        from fastapi import HTTPException

        artifacts = [_create_text_artifact(["not valid json"])]
        
        with pytest.raises(HTTPException) as exc_info:
            _get_model_from_artifacts(artifacts, "test task", SampleModel)
        
        assert "failed to parse" in exc_info.value.detail.lower()
```

### Testing Endpoint Functions

```python
# tests/orchestrator/test_endpoints.py

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from orchestrator.main import orchestrator_app


@pytest.fixture
def client():
    """Create test client for orchestrator."""
    return TestClient(orchestrator_app)


@pytest.fixture
def mock_api_key(monkeypatch):
    """Bypass API key validation."""
    monkeypatch.setattr("orchestrator.main._validate_api_key", lambda x=None: None)


@pytest.fixture
def mock_agent_registry():
    """Mock the agent registry."""
    with patch("orchestrator.main.agent_registry") as mock:
        mock.is_empty = AsyncMock(return_value=False)
        mock.get_all_cards = AsyncMock(return_value={"agent-1": MagicMock()})
        mock.get_status = AsyncMock(return_value="AVAILABLE")
        yield mock


class TestWorkflowEndpoints:
    """Tests for orchestrator workflow endpoints."""

    @pytest.mark.asyncio
    async def test_workflow_endpoint_success(self, client, mock_api_key):
        """Test successful workflow execution."""
        with patch("orchestrator.main._send_task_to_agent") as mock_send, \
             patch("orchestrator.main._get_artifacts_from_task") as mock_artifacts:
            
            mock_task = MagicMock()
            mock_task.status.state = "completed"
            mock_send.return_value = mock_task
            mock_artifacts.return_value = [...]  # Mock artifacts
            
            response = client.post(
                "/endpoint-path",
                json={"field": "value"}
            )
            
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_workflow_endpoint_agent_unavailable(self, client, mock_api_key):
        """Test workflow handles agent unavailability."""
        with patch("orchestrator.main._send_task_to_agent") as mock_send:
            mock_send.side_effect = Exception("No agents available")
            
            response = client.post(
                "/endpoint-path",
                json={"field": "value"}
            )
            
            assert response.status_code == 500
```

## Testing Patterns

### Mocking External Services

When testing components that interact with external services:

```python
@pytest.fixture
def mock_jira_client():
    """Mock JIRA client for tests."""
    with patch("common.services.jira_client.JIRA") as mock:
        mock_instance = MagicMock()
        mock.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def mock_vector_db():
    """Mock vector database service."""
    with patch("common.services.vector_db_service.VectorDbService") as mock:
        mock_instance = MagicMock()
        mock.return_value = mock_instance
        mock_instance.search = AsyncMock(return_value=[])
        yield mock_instance
```

### Testing Async Code

For async functions, use `pytest.mark.asyncio`:

```python
@pytest.mark.asyncio
async def test_async_function():
    """Test an async function."""
    result = await some_async_function()
    assert result is not None


@pytest.mark.asyncio
async def test_async_with_mock():
    """Test async function with mocked dependencies."""
    with patch("module.dependency", new_callable=AsyncMock) as mock_dep:
        mock_dep.return_value = "mocked result"
        
        result = await async_function_using_dependency()
        
        assert result == "mocked result"
        mock_dep.assert_called_once()
```

### Testing Exception Handling

```python
@pytest.mark.asyncio
async def test_handles_exception_gracefully(mock_error_history):
    """Test function handles exceptions properly."""
    from fastapi import HTTPException

    with patch("module.dependency") as mock_dep:
        mock_dep.side_effect = Exception("Unexpected error")
        
        with pytest.raises(HTTPException) as exc_info:
            await function_that_should_catch_and_rethrow()
        
        assert exc_info.value.status_code == 500
        assert "error" in exc_info.value.detail.lower()
```

### Using Parametrized Tests

For testing multiple scenarios:

```python
@pytest.mark.parametrize("input_value,expected_output", [
    ("valid_input", "expected_result"),
    ("another_input", "another_result"),
    ("edge_case", "edge_result"),
])
def test_multiple_scenarios(input_value, expected_output):
    """Test multiple input/output combinations."""
    result = function_under_test(input_value)
    assert result == expected_output


@pytest.mark.parametrize("status,should_succeed", [
    ("AVAILABLE", True),
    ("BUSY", False),
    ("BROKEN", False),
])
@pytest.mark.asyncio
async def test_status_handling(status, should_succeed, clear_registry):
    """Test handling of different agent statuses."""
    # Setup agent with given status
    # Run test
    # Assert based on should_succeed
```

## Running Tests

### Running All Tests

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run with coverage report
pytest --cov=. --cov-report=html
```

### Running Specific Tests

```bash
# Run tests for a specific module
pytest tests/agents/

# Run tests for a specific file
pytest tests/agents/test_requirements_review.py

# Run a specific test function
pytest tests/orchestrator/test_parsing_logic.py::TestGetModelFromArtifacts::test_parse_valid_model

# Run tests matching a pattern
pytest -k "test_agent"
```

### Running Async Tests

```bash
# Ensure pytest-asyncio is configured
pytest tests/orchestrator/test_orchestrator_logic.py -v
```

## Test Helper Utilities

### Creating Test Artifacts

```python
def _create_text_artifact(texts: list[str]) -> Artifact:
    """Helper to create an artifact with text parts."""
    parts = [Part(root=TextPart(text=text)) for text in texts]
    return Artifact(artifactId="test-artifact", parts=parts)


def _create_file_artifact(filename: str = "test.txt", content: bytes = b"content") -> Artifact:
    """Helper to create an artifact with a file part."""
    file_part = FilePart(
        file=FileWithBytes(name=filename, mimeType="text/plain", bytes=content)
    )
    return Artifact(artifactId="file-artifact", parts=[Part(root=file_part)])


def _create_mixed_artifact(text: str, filename: str = "test.txt") -> Artifact:
    """Helper to create an artifact with both text and file parts."""
    text_part = Part(root=TextPart(text=text))
    file_part = Part(root=FilePart(
        file=FileWithBytes(name=filename, mimeType="text/plain", bytes=b"content")
    ))
    return Artifact(artifactId="mixed-artifact", parts=[text_part, file_part])
```

### Creating Mock Agent Cards

```python
def create_mock_agent_card(
    name: str = "Test Agent",
    url: str = "http://localhost:8001",
    description: str = "Test description"
) -> AgentCard:
    """Create a mock AgentCard for testing."""
    return AgentCard(
        name=name,
        description=description,
        url=url,
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=False),
        skills=[],
        defaultInputModes=['text'],
        defaultOutputModes=['text']
    )
```

## Verification Checklist

After writing tests, verify:

- [ ] All test files follow naming convention `test_<module_name>.py`
- [ ] Test classes are named `Test<FeatureName>` 
- [ ] Test methods are named `test_<what_is_being_tested>`
- [ ] Fixtures are used for setup/teardown
- [ ] Async tests use `@pytest.mark.asyncio`
- [ ] External dependencies are properly mocked
- [ ] Both success and failure paths are tested
- [ ] Edge cases are covered
- [ ] Tests pass locally: `pytest tests/<test_file>.py -v`
- [ ] Coverage is adequate: `pytest --cov=<module> tests/<test_file>.py`

## Common Issues and Solutions

### AsyncIO Event Loop Issues

If you see "There is no current event loop" errors:

```python
@pytest.fixture
def mock_error_history():
    """Mock async components to prevent event loop issues."""
    with patch("orchestrator.main.error_history") as mock:
        mock.add = AsyncMock()
        yield mock
```

### Module Import Issues

If imports fail during test collection, mock heavy dependencies in `conftest.py`:

```python
# Mock sentence_transformers before any imports
mock_sentence_transformers = MagicMock()
sys.modules["sentence_transformers"] = mock_sentence_transformers
```

### Configuration Issues

Always mock config values in fixtures rather than modifying global state:

```python
@pytest.fixture
def mock_config(monkeypatch):
    monkeypatch.setattr(config.SomeConfig, "VALUE", "test_value")
```
