# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

import asyncio
import time
import traceback
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4

import httpx
import uvicorn
from a2a.client import ClientFactory, ClientConfig
from a2a.types import TaskState, AgentCard, Artifact, Task, JSONRPCErrorResponse, TextPart, FilePart, FileWithBytes, \
    Message, TaskIdParams
from a2a.utils import new_agent_text_message, get_message_text
from fastapi import FastAPI, Request, HTTPException, Security, Depends, Query
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from pydantic_ai import Agent
from pydantic_ai.settings import ModelSettings

import config
from common import utils
from common.custom_llm_wrapper import CustomLlmWrapper
from common.models import SelectedAgent, GeneratedTestCases, TestCase, ProjectExecutionRequest, TestExecutionResult, \
    TestExecutionRequest, SelectedAgents, JsonSerializableModel, IncidentCreationInput, IncidentCreationResult
from common.services.test_management_system_client_provider import get_test_management_client
from common.services.test_reporting_client_base_provider import get_test_reporting_client
from common.services.vector_db_service import VectorDbService
from orchestrator.auth import auth_service, dashboard_auth, LoginRequest, TokenResponse
from orchestrator.dashboard_service import dashboard_service
from orchestrator.memory_log_handler import setup_memory_logging
from orchestrator.models import (
    AgentStatus, BrokenReason, TaskStatus, TaskRecord, ErrorRecord,
    agent_registry, task_history, error_history
)

MAX_RETRIES = 3

MODEL_SETTINGS = ModelSettings(top_p=config.TOP_P, temperature=config.TEMPERATURE)

logger = utils.get_logger("orchestrator")

# Set up memory logging for dashboard
setup_memory_logging("orchestrator")

# Initialize Vector DB Service for Orchestrator
vector_db_service = VectorDbService(getattr(config.QdrantConfig, "COLLECTION_NAME", "jira_issues"))
execution_lock = asyncio.Lock()
agent_selection_lock = asyncio.Lock()  # Ensures atomic agent selection and reservation
cancellation_queue = asyncio.Queue()

API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)


# noinspection PyUnusedLocal
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Orchestrator starting up...")

    # Perform initial agent discovery before accepting requests
    logger.info("Starting initial agent discovery...")
    try:
        await _discover_agents()
        logger.info("Initial agent discovery finished.")
    except Exception as e:
        logger.error(f"Initial agent discovery failed: {e}")

    # Start periodic tasks after initial discovery
    discovery_task = asyncio.create_task(periodic_agent_discovery())
    cancellation_task = asyncio.create_task(_retry_cancellation_task())

    yield

    logger.info("Orchestrator shutting down.")
    if not discovery_task.cancel():
        try:
            await discovery_task
        except asyncio.CancelledError:
            logger.info("Agent discovery task successfully cancelled.")

    if not cancellation_task.cancel():
        try:
            await cancellation_task
        except asyncio.CancelledError:
            logger.info("Cancellation retry task successfully cancelled.")


def _validate_api_key(api_key: str = Security(api_key_header)):
    if config.OrchestratorConfig.API_KEY and api_key != config.OrchestratorConfig.API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid API Key")


orchestrator_app = FastAPI(lifespan=lifespan)


# =============================================================================
# Dashboard Authentication Routes
# =============================================================================

@orchestrator_app.post("/api/auth/login", response_model=TokenResponse)
async def login(request: LoginRequest):
    """Authenticate user and return a JWT token."""
    if not auth_service.authenticate(request.username, request.password):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return auth_service.create_token(request.username)


@orchestrator_app.post("/api/auth/logout")
async def logout():
    """Logout endpoint (client-side token removal)."""
    return {"message": "Logged out successfully"}


@orchestrator_app.get("/api/auth/verify")
async def verify_token(username: str = Depends(dashboard_auth)):
    """Verify if the current token is valid."""
    return {"valid": True, "username": username}


# =============================================================================
# Dashboard API Routes (for Web UI) - Protected by JWT Auth
# =============================================================================

@orchestrator_app.get("/api/dashboard/summary")
async def get_dashboard_summary(_: str = Depends(dashboard_auth)):
    """Get high-level dashboard statistics."""
    return await dashboard_service.get_summary()


@orchestrator_app.get("/api/dashboard/agents")
async def get_agents_status(_: str = Depends(dashboard_auth)):
    """Get detailed status of all registered agents."""
    return await dashboard_service.get_agents_status()


@orchestrator_app.get("/api/dashboard/tasks")
async def get_recent_tasks(limit: int = Query(default=50, le=100), _: str = Depends(dashboard_auth)):
    """Get recent tasks with their details."""
    return await dashboard_service.get_recent_tasks(limit=limit)


@orchestrator_app.get("/api/dashboard/errors")
async def get_recent_errors(limit: int = Query(default=20, le=50), _: str = Depends(dashboard_auth)):
    """Get recent errors with context."""
    return await dashboard_service.get_recent_errors(limit=limit)


@orchestrator_app.get("/api/dashboard/logs")
async def get_logs(
        limit: int = Query(default=100, le=500),
        level: Optional[str] = Query(default=None, description="Filter by log level (INFO, WARNING, ERROR)"),
        task_id: Optional[str] = Query(default=None, description="Filter by task ID"),
        agent_id: Optional[str] = Query(default=None, description="Filter by agent ID"),
        _: str = Depends(dashboard_auth)
):
    """Get recent application logs."""
    return await dashboard_service.get_logs(limit=limit, level=level, task_id=task_id, agent_id=agent_id)


