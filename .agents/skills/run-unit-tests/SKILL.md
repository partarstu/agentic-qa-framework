---
name: run-unit-tests
description: Executes all unit tests and fixes any issues related to the execution results. Use when running tests, identifying root causes of failures, and fixing them.
---

// turbo-all

# Run Unit Tests

This skill provides a comprehensive guide for executing unit tests in the QuAIA™ framework, identifying root causes of failures, and fixing issues.

## Overview

The QuAIA test suite uses:
- **pytest** as the test framework
- **pytest-asyncio** for async test support
- **unittest.mock** for mocking dependencies

Tests are located in the `tests/` directory:
```
tests/
├── conftest.py          # Shared fixtures and test setup
├── agents/              # Agent-specific tests
├── orchestrator/        # Orchestrator logic tests
├── common/              # Common utilities tests
└── scripts/             # Script tests
```

## ⚡ Auto-Run Policy

This skill is designed to run with minimal interruption.

- **Always set `SafeToAutoRun: true`** for all `run_command` calls.
- **Exceptions:** Only set `SafeToAutoRun: false` if a step specifically instructs you to "Ask" the user, "Wait" for approval, or "Verify" a destructive action before proceeding.
- **Restricted Symbols:** Never use the redirection operator (`>`) or `2>` in commands. Use alternatives (e.g., `Set-Content`, `Out-File`, or ignoring errors explicitly).

## Step-by-Step Instructions

### Step 1: Run All Unit Tests

Execute the full test suite to identify any failures:

```bash
# Run all tests with verbose output
pytest -v

# Run all tests with detailed failure output
pytest -v --tb=long

# Run with coverage report
pytest --cov=. --cov-report=html --cov-report=term-missing
```

### Step 2: Analyze Test Results

After running tests, analyze the output:

1. **Identify failed tests**: Look for `FAILED` markers in the output
2. **Review error messages**: Read the assertion errors and tracebacks
3. **Check test file and line numbers**: Note the exact location of failures

#### Understanding Test Output

```
FAILED tests/agents/test_example.py::TestClass::test_method - AssertionError: ...
```

This tells you:
- **File**: `tests/agents/test_example.py`
- **Class**: `TestClass`
- **Method**: `test_method`
- **Error type**: `AssertionError`

### Step 3: Identify Root Cause

For each failing test, investigate the root cause:

#### 3.1 Run the Specific Failing Test

```bash
# Run a specific test file
pytest tests/agents/test_example.py -v

# Run a specific test class
pytest tests/agents/test_example.py::TestClassName -v

# Run a specific test method
pytest tests/agents/test_example.py::TestClassName::test_method_name -v

# Run with extra debug output
pytest tests/agents/test_example.py::TestClassName::test_method_name -v -s --tb=long
```

#### 3.2 Review the Source Code

1. Open the failing test file and locate the test method
2. Identify the code under test (the actual implementation being tested)
3. Compare expected behavior vs actual behavior

#### 3.3 Check for Common Issues

- **Import errors**: Module not found or circular imports
- **Configuration issues**: Missing environment variables or config values
- **Mocking problems**: Incorrect mock setup or missing patches
- **Async issues**: Event loop problems or missing `@pytest.mark.asyncio`
- **Fixture issues**: Missing or incorrectly scoped fixtures

### Step 4: Fix the Issue

Based on the root cause analysis:

#### 4.1 If the Test is Incorrect

Update the test to match the expected behavior of the implementation:
- Fix incorrect assertions
- Update mock configurations
- Add missing fixtures

#### 4.2 If the Implementation is Incorrect

Fix the source code to match the expected behavior:
- Correct logic errors
- Fix type issues
- Handle edge cases properly

#### 4.3 If Dependencies Changed

Update tests or implementation to accommodate changes:
- Update mock return values
- Adjust expected outputs
- Sync interface changes

### Step 5: Re-run Tests and Verify

After making fixes, verify the changes:

```bash
# Re-run the specific fixed test
pytest tests/path/to/test_file.py::TestClass::test_method -v

# Run all tests in the affected module
pytest tests/path/to/test_file.py -v

# Run the full test suite to ensure no regressions
pytest -v

# Run with coverage to ensure adequate test coverage
pytest --cov=. --cov-report=term-missing
```

### Step 6: Iterate Until All Tests Pass

Repeat Steps 3-5 for each failing test until the entire test suite passes.

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

### Running Tests with Debug Options

