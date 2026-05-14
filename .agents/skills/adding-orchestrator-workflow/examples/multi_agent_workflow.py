# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

"""
Example of a multi-agent workflow where results from one agent
are passed to another agent for further processing.
"""

from fastapi import Depends, Request

from common.models import AgentExecutionError
from orchestrator.main import (
    _get_artifacts_from_task,
    _get_model_from_artifacts,
    _handle_exception,
    _send_task_to_agent,
    _validate_api_key,
    orchestrator_app,
)


# Example result models - add these to common/models.py
# class Step1ResultModel(BaseAgentResult):
#     intermediate_data: str = Field(description="Data from step 1")
#
# class Step2ResultModel(BaseAgentResult):
#     final_result: str = Field(description="Final processed result")


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
    step2_result = _get_model_from_artifacts(
        _get_artifacts_from_task(step2_task, "Step 2"),
        "Step 2",
        Step2ResultModel
    )
    
    if isinstance(step2_result, AgentExecutionError):
        _handle_exception(f"Step 2 failed: {step2_result.error_message}")
    
    return {"message": "Multi-step workflow completed", "result": step2_result}
