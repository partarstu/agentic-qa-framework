---
name: Adding a New Orchestrator Workflow
description: Step-by-step guide for adding new workflow endpoints to the QuAIA orchestrator
---

# Adding a New Orchestrator Workflow

This skill provides a comprehensive guide for adding new workflow endpoints to the QuAIA™ orchestrator. Workflows are FastAPI endpoints that trigger and coordinate agent tasks.

## Overview

The orchestrator (`orchestrator/main.py`) exposes HTTP endpoints that:
1. Receive external requests (webhooks, API calls)
2. Route tasks to appropriate agents
3. Coordinate multi-agent workflows
4. Handle results and trigger follow-up actions

## Workflow Architecture

A typical orchestrator workflow:
1. Receives a request (POST/GET endpoint)
2. Extracts relevant data from the request
3. Sends task(s) to agent(s) using `_send_task_to_agent()`
4. Parses the agent response using helper functions
5. Optionally triggers follow-up workflows
6. Returns the result to the caller

## Step-by-Step Instructions

### Step 1: Define the Request Model (if needed)

If your endpoint accepts structured input, create a request model in `common/models.py`:

```python
class <WorkflowName>Request(JsonSerializableModel):
    """Request to trigger <workflow description>."""
    
    field_name: str = Field(description="Description of this field")
    # Add other required fields
```

### Step 2: Define the Response Model (if needed)

If the workflow returns structured data beyond simple status messages, add a response model:

```python
class <WorkflowName>Result(BaseAgentResult):
    """Result from <workflow description>."""
    
    result_field: str = Field(description="Description of this field")
    # Add other fields as needed
```

### Step 3: Create the Endpoint Function

Add your endpoint in `orchestrator/main.py`. Follow this pattern:

```python
# noinspection PyUnusedLocal
@orchestrator_app.post("/<endpoint-path>")
async def <endpoint_function_name>(request: <RequestModel>, api_key: str = Depends(_validate_api_key)):
    """
    Brief description of what this endpoint does.
    
    Args:
        request: The request payload.
        api_key: API key for authentication (automatically validated).
        
    Returns:
        Dictionary with status message and any relevant data.
    """
    logger.info(f"Received request for <workflow description>: {request}")
    
    try:
        # 1. Extract data from request
        data = request.field_name
        
        # 2. Send task to agent
        task_description = "<Description for agent selection>"
        completed_task = await _send_task_to_agent(
            f"<Task payload for agent>",  # What the agent should process
            task_description              # Used for agent selection
        )
        
        # 3. Validate and extract results
        _validate_task_status(completed_task, task_description)
        received_artifacts = _get_artifacts_from_task(completed_task, task_description)
        
        # 4. Parse results based on expected format
        # Option A: Get raw text
        text_parts = _get_text_content_from_artifacts(received_artifacts, task_description)
        
        # Option B: Parse as model
        result = _get_model_from_artifacts(received_artifacts, task_description, <ResultModel>)
        
        # 5. Handle AgentExecutionError if using _get_model_from_artifacts
        if isinstance(result, AgentExecutionError):
            _handle_exception(f"Workflow failed: {result.error_message}")
        
        # 6. Optionally trigger follow-up workflows
        # await _some_follow_up_workflow(result)
        
        logger.info(f"<Workflow name> completed successfully")
        return {"message": "Workflow completed successfully", "result": result}
        
    except Exception as e:
        _handle_exception(f"<Workflow name> failed: {e}")
```

### Step 4: Helper Functions Reference

The orchestrator provides these helper functions for working with agent tasks:

#### Sending Tasks to Agents

```python
# Send a text task to an automatically selected agent
completed_task = await _send_task_to_agent(
    task_content: str,      # The payload/content for the agent
    task_description: str   # Used to select the appropriate agent
) -> Task

# Send a message with file attachments
completed_task = await _send_task_to_agent_with_message(
    message: Message,       # A2A Message with text and file parts
    task_description: str
) -> Task
```

#### Parsing Agent Responses

```python
# Validate task completed successfully
_validate_task_status(task: Task, task_description: str)

# Extract artifacts from task (raises exception if none)
artifacts = _get_artifacts_from_task(task: Task, task_description: str) -> list[Artifact]

# Extract text content from artifacts
text_parts = _get_text_content_from_artifacts(
    artifacts: list[Artifact],
    task_description: str,
    any_content_expected: bool = True  # Set False if empty is OK
) -> list[str]

# Parse artifacts as a Pydantic model (also handles AgentExecutionError)
result = _get_model_from_artifacts(
    artifacts: list[Artifact],
    task_description: str,
    model_type: type[T]
) -> T | AgentExecutionError | None

# Extract file artifacts (screenshots, logs, etc.)
files = _get_file_contents_from_artifacts(artifacts: list[Artifact]) -> list[FileWithBytes]
```

#### Error Handling

```python
# Raise HTTPException with consistent error handling and logging
_handle_exception(error_message: str, status_code: int = 500)
```

### Step 5: Multi-Agent Workflows

For workflows that involve multiple agents in sequence:

```python
@orchestrator_app.post("/multi-step-workflow")
async def multi_step_workflow(request: Request, api_key: str = Depends(_validate_api_key)):
    """Example of a multi-agent workflow."""
    
    # Step 1: First agent task
    step1_task = await _send_task_to_agent(
        "Input for step 1",
        "First processing step"
    )
    step1_result = _get_model_from_artifacts(
        _get_artifacts_from_task(step1_task, "Step 1"),
        "Step 1",
        Step1ResultModel
    )
    
    if isinstance(step1_result, AgentExecutionError):
        _handle_exception(f"Step 1 failed: {step1_result.error_message}")
    
    # Step 2: Second agent task using results from step 1
    step2_task = await _send_task_to_agent(
        f"Process these results: {step1_result}",
        "Second processing step"
    )
    # ... parse step2 results ...
    
    return {"message": "Multi-step workflow completed"}
```