```bash
# Show print statements and logging
pytest -v -s

# Stop at first failure
pytest -x

# Run last failed tests first
pytest --lf

# Run failed tests only
pytest --ff

# Show local variables in tracebacks
pytest --tb=long -l
```

## Common Issues and Solutions

### AsyncIO Event Loop Issues

**Symptom**: "There is no current event loop" errors

**Solution**: Mock async components to prevent event loop issues:

```python
@pytest.fixture
def mock_error_history():
    """Mock async components to prevent event loop issues."""
    with patch("orchestrator.main.error_history") as mock:
        mock.add = AsyncMock()
        yield mock
```

### Module Import Issues

**Symptom**: Imports fail during test collection

**Solution**: Mock heavy dependencies in `conftest.py`:

```python
# Mock sentence_transformers before any imports
mock_sentence_transformers = MagicMock()
sys.modules["sentence_transformers"] = mock_sentence_transformers
```

### Configuration Issues

**Symptom**: Tests fail due to missing or incorrect config values

**Solution**: Always mock config values in fixtures rather than modifying global state:

```python
@pytest.fixture
def mock_config(monkeypatch):
    monkeypatch.setattr(config.SomeConfig, "VALUE", "test_value")
```

### Missing Fixtures

**Symptom**: `fixture 'fixture_name' not found`

**Solution**: 
1. Check if the fixture is defined in `conftest.py`
2. Ensure the fixture is in scope (same directory or parent)
3. Verify the fixture name spelling

### Assertion Errors

**Symptom**: `AssertionError: assert X == Y`

**Solution**:
1. Compare expected vs actual values carefully
2. Check if the implementation changed
3. Verify mock return values match expectations
4. Use `pytest.approx()` for floating-point comparisons

### Timeout Issues

**Symptom**: Tests hang or timeout

**Solution**:
1. Check for infinite loops in the code
2. Ensure async functions are properly awaited
3. Add timeouts to async operations:

```python
import asyncio

@pytest.mark.asyncio
async def test_with_timeout():
    result = await asyncio.wait_for(async_function(), timeout=5.0)
    assert result is not None
```

### Mock Not Applied

**Symptom**: Real functions are called instead of mocks

**Solution**:
1. Verify the patch path is correct (patch where it's used, not where it's defined)
2. Ensure patches are applied before the code runs:

```python
# Correct: Patch where the function is imported/used
with patch("module_under_test.function_name") as mock:
    ...

# Incorrect: Patching the original location
with patch("original_module.function_name") as mock:
    ...
```

### Database/External Service Errors

**Symptom**: Tests fail due to external service unavailability

**Solution**:
1. Ensure all external services are mocked
2. Use fixtures to mock database connections
3. Verify environment variables are set for test mode

## Verification Checklist

After fixing tests, verify:

- [ ] All tests pass: `pytest -v`
- [ ] No new warnings introduced
- [ ] Coverage is maintained or improved: `pytest --cov=. --cov-report=term-missing`
- [ ] No regressions in other tests
- [ ] Fixes are minimal and targeted (avoid unnecessary changes)

## Troubleshooting Workflow

```
┌─────────────────────────────────────────────────┐
│              Run All Tests                       │
│              pytest -v                           │
└──────────────────────┬──────────────────────────┘
                       │
                       ▼
              ┌────────────────┐
              │  Tests Pass?   │
              └───────┬────────┘
                      │
         ┌────────────┴────────────┐
         │                         │
        YES                       NO
         │                         │
         ▼                         ▼
   ┌───────────┐         ┌─────────────────────┐
   │   DONE    │         │ Identify Failing    │
   └───────────┘         │ Tests               │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │ Run Specific Test   │
                         │ with Debug Options  │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │ Analyze Traceback   │
                         │ and Error Message   │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │ Identify Root Cause │
                         │ (Test vs Impl)      │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │ Apply Fix           │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │ Re-run Test         │
                         └──────────┬──────────┘
                                    │
                                    ▼
                              (Loop back to
                               "Tests Pass?")
```

## Best Practices

1. **Fix one test at a time**: Focus on a single failing test before moving to the next
2. **Understand before fixing**: Ensure you understand why a test is failing before attempting a fix
3. **Minimal changes**: Make the smallest change necessary to fix the issue
4. **Don't skip tests**: Avoid using `@pytest.mark.skip` unless absolutely necessary
5. **Run full suite**: Always run the complete test suite after fixes to catch regressions
6. **Keep tests isolated**: Each test should be independent and not rely on other tests
7. **Document fixes**: If a fix reveals a subtle issue, add a comment explaining it