async def _retry_cancellation_task():
    """Background task to recover broken agents.
    
    This task handles two types of broken agents differently:
    - OFFLINE: Agent was unreachable. Recovery = agent responds to card fetch.
    - TASK_STUCK: Agent is reachable but a task timed out. Recovery = cancel the stuck task first.
    """
    logger.info("Starting broken agent recovery task.")
    while True:
        try:
            agent_id, timestamp = await cancellation_queue.get()

            # If it's been more than 24 hours, give up
            if time.time() - timestamp > 24 * 3600:
                logger.warning(f"Gave up recovering agent {agent_id} after 24 hours.")
                cancellation_queue.task_done()
                continue

            broken_reason, stuck_task_id = await agent_registry.get_broken_context(agent_id)
            agent_card = await agent_registry.get_card(agent_id)

            if not agent_card:
                logger.warning(f"Agent {agent_id} no longer has a registered card. Skipping recovery.")
                cancellation_queue.task_done()
                continue

            logger.info(f"Attempting to recover agent {agent_id} (reason: {broken_reason})...")

            is_recovered = False

            if broken_reason == BrokenReason.OFFLINE:
                # For OFFLINE agents: check if they respond to card fetch
                if await _fetch_agent_card(agent_card.url):
                    logger.info(f"Agent {agent_id} is back online.")
                    is_recovered = True
                else:
                    logger.debug(f"Agent {agent_id} is still offline.")

            elif broken_reason == BrokenReason.TASK_STUCK:
                # For TASK_STUCK agents: attempt to cancel the stuck task first
                if stuck_task_id:
                    cancel_success = await _cancel_agent_task(agent_card, stuck_task_id)
                    if cancel_success:
                        logger.info(f"Successfully cancelled stuck task {stuck_task_id} on agent {agent_id}.")
                        is_recovered = True
                    else:
                        # Cancellation failed - check if agent is at least responsive
                        if await _fetch_agent_card(agent_card.url):
                            logger.warning(
                                f"Could not cancel task {stuck_task_id} on agent {agent_id}, "
                                f"but agent is responsive. Marking as available anyway."
                            )
                            is_recovered = True
                        else:
                            # Agent is now offline, update reason
                            logger.warning(f"Agent {agent_id} is no longer reachable. Updating to OFFLINE.")
                            await agent_registry.update_status(
                                agent_id, AgentStatus.BROKEN, BrokenReason.OFFLINE
                            )
                else:
                    # No stuck task ID tracked, just check if agent responds
                    if await _fetch_agent_card(agent_card.url):
                        logger.info(f"Agent {agent_id} is responsive (no task ID to cancel).")
                        is_recovered = True

            else:
                # Unknown or None reason - fall back to simple reachability check
                if await _fetch_agent_card(agent_card.url):
                    logger.info(f"Agent {agent_id} is responsive.")
                    is_recovered = True

            if is_recovered:
                logger.info(f"Agent {agent_id} successfully recovered. Marking AVAILABLE.")
                await agent_registry.update_status(agent_id, AgentStatus.AVAILABLE)
                cancellation_queue.task_done()
            else:
                logger.info(f"Agent {agent_id} not recovered yet. Will retry in 60 seconds.")
                cancellation_queue.task_done()
                await asyncio.sleep(60)
                await cancellation_queue.put((agent_id, timestamp))

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception(f"Error in broken agent recovery task.")
            await asyncio.sleep(5)


async def _cancel_agent_task(agent_card: AgentCard, task_id: str) -> bool:
    """Attempt to cancel a task on an agent using the A2A protocol.
    
    Args:
        agent_card: The agent's card containing connection info.
        task_id: The ID of the task to cancel.
        
    Returns:
        True if cancellation was successful or acknowledged, False otherwise.
    """
    try:
        async with httpx.AsyncClient(timeout=config.OrchestratorConfig.AGENT_DISCOVERY_TIMEOUT_SECONDS) as client:
            client_config = ClientConfig(httpx_client=client)
            client_factory = ClientFactory(config=client_config)
            a2a_client = client_factory.create(card=agent_card)

            cancelled_task = await a2a_client.cancel_task(TaskIdParams(id=task_id))

            # Check if cancellation was accepted
            if not cancelled_task.status:
                logger.warning(f"Task got no status, artefacts: {cancelled_task.artifacts}")
                return False
            if cancelled_task.status.state != TaskState.canceled:
                logger.warning(f"Task cancellation failed: got status {cancelled_task.status.state} and "
                               f"message {cancelled_task.status.message}")
                return False

            logger.info(f"Task {task_id} cancellation request sent successfully.")
            return True

    except Exception as e:
        logger.warning(f"Failed to cancel task {task_id}: {e}")
        return False


# --- For selecting the single best for the task agent ---
discovery_agent = Agent(
    model=CustomLlmWrapper(wrapped=config.OrchestratorConfig.MODEL_NAME),
    output_type=SelectedAgent,
    instructions="You are an intelligent orchestrator specialized on routing the target task to one of the agents "
                 "which are registered with you. Your task is to select one agent to handle the target "
                 "task based on the description of this task and the list of all available candidate agents "
                 " (this list has the info about the capabilities of each agent). If there is no agent that can "
                 "execute the target task, return an empty string.",
    name="Discovery Agent",
    model_settings=MODEL_SETTINGS,
    retries=MAX_RETRIES,
    output_retries=MAX_RETRIES
)

# --- For selecting ALL suitable for the task agents ---
multi_discovery_agent = Agent(
    model=CustomLlmWrapper(wrapped=config.OrchestratorConfig.MODEL_NAME),
    output_type=SelectedAgents,
    instructions="You are an intelligent orchestrator specialized on routing tasks. Your task is to select all agents "
                 "that can handle the target task based on the task's description and a list of available agents. "
                 "If no agents can execute the task, return an empty list.",
    name="Multi-Discovery Agent",
    model_settings=MODEL_SETTINGS,
    retries=MAX_RETRIES,
    output_retries=MAX_RETRIES
)


# --- For mapping between input in unknown format and output in structured format ---
def _get_results_extractor_agent(output_type: type[JsonSerializableModel] | type[str]):
    return Agent(
        model=CustomLlmWrapper(wrapped=config.OrchestratorConfig.MODEL_NAME),
        output_type=output_type,
        instructions="You are an intelligent agent specialized on extracting the structured information based on the input "
                     "provided to you. Your task is to analyze the provided to you input, identify the requested "
                     "information inside of this input and return it in a format which is requested by the user. If you've "
                     "identified no matching information inside of the provided to you input, return an empty result.",
        name="Results Extractor Agent",
        model_settings=MODEL_SETTINGS,
        retries=MAX_RETRIES,
        output_retries=MAX_RETRIES
    )


async def periodic_agent_discovery():
    """Periodically discovers agents after the initial startup discovery."""
    while True:
        # Wait before the next discovery cycle (initial discovery is done during startup)
        await asyncio.sleep(config.OrchestratorConfig.AGENTS_DISCOVERY_INTERVAL_SECONDS)
        try:
            logger.info("Starting periodic agent discovery...")
            await _discover_agents()
            logger.info("Periodic agent discovery finished.")
        except Exception as e:
            _handle_exception(f"An error occurred during periodic agent discovery: {e}")


