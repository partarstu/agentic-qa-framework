---
name: adding-orchestrator-workflow
description: Adds new workflow endpoints to the QuAIA orchestrator. Use when creating new FastAPI endpoints that coordinate agent tasks, handle webhooks, or expose new API functionality.
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

📄 **Template:** [resources/models_template.py](resources/models_template.py)

### Step 2: Define the Response Model (if needed)

If the workflow returns structured data beyond simple status messages, add a response model (also in the template above).

### Step 3: Create the Endpoint Function

Add your endpoint in `orchestrator/main.py`:

📄 **Template:** [resources/endpoint_template.py](resources/endpoint_template.py)

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

📄 **Example:** [examples/multi_agent_workflow.py](examples/multi_agent_workflow.py)

### Step 6: Parallel Agent Execution

For workflows that can process items in parallel:

📄 **Example:** [examples/parallel_execution.py](examples/parallel_execution.py)

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

📄 **Example:** [examples/test_endpoint_example.py](examples/test_endpoint_example.py)

## Complete Workflow Example

For a full example including models and endpoint:

📄 **Example:** [examples/complete_workflow.py](examples/complete_workflow.py)

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
