# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

"""
Basic endpoint function template for orchestrator workflows.

Add this to orchestrator/main.py.
Replace placeholders with your workflow-specific values.
"""

from fastapi import Depends

from common.models import AgentExecutionError
from orchestrator.main import (
    _get_artifacts_from_task,
    _get_model_from_artifacts,
    _handle_exception,
    _send_task_to_agent,
    _validate_api_key,
    _validate_task_status,
    logger,
    orchestrator_app,
)


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
        # text_parts = _get_text_content_from_artifacts(received_artifacts, task_description)
        
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