# noinspection PyUnusedLocal
@orchestrator_app.post("/new-requirements-available")
async def review_jira_requirements(request: Request, api_key: str = Depends(_validate_api_key)):
    """
    Receives webhook from Jira and triggers the requirements review.
    """
    logger.info("Received an event from Jira, requesting requirements review from an agent.")
    user_story_id = await _get_jira_issue_key_from_request(request)
    task_description = "Review the Jira user story"
    completed_task = await _send_task_to_agent(f"Jira user story with key {user_story_id}",
                                               task_description)
    _validate_task_status(completed_task, f"Review of the user story {user_story_id}")
    logger.info("Received response from an agent, requirements review seems to be complete.")
    return {"message": f"Review of the requirements for Jira user story {user_story_id} completed."}


# noinspection PyUnusedLocal
@orchestrator_app.post("/story-ready-for-test-case-generation")
async def trigger_test_case_generation_workflow(request: Request, api_key: str = Depends(_validate_api_key)):
    """
    Receives webhook from Jira and triggers the test case generation.
    """
    logger.info("Received an event from Jira, requesting test case generation from an agent.")
    user_story_id = await _get_jira_issue_key_from_request(request)
    generated_test_cases = await _request_test_cases_generation(user_story_id)
    if not generated_test_cases:
        _handle_exception(
            "Test case generation agent responded provided no generated test cases in its response.")

    logger.info(
        f"Got {len(generated_test_cases.test_cases)} generated test cases, requesting their classification.")
    await _request_test_cases_classification(generated_test_cases.test_cases, user_story_id)
    logger.info("Received response from an agent, test case classification seems to be complete.")

    logger.info("Requesting review of all generated test cases.")
    await _request_test_cases_review(generated_test_cases.test_cases, user_story_id)
    logger.info("Received response from an agent, test case review seems to be complete.")

    return {
        "message": f"Test case generation and classification for Jira user story {user_story_id} completed."
    }


# noinspection PyUnusedLocal
@orchestrator_app.post("/update-rag-db")
async def update_rag_db(request: ProjectExecutionRequest, api_key: str = Depends(_validate_api_key)):
    """
    Triggers the RAG Vector DB update for the given project.
    """
    project_key = request.project_key
    logger.info(f"Starting RAG update for project {project_key}")
    try:
        task_description = "Update RAG Vector DB with Jira issues"
        completed_task = await _send_task_to_agent(f"Sync all Jira issues for project '{project_key}'",
                                                   task_description)

        _validate_task_status(completed_task, task_description)
        received_artifacts = _get_artifacts_from_task(completed_task, task_description)
        text_content = _get_text_content_from_artifacts(received_artifacts, task_description)

        logger.info(f"RAG update completed: {text_content}")
        return {"message": "RAG update completed.", "details": text_content}
    except Exception as e:
        _handle_exception(f"RAG update failed: {e}")


# noinspection PyUnusedLocal
@orchestrator_app.post("/execute-tests")
async def execute_tests(request: ProjectExecutionRequest, api_key: str = Depends(_validate_api_key)):
    async with execution_lock:
        project_key = request.project_key
        logger.info(f"Received request to execute automated tests for project '{project_key}'.")
        test_management_client = get_test_management_client()
        automated_test_cases = []
        try:
            automated_tests_dict = test_management_client.fetch_ready_for_execution_test_cases_by_labels(
                project_key, [config.OrchestratorConfig.AUTOMATED_TC_LABEL])
            automated_test_cases = automated_tests_dict.get(config.OrchestratorConfig.AUTOMATED_TC_LABEL, [])
            if not automated_test_cases:
                logger.info(f"No test cases ready for execution found for project {project_key}.")
                return {"message": "No test cases found to execute."}
        except Exception as e:
            _handle_exception(f"Failed to fetch test cases for project {project_key}: {e}")

        logger.info(
            f"Retrieved {len(automated_test_cases)} test cases for automatic execution, grouping them by labels "
            f"and requesting execution for each group.")
        grouped_test_cases = await _group_test_cases_by_labels(automated_test_cases)
        if not grouped_test_cases:
            logger.info("No tests found which can be automated based on the label.")
            return {
                "message": f"No test cases with '{config.OrchestratorConfig.AUTOMATED_TC_LABEL}' label found."}

        all_execution_results = await _request_all_test_cases_execution(grouped_test_cases)
        logger.info(f"Collected execution results for {len(all_execution_results)} test cases.")

        # Request incident creation for all failed tests
        logger.info("Processing failed tests for incident creation.")
        await _request_incident_creation_for_failed_tests(all_execution_results)

        if all_execution_results:
            logger.info("Generating test execution report based on all execution results.")
            await _generate_test_report(all_execution_results, project_key, test_management_client)
        return {
            "message": f"Test execution completed for project {project_key}. Ran {len(all_execution_results)} tests."}


async def _generate_test_report(all_execution_results, project_key, test_management_client):
    test_cycle_name = f"Automated Test Execution - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    test_cycle_key = test_management_client.create_test_plan(project_key, test_cycle_name)
    test_management_client.create_test_execution(all_execution_results, project_key, test_cycle_key)
    reporting_client = get_test_reporting_client(str(Path(__file__).resolve().parent.parent.resolve()))
    reporting_client.generate_report(all_execution_results)


async def _request_incident_creation_for_failed_tests(
        all_execution_results: List[TestExecutionResult],
) -> None:
    """
    Process all failed test execution results and create incidents for each.

    Args:
        all_execution_results: List of all test execution results to process.
    """
    failed_results = [
        result for result in all_execution_results
        if result.testExecutionStatus in ["failed", "error"]
    ]

    if not failed_results:
        logger.info("No failed tests found. Skipping incident creation.")
        return

    logger.info(f"Found {len(failed_results)} failed test(s). Creating incidents in parallel.")

    async def _create_incident_for_result(result: TestExecutionResult) -> None:
        """Helper coroutine to create incident for a single failed test result."""
        logger.info(f"Test case {result.testCaseKey} failed. Initiating incident creation.")
        try:
            incident_input = IncidentCreationInput(
                test_case=result.test_case,
                test_execution_result=str(result.generalErrorMessage),
                test_step_results=result.stepResults,
                system_description=result.system_description,
                issue_priority_field_id=config.IncidentCreationAgentConfig.ISSUE_PRIORITY_FIELD_ID
            )

            incident_result = await _request_incident_creation(incident_input, result.artifacts or [])
            result.incident_creation_result = incident_result
            logger.info(
                f"Incident creation completed for test case {result.testCaseKey}. "
                f"Incident key: {incident_result.incident_key if incident_result else 'N/A'}"
            )
        except Exception as e:
            logger.exception(f"Failed to create incident for test case {result.testCaseKey}.")

    # Execute all incident creations in parallel
    await asyncio.gather(*[_create_incident_for_result(result) for result in failed_results])