### Step 6: Parallel Agent Execution

For workflows that can process items in parallel:

```python
async def _process_items_in_parallel(items: list[SomeItem]) -> list[Result]:
    """Process multiple items using parallel agent tasks."""
    
    async def _process_single_item(item: SomeItem) -> Result:
        """Helper coroutine for processing a single item."""
        task = await _send_task_to_agent(
            item.model_dump_json(),
            f"Process item {item.id}"
        )
        # Parse and return result
        return _parse_result(task)
    
    # Execute all tasks in parallel
    results = await asyncio.gather(
        *[_process_single_item(item) for item in items],
        return_exceptions=True  # Continue on individual failures
    )
    
    # Filter successful results and log failures
    successful_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"Failed to process item {i}: {result}")
        else:
            successful_results.append(result)
    
    return successful_results
```

### Step 7: Using Execution Lock (Optional)

For workflows that should not run concurrently (e.g., test execution):

```python
@orchestrator_app.post("/exclusive-workflow")
async def exclusive_workflow(request: Request, api_key: str = Depends(_validate_api_key)):
    """Workflow that requires exclusive access."""
    
    async with execution_lock:  # Only one instance runs at a time
        # ... workflow logic ...
        return {"message": "Exclusive workflow completed"}
```

### Step 8: Add Webhook URL Configuration (Optional)

If the endpoint will be called via webhooks, add the URL to `config.py`:

```python
# Webhook URLs
<WORKFLOW_NAME>_WEBHOOK_URL = f"{ORCHESTRATOR_URL}/<endpoint-path>"
```

### Step 9: Update README Documentation

Add documentation for the new endpoint in `README.md` under "Invoking Orchestrator Workflows":

```markdown
### <Workflow Name>

Description of what this workflow does.

* **Endpoint:** `POST /<endpoint-path>`
  
  Example payload:
  ```json
  {
      "field_name": "value"
  }
  ```
  
  Response:
  ```json
  {
      "message": "Workflow completed successfully",
      "result": { ... }
  }
  ```
```

### Step 10: Create Unit Tests

Create test cases in `tests/orchestrator/test_endpoints.py` or a new file:

```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from orchestrator.main import orchestrator_app


@pytest.fixture
def client():
    return TestClient(orchestrator_app)


@pytest.fixture
def mock_api_key(monkeypatch):
    """Allow requests without API key check."""
    monkeypatch.setattr("orchestrator.main._validate_api_key", lambda x=None: None)


@pytest.mark.asyncio
async def test_<workflow_name>_success(client, mock_api_key):
    with patch("orchestrator.main._send_task_to_agent") as mock_send:
        # Setup mock response
        mock_task = MagicMock()
        mock_task.status.state = "completed"
        mock_task.artifacts = [...]  # Mock artifacts
        mock_send.return_value = mock_task
        
        response = client.post(
            "/<endpoint-path>",
            json={"field_name": "value"}
        )
        
        assert response.status_code == 200
        assert "message" in response.json()


@pytest.mark.asyncio
async def test_<workflow_name>_agent_error(client, mock_api_key):
    with patch("orchestrator.main._send_task_to_agent") as mock_send:
        mock_send.side_effect = Exception("Agent unavailable")
        
        response = client.post(
            "/<endpoint-path>",
            json={"field_name": "value"}
        )
        
        assert response.status_code == 500
```

## Complete Workflow Example

Here's a complete example of a simple workflow:

```python
# In common/models.py
class DataProcessingRequest(JsonSerializableModel):
    """Request to process data items."""
    project_key: str = Field(description="The project to process data for")
    item_ids: list[str] = Field(description="List of item IDs to process")


class DataProcessingResult(BaseAgentResult):
    """Result of data processing."""
    processed_count: int = Field(description="Number of items processed")
    results: list[str] = Field(description="Processing results")


# In orchestrator/main.py
@orchestrator_app.post("/process-data")
async def process_data(request: DataProcessingRequest, api_key: str = Depends(_validate_api_key)):
    """
    Process data items for a project.
    """
    logger.info(f"Starting data processing for project {request.project_key}")
    
    try:
        task_description = "Process data items"
        completed_task = await _send_task_to_agent(
            request.model_dump_json(),
            task_description
        )
        
        _validate_task_status(completed_task, task_description)
        artifacts = _get_artifacts_from_task(completed_task, task_description)
        result = _get_model_from_artifacts(artifacts, task_description, DataProcessingResult)
        
        if isinstance(result, AgentExecutionError):
            _handle_exception(f"Data processing failed: {result.error_message}")
        
        logger.info(f"Data processing completed: {result.processed_count} items")
        return {
            "message": "Data processing completed",
            "processed_count": result.processed_count,
            "results": result.results
        }
        
    except Exception as e:
        _handle_exception(f"Data processing failed: {e}")
```

## Verification Checklist

After adding the workflow, verify:

- [ ] Request model (if any) added to `common/models.py`
- [ ] Response model (if any) added to `common/models.py`
- [ ] Endpoint function follows the standard pattern
- [ ] Proper error handling with `_handle_exception()`
- [ ] API key validation via `Depends(_validate_api_key)`
- [ ] Logging at key points (start, completion, errors)
- [ ] Unit tests cover success and failure cases
- [ ] Documentation updated in README.md
- [ ] Tests pass: `pytest tests/orchestrator/ -v`
- [ ] Endpoint accessible: `curl -X POST http://localhost:8000/<endpoint-path> -d '...'`
