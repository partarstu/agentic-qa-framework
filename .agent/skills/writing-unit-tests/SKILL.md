---
name: writing-unit-tests
description: Writes unit tests for agents, orchestrator logic, and common utilities in the QuAIA framework using pytest. Use when adding tests for new or existing components.
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

📄 **Template:** [resources/conftest_template.py](resources/conftest_template.py)

## Writing Agent Tests

### Basic Agent Test Structure

Agent tests verify:
1. Agent initialization with correct configuration
2. Custom tools work as expected
3. Thinking budget and request limits are properly returned

📄 **Example:** [examples/test_agent_example.py](examples/test_agent_example.py)

## Writing Orchestrator Tests

### Testing Orchestrator Logic Functions

📄 **Example:** [examples/test_orchestrator_logic.py](examples/test_orchestrator_logic.py)

### Testing Artifact Parsing Functions

📄 **Example:** [examples/test_parsing_logic.py](examples/test_parsing_logic.py)

### Testing Endpoint Functions

📄 **Example:** [examples/test_endpoints.py](examples/test_endpoints.py)

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

## Test Helper Utilities

Use the provided helper utilities for creating mock objects:

📄 **Template:** [resources/test_helpers.py](resources/test_helpers.py)

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