async def _request_all_test_cases_execution(grouped_test_cases):
    label_to_agents_map = await _select_execution_agents_for_each_test_label(list(grouped_test_cases.keys()))
    execution_tasks = []
    for label, test_cases in grouped_test_cases.items():
        agent_ids = label_to_agents_map.get(label)
        if agent_ids:
            execution_tasks.append(_execute_test_group(label, test_cases, agent_ids))
        else:
            logger.warning(f"Skipping execution of test cases for label '{label}' as no suitable agents were found.")
    execution_results_nested = await asyncio.gather(*execution_tasks)
    all_execution_results = [result for group_results in execution_results_nested for result in group_results]
    return all_execution_results


async def _group_test_cases_by_labels(automated_test_cases):
    grouped_test_cases = defaultdict(list)
    for tc in automated_test_cases:
        for label in tc.labels:
            if label != config.OrchestratorConfig.AUTOMATED_TC_LABEL:
                grouped_test_cases[label].append(tc)
    return grouped_test_cases


async def _select_execution_agents_for_each_test_label(labels: List[str]) -> Dict[str, List[str]]:
    if await agent_registry.is_empty():
        logger.warning("Agent registry is empty. Cannot select any execution agents.")
        return {label: [] for label in labels}

    tasks = [_select_all_suitable_agent_ids(f"Execute tests having the following label: {label}") for label in labels]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    label_agent_mapping = {}
    for label, result in zip(labels, results):
        if isinstance(result, Exception):
            logger.error(f"Failed to select agents for label '{label}': {result}")
            label_agent_mapping[label] = []
        elif result:
            logger.info(f"Selected agent(s) {result} for label '{label}'.")
            label_agent_mapping[label] = result
        else:
            logger.warning(f"No suitable agents found for label '{label}'.")
            label_agent_mapping[label] = []
    return label_agent_mapping


async def _execute_test_group(test_type: str, test_cases: List[TestCase],
                              agent_ids: List[str]) -> List[TestExecutionResult]:
    # Filter agents that are actually in the registry
    valid_agent_ids = []
    for aid in agent_ids:
        if await agent_registry.contains(aid):
            valid_agent_ids.append(aid)

    agent_names = []
    for aid in valid_agent_ids:
        agent_names.append(await agent_registry.get_name(aid))

    logger.info(
        f"Starting execution of {len(test_cases)} tests for type: '{test_type}' using agents: {agent_names}")

    if not valid_agent_ids:
        logger.warning(f"No agents available for test type '{test_type}', skipping execution.")
        return []

    queue = asyncio.Queue()
    for tc in test_cases:
        queue.put_nowait((tc, test_type))

    results: List[TestExecutionResult] = []
    workers = []
    for agent_id in valid_agent_ids:
        workers.append(asyncio.create_task(_agent_worker(agent_id, queue, results, valid_agent_ids)))

    # Wait for all items in the queue to be processed
    await queue.join()

    # Cancel all workers
    for worker in workers:
        worker.cancel()

    # Wait for workers to finish cancelling
    await asyncio.gather(*workers, return_exceptions=True)

    return results


async def _agent_worker(agent_id: str, queue: asyncio.Queue, results: List[TestExecutionResult], pool_agent_ids: List[str]):
    logger.info(f"Agent worker started for agent {agent_id}")
    try:
        while True:
            status = await agent_registry.get_status(agent_id)
            if status != AgentStatus.AVAILABLE:
                if status == AgentStatus.BROKEN:
                    logger.warning(f"Agent {agent_id} is BROKEN. Worker stopping.")
                    break
                await asyncio.sleep(1)
                continue

            test_case, test_type = await queue.get()
            try:
                result = await _execute_single_test(agent_id, test_case, test_type)
                if result:
                    results.append(result)
            except Exception as e:
                logger.exception(f"Error in worker for agent {agent_id}.")
                # Mark agent as BROKEN - task execution failed
                await agent_registry.update_status(
                    agent_id, AgentStatus.BROKEN, BrokenReason.TASK_STUCK
                )

                # Check if any other agents in the pool are still alive (not BROKEN)
                any_agents_alive = False
                for other_id in pool_agent_ids:
                    if other_id != agent_id:
                        status = await agent_registry.get_status(other_id)
                        if status != AgentStatus.BROKEN:
                            any_agents_alive = True
                            break

                if any_agents_alive:
                    # Retry logic: Put back in queue
                    logger.info(f"Agent {agent_id} broken, but other agents available. Re-queueing task.")
                    queue.put_nowait((test_case, test_type))
                else:
                    # Last agent standing failed. Report error.
                    logger.error(f"All agents for this group are broken. Returning failed result for test case {test_case.key}.")
                    agent_name = await agent_registry.get_name(agent_id)
                    failed_result = TestExecutionResult(
                        stepResults=[],
                        testCaseKey=test_case.key,
                        testCaseName=test_case.name,
                        testExecutionStatus="error",
                        generalErrorMessage=f"All agents failed. Last error from {agent_name}: {e}",
                        start_timestamp=datetime.now().isoformat(),
                        end_timestamp=datetime.now().isoformat(),
                        system_description=f"Agent: {agent_name} (Failed - No Retry Available)",
                        test_case=test_case
                    )
                    results.append(failed_result)

                queue.task_done()
                break  # Exit worker as agent is broken
            queue.task_done()
    except asyncio.CancelledError:
        logger.info(f"Agent worker for {agent_id} cancelled.")
    except Exception as e:
        logger.exception(f"Unexpected error in agent worker {agent_id}: {e}")


