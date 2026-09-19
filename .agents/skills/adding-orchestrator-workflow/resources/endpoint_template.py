# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""
Workflow endpoint template.

Paste into orchestrator/main.py, where every name used below is already defined or imported.
Replace the <placeholders>. For a Jira webhook, take `request: Request` instead of a model and start the `try`
block with `await _verify_jira_webhook_signature(request)`.
"""


# noinspection PyUnusedLocal
@orchestrator_app.post("/<endpoint-path>")
async def <endpoint_function_name>(request: <RequestModel>, api_key: str = Depends(_validate_api_key)):
    """
    <What the workflow does and who triggers it>.
    """
    try:
        logger.info("Received a request for <workflow description>: %s", request)
        task_description = f"<Description the orchestrator uses to select the agent>"
        completed_task = await _send_task_to_agent(request.model_dump_json(), task_description)
        artifacts = _get_artifacts_from_task(completed_task, task_description)
        result = _get_model_from_artifacts(artifacts, task_description, <ResultModel>)
        if isinstance(result, AgentExecutionError):
            _handle_exception(f"<Workflow name> failed: {result.error_message}")
        logger.info("<Workflow name> completed.")
        return {"message": "<Workflow name> completed.", "result": result.model_dump()}
    except HTTPException:
        raise
    except Exception as e:
        _handle_exception(f"<Workflow name> failed: {e}")
