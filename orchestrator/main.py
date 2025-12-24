# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

import asyncio
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List
from uuid import uuid4

import httpx
import uvicorn
from a2a.client import ClientFactory, ClientConfig
from a2a.types import TaskState, AgentCard, Artifact, Task, JSONRPCErrorResponse, TextPart, FilePart, FileWithBytes, \
    Message
from a2a.utils import new_agent_text_message, get_message_text
from fastapi import FastAPI, Request, HTTPException, Security, Depends
from fastapi.security import APIKeyHeader
from pydantic_ai import Agent
from pydantic_ai.settings import ModelSettings

import config
from common import utils
from common.services.vector_db_service import VectorDbService
from common.custom_llm_wrapper import CustomLlmWrapper
from common.models import SelectedAgent, GeneratedTestCases, TestCase, ProjectExecutionRequest, TestExecutionResult, \
    TestExecutionRequest, SelectedAgents, JsonSerializableModel, IncidentCreationInput, IncidentCreationResult, \
    IncidentIndexData
from common.services.test_management_system_client_provider import get_test_management_client
from common.services.test_reporting_client_base_provider import get_test_reporting_client

MAX_RETRIES = 3

MODEL_SETTINGS = ModelSettings(top_p=config.TOP_P, temperature=config.TEMPERATURE)

logger = utils.get_logger("orchestrator")

# Initialize Vector DB Service for Orchestrator
vector_db_service = VectorDbService(getattr(config.QdrantConfig, "COLLECTION_NAME", "jira_issues"))


class AgentStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    BUSY = "BUSY"
    BROKEN = "BROKEN"


class AgentRegistry:
    def __init__(self):
        self._cards: Dict[str, AgentCard] = {}
        self._statuses: Dict[str, AgentStatus] = {}
        self._lock = asyncio.Lock()

    async def get_card(self, agent_id: str) -> AgentCard | None:
        async with self._lock:
            return self._cards.get(agent_id)

    async def get_name(self, agent_id: str) -> str:
        async with self._lock:
            card = self._cards.get(agent_id)
            return card.name if card else "Unknown"

    async def register(self, agent_id: str, card: AgentCard):
        async with self._lock:
            self._cards[agent_id] = card
            if agent_id not in self._statuses:
                self._statuses[agent_id] = AgentStatus.AVAILABLE

    async def update_status(self, agent_id: str, status: AgentStatus):
        async with self._lock:
            if agent_id in self._cards:
                self._statuses[agent_id] = status

    async def get_status(self, agent_id: str) -> AgentStatus:
        async with self._lock:
            return self._statuses.get(agent_id, AgentStatus.BROKEN)

    async def remove(self, agent_id: str):
        async with self._lock:
            self._cards.pop(agent_id, None)
            self._statuses.pop(agent_id, None)

    async def get_all_cards(self) -> Dict[str, AgentCard]:
        async with self._lock:
            return self._cards.copy()

    async def is_empty(self) -> bool:
        async with self._lock:
            return not self._cards

    async def contains(self, agent_id: str) -> bool:
        async with self._lock:
            return agent_id in self._cards

    async def get_valid_agents(self) -> List[str]:
        async with self._lock:
            return [aid for aid, status in self._statuses.items() if status != AgentStatus.BROKEN and aid in self._cards]


agent_registry = AgentRegistry()
execution_lock = asyncio.Lock()
cancellation_queue = asyncio.Queue()

API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)


# noinspection PyUnusedLocal
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Orchestrator starting up...")
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