async def _execute_single_test(agent_id: str, test_case: TestCase,
                               test_type: str) -> TestExecutionResult | None:
    task_description = f"Execution of test case {test_case.key} (type: {test_type})"
    execution_request = TestExecutionRequest(test_case=test_case)
    artifacts = []
    start_timestamp = datetime.now()
    try:
        completed_task = await _send_task_to_agent(agent_id, execution_request.model_dump_json(), task_description)
        artifacts = _get_artifacts_from_task(completed_task, task_description)
    except Exception as e:
        _handle_exception(f"Failed to execute test case {test_case.key}. Error: {e}", 500)
    finally:
        end_timestamp = datetime.now()

    agent_name = await agent_registry.get_name(agent_id)
    if not artifacts:
        _handle_exception(f"No test case execution results received from agent {agent_name}", 500)
    text_results = _get_text_content_from_artifacts(artifacts, task_description)
    if not text_results:
        _handle_exception(f"No test case execution information received from agent {agent_name}",
                          500)
    user_prompt = f"""
Test case execution results:\n```{text_results}```
"""
    result = await _get_results_extractor_agent(TestExecutionResult).run(user_prompt)
    test_execution_result: TestExecutionResult = result.output
    if not test_execution_result:
        _handle_exception("Couldn't map the test execution results received from the agent to the expected format.")

    test_execution_result.testCaseKey = test_case.key
    if not test_execution_result.start_timestamp:
        test_execution_result.start_timestamp = start_timestamp.isoformat()
    if not test_execution_result.end_timestamp:
        test_execution_result.end_timestamp = end_timestamp.isoformat()
    # Extract file artifacts from agent response - logs are included as file parts by the agent
    file_artifacts = _get_file_contents_from_artifacts(artifacts)
    test_execution_result.artifacts = file_artifacts

    if not test_execution_result.system_description:
        test_execution_result.system_description = f"Agent: {agent_name}, Environment: Standard Test Environment"

    test_execution_result.test_case = test_case

    logger.info(f"Executed test case {test_case.key}. Status: {test_execution_result.testExecutionStatus}")
    return test_execution_result


async def _request_incident_creation(
        incident_input: IncidentCreationInput,
        artifacts: List[FileWithBytes]
) -> IncidentCreationResult:
    """Request incident creation with all artifacts sent as file parts.
    
    Args:
        incident_input: The incident creation input JSON.
        artifacts: All file artifacts to send as file parts in the A2A message.
        
    Returns:
        IncidentCreationResult containing the created incident information.
    """
    task_description = "Create incident report"

    # Create message with JSON text part and ALL artifact file parts
    message_parts = [TextPart(text=incident_input.model_dump_json())]

    # Add ALL artifacts as file parts (agent will handle them)
    for artifact in artifacts:
        message_parts.append(FilePart(file=artifact))
        logger.info(f"Adding artifact '{artifact.name}' as file part to incident creation message")

    # Create the message
    message = Message(parts=message_parts, message_id="", role='agent')

    completed_task = await _send_task_to_agent_with_message(message, task_description)

    task_description = f"Incident creation for test case {incident_input.test_case.key}"
    received_artifacts = _get_artifacts_from_task(completed_task, task_description)
    text_content = _get_text_content_from_artifacts(received_artifacts, task_description)
    result = IncidentCreationResult.model_validate_json(text_content)
    return result


async def _request_test_cases_generation(user_story_id) -> GeneratedTestCases:
    task_description = "Generate test cases"
    completed_task = await _send_task_to_agent(f"Jira user story with key {user_story_id}",
                                               task_description)
    task_description = f"Generation of test cases for the user story {user_story_id}"
    received_artifacts = _get_artifacts_from_task(completed_task, task_description)
    text_content = _get_text_content_from_artifacts(received_artifacts, task_description)
    return GeneratedTestCases.model_validate_json(text_content)


def _get_artifacts_from_task(task: Task, task_description: str) -> list[Artifact]:
    _validate_task_status(task, task_description)
    results: list[Artifact] = task.artifacts
    if not results:
        _handle_exception(f"Received no execution results from the agent after it executed {task_description}.")
    return results


async def _request_test_cases_classification(test_cases: List[TestCase], user_story_id: str) -> list[Artifact]:
    task_description = "Classify test cases"
    completed_task = await _send_task_to_agent(f"Test cases:\n{test_cases}", task_description)
    return _get_artifacts_from_task(completed_task,
                                    f"Classification of test cases for the user story {user_story_id}")


async def _request_test_cases_review(test_cases: List[TestCase], user_story_id: str) -> list[Artifact]:
    task_description = "Review test cases"
    completed_task = await _send_task_to_agent(f"Test cases:\n{test_cases}\nUser Story ID: {user_story_id}", task_description)
    return _get_artifacts_from_task(completed_task, "Review of test cases")


async def _extract_generated_test_case_issue_keys_from_agent_response(results: list[Artifact], task_description: str) -> \
        list[str]:
    test_case_generation_results = _get_text_content_from_artifacts(results, task_description)
    user_prompt = f"""
Your input:\n"{test_case_generation_results}".

The information inside the input you need to find: the Jira issue key of each test case.

Result format: a list of all found test case issue keys as a lift of strings.
"""
    result = await _get_results_extractor_agent(str).run(user_prompt)
    issue_keys: list[str] = result.output or []
    logger.info(f"Extracted issue keys of {len(issue_keys)} test cases from test case generation agent's "
                f"response.")
    return result.output or None


def _get_text_content_from_artifacts(artifacts: list[Artifact], task_description, any_content_expected=True) -> str:
    text_parts: List[str] = []
    for part in artifacts[0].parts:
        if isinstance(part.root, TextPart):
            text_parts.append(part.root.text)
    if any_content_expected and (not text_parts):
        _handle_exception(f"Received no text results from the agent after it executed {task_description}.")
    test_case_generation_results = "\n".join(text_parts)
    return test_case_generation_results


def _get_file_contents_from_artifacts(artifacts: list[Artifact]) -> List[FileWithBytes]:
    file_parts: List[FileWithBytes] = []
    for part in artifacts[0].parts:
        if isinstance(part.root, FilePart):
            file_parts.append(part.root.file)
    return file_parts


