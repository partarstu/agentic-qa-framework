# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

"""
Complete example of a data processing workflow.

This shows the full implementation including:
- Request/Response models in common/models.py
- Endpoint function in orchestrator/main.py
"""

# =============================================================================
# Add to common/models.py
# =============================================================================

from pydantic import Field

from common.models import BaseAgentResult, JsonSerializableModel


class DataProcessingRequest(JsonSerializableModel):
    """Request to process data items."""
    project_key: str = Field(description="The project to process data for")
    item_ids: list[str] = Field(description="List of item IDs to process")


class DataProcessingResult(BaseAgentResult):
    """Result of data processing."""
    processed_count: int = Field(description="Number of items processed")
    results: list[str] = Field(description="Processing results")


# =============================================================================
# Add to orchestrator/main.py
# =============================================================================

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