async def _retry_cancellation_task():
    """Background task to retry cancellation of tasks on broken agents."""
    logger.info("Starting retry cancellation task.")
    while True:
        try:
            agent_id, timestamp = await cancellation_queue.get()
            
            # If it's been more than 24 hours, give up
            if time.time() - timestamp > 24 * 3600:
                logger.warning(f"Gave up cancelling task for agent {agent_id} after 24 hours.")
                cancellation_queue.task_done()
                continue

            # Attempt cancellation (or recovery check)
            logger.info(f"Attempting to cancel task/recover agent {agent_id}...")
            
            # Placeholder for actual cancellation logic. 
            # We check if agent is responsive (e.g. we can get its card).
            # If responsive, we assume we can reset it to AVAILABLE.
            agent_card = await agent_registry.get_card(agent_id)
            is_recovered = False
            if agent_card:
                 # Try to fetch card again to see if it responds
                 if await _fetch_agent_card(agent_card.url):
                     is_recovered = True
            
            if is_recovered:
                logger.info(f"Agent {agent_id} successfully recovered/cancelled. Marking AVAILABLE.")
                await agent_registry.update_status(agent_id, AgentStatus.AVAILABLE)
                cancellation_queue.task_done()
            else:
                logger.info(f"Agent {agent_id} not recovered yet. Will retry.")
                cancellation_queue.task_done()
                # Re-queue with delay
                await asyncio.sleep(60) # Wait 1 minute before retrying same agent? 
                # To avoid busy loop if queue has items, we should sleep or use a better scheduling.
                # But putting it back immediately makes this loop spin if queue has items and they fail.
                # So we should put it back and sleep.
                await cancellation_queue.put((agent_id, timestamp))
                
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in cancellation retry task: {e}")
            await asyncio.sleep(5)


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
    """Periodically discovers agents."""
    while True:
        try:
            logger.info("Starting periodic agent discovery...")
            await _discover_agents()
            logger.info("Periodic agent discovery finished.")
        except Exception as e:
            _handle_exception(f"An error occurred during periodic agent discovery: {e}")
        finally:
            await asyncio.sleep(config.OrchestratorConfig.AGENTS_DISCOVERY_INTERVAL_SECONDS)