async def _save_agent_logs_from_task(task: Task, internal_task_id: str) -> None:
    """Extract and save agent logs from task artifacts.
    
    Args:
        task: The completed Task containing artifacts with potential logs.
        internal_task_id: The internal task ID for tracking in task history.
    """
    try:
        file_artifacts = _get_file_contents_from_artifacts(task.artifacts)
        agent_logs = utils.get_execution_logs_from_artifacts(file_artifacts)
        if agent_logs:
            await task_history.update_logs(internal_task_id, agent_logs)
    except Exception as e:
        logger.warning(f"Failed to extract logs for task {internal_task_id}: {e}")


async def _send_task_to_agent_with_message(message: Message, task_description: str) -> Task | None:
    """Send a custom message (with file parts) to an agent.

    Args:
        message: The A2A Message object to send (can contain text and file parts).
        task_description: Description of the task for agent selection and logging.

    Returns:
        The completed Task, or None if the task failed to complete.
    """

    internal_task_id = str(uuid4())
    agent_id = None
    try:
        # Wait for an agent and reserve it atomically
        agent_id, agent_card = await _wait_and_reserve_agent(task_description)
        task_start_time = datetime.now()
        agent_name = await agent_registry.get_name(agent_id)

        # Record task start in history
        task_record = TaskRecord(
            task_id=internal_task_id,
            agent_id=agent_id,
            agent_name=agent_name,
            description=task_description,
            status=TaskStatus.RUNNING,
            start_time=task_start_time
        )
        await task_history.add(task_record)
        await agent_registry.set_current_task(agent_id, internal_task_id)

        async with httpx.AsyncClient(timeout=config.OrchestratorConfig.TASK_EXECUTION_TIMEOUT) as client:
            client_config = ClientConfig(httpx_client=client)
            client_factory = ClientFactory(config=client_config)
            a2a_client = client_factory.create(card=agent_card)

            response_iterator = a2a_client.send_message(message)
            start_time = time.time()
            last_task = None
            while (time_left := _get_time_left_for_task_completion_waiting(start_time)) > 0:
                try:
                    response = await asyncio.wait_for(response_iterator.__anext__(), timeout=time_left)
                except StopAsyncIteration:
                    if last_task and last_task.status.state in (TaskState.completed, TaskState.failed, TaskState.rejected):
                        # Update task history with completion
                        final_status = TaskStatus.COMPLETED if last_task.status.state == TaskState.completed else TaskStatus.FAILED
                        await task_history.update(internal_task_id, status=final_status, end_time=datetime.now())
                        await _save_agent_logs_from_task(last_task, internal_task_id)
                        await agent_registry.update_status(agent_id, AgentStatus.AVAILABLE)
                        await agent_registry.set_current_task(agent_id, None)
                        return last_task
                    await task_history.update(internal_task_id, TaskStatus.FAILED, datetime.now(), "Iterator finished before completion")
                    # Release agent as AVAILABLE since this is a protocol issue, not agent issue
                    await agent_registry.update_status(agent_id, AgentStatus.AVAILABLE)
                    await agent_registry.set_current_task(agent_id, None)
                    _handle_exception(f"Task '{task_description}' iterator finished before completion.", 500, internal_task_id, agent_id)
                except asyncio.TimeoutError:
                    logger.error(f"Task '{task_description}' timed out while waiting for completion.",
                                 extra={"task_id": internal_task_id, "agent_id": agent_id})
                    await task_history.update(internal_task_id, TaskStatus.FAILED, datetime.now(), "Task timed out")
                    stuck_task_id = last_task.id if last_task else None
                    await agent_registry.update_status(
                        agent_id, AgentStatus.BROKEN, BrokenReason.TASK_STUCK, stuck_task_id
                    )
                    await agent_registry.set_current_task(agent_id, None)
                    await cancellation_queue.put((agent_id, time.time()))
                    _handle_exception(f"Task '{task_description}' timed out while waiting for completion.", 408, internal_task_id, agent_id)

                if isinstance(response, JSONRPCErrorResponse):
                    await task_history.update(internal_task_id, TaskStatus.FAILED, datetime.now(), str(response.error))
                    # Release agent as AVAILABLE since this is a task-level error
                    await agent_registry.update_status(agent_id, AgentStatus.AVAILABLE)
                    await agent_registry.set_current_task(agent_id, None)
                    _handle_exception(f"Couldn't execute the task '{task_description}'. Root cause: {response.error}", 500,
                                      internal_task_id, agent_id)

                if isinstance(response, tuple):
                    task, _ = response
                    last_task = task
                    if task.status.state in (TaskState.completed, TaskState.failed, TaskState.rejected):
                        logger.info(f"Task '{task_description}' was completed with status '{str(task.status.state)}'.",
                                    extra={"task_id": internal_task_id, "agent_id": agent_id})
                        final_status = TaskStatus.COMPLETED if task.status.state == TaskState.completed else TaskStatus.FAILED
                        error_msg = get_message_text(task.status.message) if task.status.state != TaskState.completed else None
                        await task_history.update(internal_task_id, final_status, datetime.now(), error_msg)
                        await _save_agent_logs_from_task(task, internal_task_id)
                        await agent_registry.update_status(agent_id, AgentStatus.AVAILABLE)
                        await agent_registry.set_current_task(agent_id, None)
                        return task
                    else:
                        logger.debug(f"Task for {task_description} is still in '{task.status.state}' state. Waiting for its "
                                     f"completion. Agent: '{agent_card.name}' (ID: {agent_id})",
                                     extra={"task_id": internal_task_id, "agent_id": agent_id})
                elif isinstance(response, Message):
                    msg_text = get_message_text(response)
                    logger.info(f"Received a message from agent in the scope of the "
                                f"task '{task_description}': {msg_text}", extra={"task_id": internal_task_id, "agent_id": agent_id})

            await task_history.update(internal_task_id, TaskStatus.FAILED, datetime.now(), "Timeout waiting for completion")
            # Release agent as BROKEN since we hit overall timeout
            await agent_registry.update_status(agent_id, AgentStatus.BROKEN, BrokenReason.TASK_STUCK)
            await agent_registry.set_current_task(agent_id, None)
            await cancellation_queue.put((agent_id, time.time()))
            _handle_exception(f"Task for {task_description} wasn't complete within timeout.", 408, internal_task_id, agent_id)
            return None

    except HTTPException:
        # HTTPException is raised by _handle_exception, agent status already handled above
        raise
    except Exception as e:
        logger.exception(f"Error communicating with agent {agent_id}.", extra={"task_id": internal_task_id, "agent_id": agent_id})
        try:
            await task_history.update(internal_task_id, TaskStatus.FAILED, datetime.now(), str(e))
        except Exception:
            pass  # Task history update failed, but we must still release the agent
        # Connection/communication error likely means agent is offline
        await agent_registry.update_status(agent_id, AgentStatus.BROKEN, BrokenReason.OFFLINE)
        await agent_registry.set_current_task(agent_id, None)
        await cancellation_queue.put((agent_id, time.time()))
        raise


