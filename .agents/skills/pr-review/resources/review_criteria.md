# PR Review Criteria

This document defines the comprehensive review criteria for Python code in the QuAIA™ project. These criteria are
derived from the project's GEMINI.md guidelines, Python best practices (PEP 8, PEP 257), and industry standards for
secure, maintainable code.

## 1. Code Style & Naming Conventions

### PEP 8 Compliance

| Element                     | Convention           | Example                         |
|-----------------------------|----------------------|---------------------------------|
| Functions, methods          | `snake_case`         | `process_data()`, `get_result()`|
| Variables, modules          | `snake_case`         | `user_name`, `file_path`        |
| Classes                     | `PascalCase`         | `UserManager`, `TestResult`     |
| Constants                   | `SCREAMING_SNAKE_CASE` | `MAX_RETRIES`, `DEFAULT_TIMEOUT`|
| Internal/private members    | `_leading_underscore`| `_internal_helper()`, `_cache`  |
| Config keys (TOML/YAML/INI) | `snake_case`         | `api_key`, `database_url`       |
| Environment variables       | `SCREAMING_SNAKE_CASE` | `DATABASE_URL`, `API_KEY`     |

### Code Clarity

- **Readability over cleverness**: Avoid overly complex one-liners or list comprehensions that sacrifice clarity
- **Function length**: Functions should be concise (under ~40 lines) with a single responsibility
- **Line length**: Adhere to reasonable line lengths (88-100 characters)
- **No unnecessary reformatting**: Only modify code you're intentionally changing

## 2. Type Hints & Type Safety

### Requirements

- **All function signatures** must have type hints for arguments and return values
- **Modern syntax preferred**: Use `list[str]` instead of `typing.List[str]`
- **Nullable types**: Use `str | None` or `Optional[str]` to indicate nullable values
- **Return type always specified**: Even `-> None` for void functions

### Examples

```python
# Good
def process_items(items: list[str], limit: int | None = None) -> dict[str, int]:
    ...

# Bad - missing type hints
def process_items(items, limit=None):
    ...
```

## 3. Data Structures & Models

### Guidelines

- Use **dataclasses** (with `slots=True`) for DTOs and value objects
- Use **Pydantic** for API request/response models requiring validation
- Prefer **composition** over inheritance for building complex objects
- Use **appropriate data structures** for performance (`set`/`dict` for O(1) lookups)

### Example

```python
from dataclasses import dataclass

@dataclass(slots=True)
class UserResult:
    user_id: str
    name: str
    email: str | None = None
```

## 4. Documentation

### Docstrings (PEP 257)

- **Required for**: All public modules, classes, and functions
- **Format**: Use consistent format (Google-style recommended)
- **Content**: Describe purpose, arguments, return values, and exceptions

### Comments

- Explain the **"why"**, not the **"what"**
- Remove commented-out code before PR submission
- Keep comments up-to-date with code changes

### Example

```python
def calculate_score(attempts: list[int], threshold: int) -> float:
    """Calculate the normalized score from test attempts.

    Filters attempts above the threshold and computes a weighted average.
    Uses exponential decay to weight recent attempts more heavily.

    Args:
        attempts: List of attempt scores (0-100).
        threshold: Minimum score to include in calculation.

    Returns:
        Normalized score between 0.0 and 1.0.

    Raises:
        ValueError: If attempts list is empty.
    """
    ...
```

## 5. Error Handling & Exceptions

### Requirements

- **No bare `except:` blocks** - always catch specific exceptions
- **Never silently ignore exceptions** - at minimum, log them
- **Use specific exception types** from the standard library or custom exceptions
- **Handle errors at the appropriate level** - don't catch too early or too late

### Examples

```python
# Good
try:
    result = process_data(data)
except ValidationError as e:
    logger.error(f"Validation failed: {e}")
    raise
except ConnectionError:
    logger.warning("Connection lost, retrying...")
    return retry_with_backoff()

# Bad - bare except, silent failure
try:
    result = process_data(data)
except:
    pass
```

## 6. Security Considerations

### Critical Rules

- **No hardcoded secrets**: API keys, passwords, tokens must come from environment variables or secrets manager
- **Input validation**: Never trust user-supplied data; always validate and sanitize
- **SQL injection prevention**: Use parameterized queries, never string concatenation
- **Avoid dangerous functions**: `eval()`, `exec()`, `pickle` with untrusted data
- **Use `secrets` module**: For cryptographic randomness, not `random`

### Example

```python
# Good - secret from environment
api_key = os.environ.get("API_KEY")

# Bad - hardcoded secret
api_key = "sk-abc123xyz789"
```

## 7. Concurrency & Performance

### Concurrency Model Selection

| Task Type       | Recommended Approach | Use Case                                    |
|-----------------|---------------------|---------------------------------------------|
| I/O-bound       | `asyncio`           | Network requests, database operations       |
| I/O-bound (blocking libs) | `threading` | Integration with blocking libraries     |
| CPU-bound       | `multiprocessing`   | Heavy computation, bypasses GIL            |

### Performance Best Practices

- Use **f-strings** or `''.join()` for string concatenation in loops
- Use **comprehensions** and **generator expressions** for collection creation
- Prefer **built-in functions** (`sum()`, `any()`, `all()`) over manual loops
- Avoid redundant operations inside loops

## 8. Code Organization & Architecture

### Principles

- **No code duplication**: Reuse existing functionality; extract common logic
- **Single Responsibility**: Each function/class should have one clear purpose
- **Composition over inheritance**: Build complex objects from simpler ones
- **Pattern matching**: Use `match...case` for complex conditionals when it improves readability

### Import Organization

- Standard library imports first
- Third-party imports second
- Local/project imports last
- Each group separated by a blank line
- Alphabetically sorted within groups

## 9. Testing & Testability

### Guidelines

- New/modified code should have corresponding unit tests
- Tests should be isolated and repeatable
- Use meaningful test names that describe the scenario
- Mock external dependencies appropriately

## 10. Project-Specific Rules

### SPDX License Header

All new Python files must include:

```python
# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0
```

### Virtual Environments

- Always use a virtual environment for isolation
- Manage dependencies with `requirements.in` (abstract) and `requirements.txt` (pinned)

### Git Branch

- Main branch is `main`
- Never commit directly to main without PR review

---

## Review Comment Severity Levels

When adding review comments, use these severity indicators:

| Severity | Prefix | Description |
|----------|--------|-------------|
| 🔴 **Critical** | `[CRITICAL]` | Must fix before merge (security, correctness, breaking) |
| 🟠 **Major** | `[MAJOR]` | Should fix (code quality, maintainability) |
| 🟡 **Minor** | `[MINOR]` | Nice to fix (style, optimization) |
| 💡 **Suggestion** | `[SUGGESTION]` | Optional improvement or alternative approach |
| ❓ **Question** | `[QUESTION]` | Request for clarification or explanation |