# noinspection PyUnusedLocal
@orchestrator_app.post("/new-requirements-available")
async def review_jira_requirements(request: Request, api_key: str = Depends(_validate_api_key)):
    """
    Receives webhook from Jira and triggers the requirements review.
    """
    logger.info("Received an event from Jira, requesting requirements review from an agent.")
    user_story_id = await _get_jira_issue_key_from_request(request)
    task_description = "Review the Jira user story"
    agent_id = await _choose_agent_id(task_description)
    completed_task, _ = await _send_task_to_agent(agent_id, f"Jira user story with key {user_story_id}",
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
        agent_id = await _choose_agent_id(task_description)
        completed_task, _ = await _send_task_to_agent(agent_id, f"Sync Jira bugs for project {project_key}",
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
        # _validate_request_authorization(request)
        project_key = request.project_key
        logger.info(f"Received request to execute automated tests for project '{project_key}'.")
        test_management_client = get_test_management_client()
        automated_test_cases = []
        try:
            automated_tests_dict = test_management_client.fetch_ready_for_execution_test_cases_by_labels(
                project_key,                          [config.OrchestratorConfig.AUTOMATED_TC_LABEL])
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
        workers.append(asyncio.create_task(_agent_worker(agent_id, queue, results)))

    # Wait for all items in the queue to be processed
    await queue.join()

    # Cancel all workers
    for worker in workers:
        worker.cancel()
    
    # Wait for workers to finish cancelling
    await asyncio.gather(*workers, return_exceptions=True)

    return results


async def _agent_worker(agent_id: str, queue: asyncio.Queue, results: List[TestExecutionResult]):
    logger.info(f"Agent worker started for agent {agent_id}")
    try:
        while True:
            # Check agent status
            status = await agent_registry.get_status(agent_id)
            if status != AgentStatus.AVAILABLE:
                if status == AgentStatus.BROKEN:
                    logger.warning(f"Agent {agent_id} is BROKEN. Worker stopping.")
                    break
                # If BUSY, just wait a bit? But logically if it is this worker's turn, 
                # and we are using a queue, the agent should be AVAILABLE or we made it BUSY ourselves?
                # In this architecture, we have one worker per agent. 
                # So this worker is the ONLY one sending tasks to this agent.
                # So if it says BUSY, it might be busy from a previous task (unlikely if single worker)
                # or marked BUSY by this worker.
                # However, let's follow the plan: "If agent_status[agent_id] is not AVAILABLE, wait/sleep."
                await asyncio.sleep(1)
                continue

            test_case, test_type = await queue.get()
            
            try:
                # Execute
                result = await _execute_single_test(agent_id, test_case, test_type)
                if result:
                    results.append(result)
            except Exception as e:
                logger.error(f"Error in worker for agent {agent_id}: {e}")
                # Retry logic: Put back in queue
                # Mark agent broken if needed? The plan says:
                # "If _execute_single_test raises exception... Mark agent as BROKEN (if not already)."
                # "Retry: Put the failed test_case back into the queue"
                await agent_registry.update_status(agent_id, AgentStatus.BROKEN)
                queue.put_nowait((test_case, test_type))
                queue.task_done() # Mark the failed task as done so we don't block join? 
                # Wait, if we put it back, queue size increases. 
                # queue.join() blocks until unfinished_tasks goes to 0.
                # We called get(), so unfinished_tasks is same.
                # If we put_nowait, unfinished_tasks +1.
                # We call task_done() for the one we failed.
                # So net change is 0. Correct.
                break # Exit worker as agent is broken
            
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
    logs = ""
    start_timestamp = datetime.now()
    try:
        completed_task, logs = await _send_task_to_agent(agent_id, execution_request.model_dump_json(),
                                                   task_description)
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
Your input are the following test case execution results:\n```\n{text_results}\n```

Information you need to find: all data of the requested output JSON object.

Result format is a JSON.
"""
    result = await _get_results_extractor_agent(TestExecutionResult).run(user_prompt)
    test_execution_result: TestExecutionResult = result.output
    if not test_execution_result:
        _handle_exception("Couldn't map the test execution results received from the agent to the expected format.")

    test_execution_result.testCaseKey = test_case.key
    test_execution_result.logs = logs
    if not test_execution_result.start_timestamp:
        test_execution_result.start_timestamp = start_timestamp.isoformat()
    if not test_execution_result.end_timestamp:
        test_execution_result.end_timestamp = end_timestamp.isoformat()
    file_artifacts = _get_file_contents_from_artifacts(artifacts)
    test_execution_result.artifacts = file_artifacts
    
    if not test_execution_result.system_description:
        test_execution_result.system_description = f"Agent: {agent_name}, Environment: Standard Test Environment"

    if test_execution_result.testExecutionStatus in ["failed", "error"]:
        logger.info(f"Test case {test_case.key} failed. Initiating incident creation.")
        try:
            incident_input = IncidentCreationInput(
                test_case_key=test_case.key,
                test_execution_result=str(test_execution_result),
                agent_execution_logs=test_execution_result.logs,
                system_description=test_execution_result.system_description,
                available_artefacts=file_artifacts or []
            )
            incident_result = await _request_incident_creation(incident_input)
            test_execution_result.incident_creation_result = incident_result
        except Exception as e:
            logger.error(f"Failed to create incident for test case {test_case.key}: {e}")

    logger.info(f"Executed test case {test_case.key}. Status: {test_execution_result.testExecutionStatus}")
    return test_execution_result


async def _request_incident_creation(incident_input: IncidentCreationInput) -> IncidentCreationResult:
    task_description = "Create incident report"
    agent_id = await _choose_agent_id(task_description)
    completed_task, _ = await _send_task_to_agent(agent_id,
                                               incident_input.model_dump_json(),
                                               task_description)
    
    task_description = f"Incident creation for test case {incident_input.test_case_key}"
    received_artifacts = _get_artifacts_from_task(completed_task, task_description)
    text_content = _get_text_content_from_artifacts(received_artifacts, task_description)
    result = IncidentCreationResult.model_validate_json(text_content)

    if result.incident_key:
        try:
            content_to_index = f"{incident_input.test_execution_result}\n{incident_input.system_description}"
            if incident_input.agent_execution_logs:
                content_to_index += f"\nLogs: {incident_input.agent_execution_logs[:500]}..."

            incident_data = IncidentIndexData(
                incident_key=result.incident_key,
                content=content_to_index,
                source="incident_creation"
            )

            await vector_db_service.upsert(data=incident_data)
        except Exception as e:
            logger.error(f"Failed to index created incident {result.incident_key}: {e}")

    return result


async def _request_test_cases_generation(user_story_id) -> GeneratedTestCases:
    task_description = "Generate test cases"
    agent_id = await _choose_agent_id(task_description)
    completed_task, _ = await _send_task_to_agent(agent_id,
                                               f"Jira user story with key {user_story_id}",
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
    agent_id = await _choose_agent_id(task_description)
    completed_task, _ = await _send_task_to_agent(agent_id,
                                               f"Test cases:\n{test_cases}", task_description)
    return _get_artifacts_from_task(completed_task,
                                    f"Classification of test cases for the user story {user_story_id}")


async def _request_test_cases_review(test_cases: List[TestCase], user_story_id: str) -> list[Artifact]:
    task_description = "Review test cases"
    agent_id = await _choose_agent_id(task_description)
    completed_task, _ = await _send_task_to_agent(agent_id, f"Test cases:\n{test_cases}\nUser Story ID: {user_story_id}", task_description)
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


async def _send_task_to_agent(agent_id: str, input_data: str, task_description: str) -> tuple[Task | None, str]:
    # Updated for Step 3.1: Self-Healing Task Distribution
    agent_card = await agent_registry.get_card(agent_id)
    if not agent_card:
        raise ValueError(f"Agent with ID '{agent_id}' is not yet registered with his card")

    # Set BUSY status
    await agent_registry.update_status(agent_id, AgentStatus.BUSY)

    execution_logs = []

    try:
        async with httpx.AsyncClient(timeout=config.OrchestratorConfig.TASK_EXECUTION_TIMEOUT) as client:
            client_config = ClientConfig(httpx_client=client)
            client_factory = ClientFactory(config=client_config)
            a2a_client = client_factory.create(card=agent_card)

            response_iterator = a2a_client.send_message(new_agent_text_message(input_data))
            start_time = time.time()
            last_task = None
            
            # We use a loop to wait for completion or timeout
            # Note: The original code had a while loop with timeout. 
            # We want to wrap this with try/except to handle timeouts and set status to BROKEN/AVAILABLE.
            
            while (time_left := _get_time_left_for_task_completion_waiting(start_time)) > 0:
                try:
                    response = await asyncio.wait_for(response_iterator.__anext__(), timeout=time_left)
                except StopAsyncIteration:
                    if last_task and last_task.status.state in (TaskState.completed, TaskState.failed, TaskState.rejected):
                        await agent_registry.update_status(agent_id, AgentStatus.AVAILABLE)
                        return last_task, "\n".join(execution_logs)
                    _handle_exception(f"Task '{task_description}' iterator finished before completion.", 500)
                except asyncio.TimeoutError:
                    # Handle Timeout (Step 3.1)
                    logger.error(f"Task '{task_description}' timed out while waiting for completion.")
                    try:
                        # Mark as BROKEN and enqueue for cancellation retry
                         await agent_registry.update_status(agent_id, AgentStatus.BROKEN)
                         await cancellation_queue.put((agent_id, time.time()))
                    except Exception as ex:
                         logger.error(f"Error handling timeout for agent {agent_id}: {ex}")
                         await agent_registry.update_status(agent_id, AgentStatus.BROKEN)
                    
                    _handle_exception(f"Task '{task_description}' timed out while waiting for completion.", 408)

                if isinstance(response, JSONRPCErrorResponse):
                    _handle_exception(f"Couldn't execute the task '{task_description}'. Root cause: {response.error}")

                if isinstance(response, tuple):
                    task, _ = response
                    last_task = task
                    if task.status.state in (TaskState.completed, TaskState.failed, TaskState.rejected):
                        logger.info(f"Task '{task_description}' was completed with status '{str(task.status.state)}'.")
                        await agent_registry.update_status(agent_id, AgentStatus.AVAILABLE)
                        return task, "\n".join(execution_logs)
                    else:
                        logger.debug(
                            f"Task for {task_description} is still in '{task.status.state}' state. Waiting for its "
                            f"completion. Agent: '{agent_card.name}' (ID: {agent_id})")
                elif isinstance(response, Message):
                    msg_text = get_message_text(response)
                    execution_logs.append(f"[{datetime.now().isoformat()}] {msg_text}")
                    logger.info(
                        f"Received a message from agent in the scope of the "
                        f"task '{task_description}': {msg_text}")

            _handle_exception(f"Task for {task_description} wasn't complete within timeout.", 408)
            return None, "\n".join(execution_logs)

    except Exception as e:
        # Handle General Exception (Step 3.1)
        logger.error(f"Error communicating with agent {agent_id}: {e}")
        await agent_registry.update_status(agent_id, AgentStatus.BROKEN)
        raise e
    # finally:
        # "If success, set agent_status[agent_id] = AgentStatus.AVAILABLE."
        # This is handled inside the loop upon return. 
        # If exception raised, it goes to except block -> BROKEN.
        # So we don't need a catch-all finally that sets AVAILABLE because it might override BROKEN.


async def _choose_agent_id(agent_task_description):
    if await agent_registry.is_empty():
        _handle_exception("Orchestrator has currently no registered agents.", 404)
    agent_id = await _select_agent(agent_task_description)
    if not agent_id:
        _handle_exception(f"No agent found to handle the task '{agent_task_description}'.", 404)
    
    agent_name = await agent_registry.get_name(agent_id)
    logger.info(
        f"Selected agent '{agent_name}' (ID: {agent_id}) for task '{agent_task_description}'.")
    return agent_id


async def _get_jira_issue_key_from_request(request):
    payload = await request.json()
    user_story_id = (payload or {}).get("issue_key", "")
    if not user_story_id:
        _handle_exception("Request has no Jira issue key in the payload.", 400)
    return user_story_id


def _handle_exception(message: str, status_code: int = 500) -> HTTPException:
    logger.exception(message)
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
    """Selects all suitable agents from the registry for a given task."""
    agents_info = await _get_agents_info()
    user_prompt = f"""
Target task description: "{task_description}".

The list of all registered with you agents:\n{agents_info}
"""

    result = await multi_discovery_agent.run(user_prompt)
    selected_agent_ids = result.output.ids or []
    valid_agent_ids = []
    for agent_id in selected_agent_ids:
        if await agent_registry.contains(agent_id):
            valid_agent_ids.append(agent_id)
            
    for agent_id in valid_agent_ids:
        agent_name = await agent_registry.get_name(agent_id)
        logger.info(f"Selected agent '{agent_name}' with ID '{agent_id}' for task '{task_description}'.")
    return valid_agent_ids


async def _get_agents_info():
    agents_info = ""
    all_cards = await agent_registry.get_all_cards()
    for agent_id, card in all_cards.items():
        agents_info += (f"- Name: {card.name}, ID: {agent_id}, Description: {card.description}, Skills: "
                        f"{"; ".join(skill.description for skill in card.skills)}\n")
    return agents_info


async def _select_agent(task_description: str) -> str | None:
    """Selects the best agent from the registry to handle a given task and returns its ID"""
    agents_info = await _get_agents_info()
    user_prompt = f"""
Target task description: "{task_description}".

The list of all registered with you agents:\n{agents_info}
"""
    result = await discovery_agent.run(user_prompt)
    selected_agent_id = result.output.id or None
    if selected_agent_id and await agent_registry.contains(selected_agent_id):
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


async def _discover_agents():
    """
    Discovers remote agents by scanning a port range on each of the configured base URLs.
    """
    agent_base_urls_str = config.REMOTE_EXECUTION_AGENT_HOSTS
    port_range_str = config.AGENT_DISCOVERY_PORTS

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

    tasks = [_fetch_agent_card(url) for url in set(remote_agent_urls)]
    found_urls = []
    
    # Update for thread safety using AgentRegistry
    agent_cards = await asyncio.gather(*tasks)
    
    # We need to check against existing agents. 
    # Since registry methods are async, we should iterate and check.
    
    existing_cards = await agent_registry.get_all_cards()
    
    for agent_card in agent_cards:
        if agent_card:
            # Check if an agent with this URL is already registered
            already_registered = False
            for agent_id, existing_card in existing_cards.items():
                if existing_card.url == agent_card.url:
                    logger.info(f"Agent with URL {agent_card.url} is already registered with ID {agent_id}. Skipping.")
                    already_registered = True
                    break
            if not already_registered:
                agent_id = str(uuid4())
                await agent_registry.register(agent_id, agent_card)
                found_urls.append(agent_card.url)

    if found_urls:
        logger.info(f"Discovered and pre-registered agents with following URLs: {', '.join(found_urls)}")


if __name__ == "__main__":
    uvicorn.run(orchestrator_app, host=config.ORCHESTRATOR_HOST, port=config.ORCHESTRATOR_PORT)