async def _send_task_to_agent(input_data: str, task_description: str) -> Task | None:
    """Send a text message to an agent.

    Args:
        input_data: The text content to send to the agent.
        task_description: Description of the task for agent selection and logging.

    Returns:
        The completed Task, or None if the task failed to complete.
    """
    message = new_agent_text_message(input_data)
    return await _send_task_to_agent_with_message(message, task_description)


async def _wait_and_reserve_agent(task_description: str) -> tuple[str, AgentCard]:
    """Wait for an available agent and atomically reserve it.

    This function handles the waiting loop outside the lock, and only holds
    the lock during the atomic check-select-reserve operation.

    Args:
        task_description: Description of the task to be assigned.

    Returns:
        Tuple of (agent_id, agent_card) for the reserved agent.
        
    Raises:
        HTTPException: If no agents are registered, no suitable agent found, 
                       or timeout waiting for an available agent.
    """
    if await agent_registry.is_empty():
        _handle_exception("Orchestrator has currently no registered agents.", 404)

    max_wait_time = config.OrchestratorConfig.TASK_EXECUTION_TIMEOUT
    start_time = time.time()
    wait_interval = 2
    max_wait_interval = 30

    while (time.time() - start_time) < max_wait_time:
        # Try to atomically select and reserve an agent
        async with agent_selection_lock:
            available_agent_ids = await agent_registry.get_available_agents()
            if available_agent_ids:
                agent_id = await _select_agent(task_description, available_agent_ids)
                if agent_id:
                    # Double-check agent is still available (might have changed during _select_agent)
                    current_status = await agent_registry.get_status(agent_id)
                    if current_status == AgentStatus.AVAILABLE:
                        agent_card = await agent_registry.get_card(agent_id)
                        if agent_card:
                            # Atomically mark as BUSY before releasing the lock
                            await agent_registry.update_status(agent_id, AgentStatus.BUSY)
                            agent_name = await agent_registry.get_name(agent_id)
                            logger.info(f"Reserved agent '{agent_name}' (ID: {agent_id}) for task '{task_description}'")
                            return agent_id, agent_card
                else:
                    _handle_exception(f"No suitable agent found to handle the task '{task_description}'.", 404)

        # No agent was reserved - wait and retry (outside the lock)
        logger.info(f"No available agents for task '{task_description}'. "
                    f"All agents are busy. Waiting {wait_interval}s before retry...")
        await asyncio.sleep(wait_interval)
        wait_interval = min(wait_interval * 1.5, max_wait_interval)  # Exponential backoff with cap

    # Timeout reached
    _handle_exception(f"Timeout waiting for an available agent to handle task '{task_description}'. "
                      f"All agents have been busy for {max_wait_time} seconds.", 503)


async def _get_jira_issue_key_from_request(request):
    payload = await request.json()
    user_story_id = (payload or {}).get("issue_key", "")
    if not user_story_id:
        _handle_exception("Request has no Jira issue key in the payload.", 400)
    return user_story_id


def _handle_exception(
        message: str,
        status_code: int = 500,
        task_id: str | None = None,
        agent_id: str | None = None
) -> HTTPException:
    """Handle an exception by logging it and recording it for the dashboard.
    
    Args:
        message: Error message.
        status_code: HTTP status code.
        task_id: Optional task ID related to the error.
        agent_id: Optional agent ID related to the error.
    """
    logger.exception(message)

    # Record error for dashboard (run in background to avoid blocking)
    error_record = ErrorRecord(
        error_id=str(uuid4()),
        timestamp=datetime.now(),
        message=message,
        task_id=task_id,
        agent_id=agent_id,
        module="orchestrator.main",
        traceback_snippet=traceback.format_exc()[-500:]  # Last 500 chars of traceback
    )
    # Schedule the async add without waiting
    asyncio.create_task(error_history.add(error_record))

    raise HTTPException(status_code=status_code, detail=message)


def _is_task_still_running(task_state: TaskState) -> bool:
    return task_state in (TaskState.submitted, TaskState.working)


def _validate_task_status(task: Task, task_description: str):
    if not task:
        _handle_exception(f"Something went wrong while executing the task for {task_description}.")
    task_state = task.status.state
    if task_state != TaskState.completed:
        _handle_exception(f"Task for {task_description} has an unexpected status '{str(task_state)}'. "
                          f"Root cause: {get_message_text(task.status.message)}")


def _get_time_left_for_task_completion_waiting(start_time):
    return config.OrchestratorConfig.TASK_EXECUTION_TIMEOUT - (time.time() - start_time)


async def _select_all_suitable_agent_ids(task_description: str) -> List[str]:
    """Selects all suitable agents from the registry for a given task.
    
    Only considers agents that are currently AVAILABLE for new tasks.
    """
    available_agent_ids = await agent_registry.get_available_agents()
    agents_info = await _get_agents_info(available_agent_ids)
    user_prompt = f"""
Target task description: "{task_description}".

The list of all registered with you agents:\n{agents_info}
"""

    result = await multi_discovery_agent.run(user_prompt)
    selected_agent_ids = result.output.ids or []
    valid_agent_ids = []
    for agent_id in selected_agent_ids:
        # Verify agent exists AND is in our available agents list
        if await agent_registry.contains(agent_id) and agent_id in available_agent_ids:
            valid_agent_ids.append(agent_id)

    for agent_id in valid_agent_ids:
        agent_name = await agent_registry.get_name(agent_id)
        logger.info(f"Selected agent '{agent_name}' with ID '{agent_id}' for task '{task_description}'.")
    return valid_agent_ids


async def _get_agents_info(available_agent_ids: List[str]) -> str:
    """Get information about agents that are AVAILABLE for new tasks.
    
    Args:
        available_agent_ids: List of agent IDs that are currently AVAILABLE.
        
    Returns:
        Formatted string with agent information for the discovery agent.
    """
    agents_info = ""
    all_cards = await agent_registry.get_all_cards()
    for agent_id in available_agent_ids:
        card = all_cards.get(agent_id)
        if card:
            agents_info += (f"- Name: {card.name}, ID: {agent_id}, Description: {card.description}, Skills: "
                            f"{"; ".join(skill.description for skill in card.skills)}\n")
    return agents_info


async def _select_agent(task_description: str, available_agent_ids: List[str]) -> str | None:
    """Selects the best agent from the available agents to handle a given task.
    
    Args:
        task_description: Description of the task to be assigned.
        available_agent_ids: List of agent IDs that are currently AVAILABLE.
        
    Returns:
        The ID of the selected agent, or None if no suitable agent found.
    """
    agents_info = await _get_agents_info(available_agent_ids)
    if not agents_info:
        return None

    user_prompt = f"""
Target task description: "{task_description}".

The list of all registered with you agents:\n{agents_info}
"""
    result = await discovery_agent.run(user_prompt)
    selected_agent_id = result.output.id or None
    # Verify the selected agent is in our available list
    if selected_agent_id and selected_agent_id in available_agent_ids:
        return selected_agent_id
    return None


async def _fetch_agent_card(agent_base_url: str) -> AgentCard | None:
    agent_card_url = f"{agent_base_url}/.well-known/agent-card.json"
    try:
        logger.info(f"Attempting to retrieve agent card from {agent_card_url}")
        async with httpx.AsyncClient() as client:
            response = await client.get(agent_card_url,
                                        timeout=config.OrchestratorConfig.AGENT_DISCOVERY_TIMEOUT_SECONDS)
            response.raise_for_status()
            agent_card = AgentCard(**response.json())
            actual_agent_name = agent_card.name
            logger.info(f"Successfully retrieved and registered the agent card for '{actual_agent_name}'.")
            return agent_card
    except Exception as exc:
        logger.warning(f"Could not retrieve agent card from {agent_card_url}. Error: {exc}")
        return None


async def _check_agent_reachability(agent_base_url: str) -> bool:
    agent_card_url = f"{agent_base_url}/.well-known/agent-card.json"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(agent_card_url,
                                        timeout=config.OrchestratorConfig.AGENT_DISCOVERY_TIMEOUT_SECONDS)
            return response.status_code == 200
    except Exception:
        return False


async def _process_url_discovery(url: str):
    existing_agent_id = await agent_registry.get_agent_id_by_url(url)
    if existing_agent_id:
        if await _check_agent_reachability(url):
            status = await agent_registry.get_status(existing_agent_id)
            if status == AgentStatus.BROKEN:
                broken_reason, _ = await agent_registry.get_broken_context(existing_agent_id)
                if broken_reason == BrokenReason.OFFLINE:
                    logger.info(
                        f"Agent {existing_agent_id} (URL: {url}) was OFFLINE "
                        f"but is now responsive. Resetting to AVAILABLE."
                    )
                    await agent_registry.update_status(existing_agent_id, AgentStatus.AVAILABLE)
        else:
            logger.info(f"Agent {existing_agent_id} at {url} is unreachable. Removing from registry.")
            await agent_registry.remove(existing_agent_id)
    else:
        agent_card = await _fetch_agent_card(url)
        if agent_card:
            existing_agent_id = await agent_registry.get_agent_id_by_url(agent_card.url)
            if existing_agent_id:
                logger.debug(f"Agent with URL {agent_card.url} is already registered with ID {existing_agent_id}.")
            else:
                new_agent_id = str(uuid4())
                await agent_registry.register(new_agent_id, agent_card)
                logger.info(f"Discovered and registered agent with URL: {agent_card.url}")


async def _discover_agents():
    """
    Discovers remote agents by scanning a port range on each of the configured base URLs.
    Checks reachability of existing agents and discovers new ones.
    """
    agent_base_urls_str = config.OrchestratorConfig.REMOTE_EXECUTION_AGENT_HOSTS
    port_range_str = config.OrchestratorConfig.AGENT_DISCOVERY_PORTS

    if not agent_base_urls_str or not port_range_str:
        logger.info("Agent discovery configuration is incomplete. "
                    "Please set both REMOTE_EXECUTION_AGENT_HOSTS and AGENT_DISCOVERY_PORTS.")
        return

    base_urls = [url.strip() for url in agent_base_urls_str.split(',')]

    try:
        start_port, end_port = map(int, port_range_str.split('-'))
    except ValueError:
        logger.error(f"Invalid port range format for AGENT_DISCOVERY_PORTS: '{port_range_str}'. "
                     f"Expected format is 'start-end', e.g., '8001-8010'.")
        return

    remote_agent_urls = []
    for base_url in base_urls:
        for port in range(start_port, end_port + 1):
            remote_agent_urls.append(f"{base_url}:{port}")

    if not remote_agent_urls:
        logger.warning("No agent URLs were generated for discovery.")
        return

    tasks = [_process_url_discovery(url) for url in set(remote_agent_urls)]
    await asyncio.gather(*tasks)


# =============================================================================
# Static File Serving for Dashboard UI
# =============================================================================

# Path to the built UI static files
STATIC_FILES_DIR = Path(__file__).parent / "static"

if STATIC_FILES_DIR.exists():
    # Mount static files (JS, CSS, assets)
    orchestrator_app.mount("/assets", StaticFiles(directory=STATIC_FILES_DIR / "assets"), name="assets")


    # Serve index.html for the root path
    @orchestrator_app.get("/")
    async def serve_dashboard():
        """Serve the dashboard UI."""
        from fastapi.responses import FileResponse
        return FileResponse(STATIC_FILES_DIR / "index.html")


    # Catch-all route for SPA client-side routing (must be last)
    @orchestrator_app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve index.html for all unmatched routes (SPA fallback)."""
        from fastapi.responses import FileResponse
        # Don't intercept API routes
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API endpoint not found")
        # Check if file exists in static dir
        file_path = STATIC_FILES_DIR / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        # Return index.html for client-side routing
        return FileResponse(STATIC_FILES_DIR / "index.html")
else:
    logger.info("Dashboard UI static files not found. UI will not be available.")

if __name__ == "__main__":
    uvicorn.run(orchestrator_app, host=config.ORCHESTRATOR_HOST, port=config.ORCHESTRATOR_PORT)
