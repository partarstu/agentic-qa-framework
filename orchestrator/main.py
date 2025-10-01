# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

import asyncio
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime
from functools import wraps
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
from common.custom_llm_wrapper import CustomLlmWrapper
from common.models import SelectedAgent, GeneratedTestCases, TestCase, ProjectExecutionRequest, TestExecutionResult, \
    TestExecutionRequest, SelectedAgents, JsonSerializableModel
from common.services.test_management_system_client_provider import get_test_management_client
from common.services.test_reporting_client_base_provider import get_test_reporting_client

MAX_RETRIES = 3

MODEL_SETTINGS = ModelSettings(top_p=config.TOP_P, temperature=config.TEMPERATURE)

logger = utils.get_logger("orchestrator")

agent_registry: Dict[str, AgentCard] = {}
discovery_lock = asyncio.Lock()

API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)


# noinspection PyUnusedLocal
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Orchestrator starting up...")
    discovery_task = asyncio.create_task(periodic_agent_discovery())

    yield

    logger.info("Orchestrator shutting down.")
    if not discovery_task.cancel():
        try:
            await discovery_task
        except asyncio.CancelledError:
            logger.info("Agent discovery task successfully cancelled.")


def _validate_api_key(api_key: str = Security(api_key_header)):
    if config.OrchestratorConfig.API_KEY and api_key != config.OrchestratorConfig.API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid API Key")


orchestrator_app = FastAPI(lifespan=lifespan)


def with_exclusive_lock(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        lock_acquired = False
        try:
            async with asyncio.timeout(config.OrchestratorConfig.INCOMING_REQUEST_WAIT_TIMEOUT):
                await discovery_lock.acquire()
            lock_acquired = True
            logger.info("Lock acquired by request processing.")
            return await func(*args, **kwargs)
        except TimeoutError:
            _handle_exception("Could not acquire lock to process request, please try again later.", 503)
        finally:
            if lock_acquired:
                discovery_lock.release()
                logger.info("Lock released by request processing.")

    return wrapper


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
    retries=MAX_RETRIES
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
    retries=MAX_RETRIES
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
        retries=MAX_RETRIES
    )


async def periodic_agent_discovery():
    """Periodically discovers agents."""
    while True:
        try:
            async with discovery_lock:
                logger.info("Lock acquired by agent discovery.")
                logger.info("Starting periodic agent discovery...")
                await _discover_agents()
                logger.info("Periodic agent discovery finished.")
        except Exception as e:
            _handle_exception(f"An error occurred during periodic agent discovery: {e}")
        finally:
            logger.info("Lock released by agent discovery.")
            await asyncio.sleep(config.OrchestratorConfig.AGENTS_DISCOVERY_INTERVAL_SECONDS)


# noinspection PyUnusedLocal
@orchestrator_app.post("/new-requirements-available")
@with_exclusive_lock
async def review_jira_requirements(request: Request, api_key: str = Depends(_validate_api_key)):
    """
    Receives webhook from Jira and triggers the requirements review.
    """
    logger.info("Received an event from Jira, requesting requirements review from an agent.")
    user_story_id = await _get_jira_issue_key_from_request(request)
    task_description = "Review the Jira user story"
    agent_id = await _choose_agent_id(task_description)
    completed_task = await _send_task_to_agent(agent_id, f"Jira user story with key {user_story_id}",
                                               task_description)
    _validate_task_status(completed_task, f"Review of the user story {user_story_id}")
    logger.info("Received response from an agent, requirements review seems to be complete.")
    return {"message": f"Review of the requirements for Jira user story {user_story_id} completed."}


# noinspection PyUnusedLocal
@orchestrator_app.post("/story-ready-for-test-case-generation")
@with_exclusive_lock
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
    await _request_test_cases_review(generated_test_cases.test_cases)
    logger.info("Received response from an agent, test case review seems to be complete.")

    return {
        "message": f"Test case generation and classification for Jira user story {user_story_id} completed."
    }


# noinspection PyUnusedLocal
@orchestrator_app.post("/execute-tests")
@with_exclusive_lock
async def execute_tests(request: ProjectExecutionRequest, api_key: str = Depends(_validate_api_key)):
    # _validate_request_authorization(request)
    project_key = request.project_key
    logger.info(f"Received request to execute automated tests for project '{project_key}'.")
    test_management_client = get_test_management_client()
    automated_test_cases = []
    try:
        automated_tests_dict = test_management_client.fetch_ready_for_execution_test_cases_by_labels(project_key,
                                                                                                     [config.OrchestratorConfig.AUTOMATED_TC_LABEL])
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
    if not agent_registry:
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
    logger.info(
        f"Starting execution of {len(test_cases)} tests for type: '{test_type}' using agents: {[agent_registry[agent_id].name for agent_id in agent_ids if agent_id in agent_registry]}")

    if not agent_ids:
        logger.warning(f"No agents available for test type '{test_type}', skipping execution.")
        return []

    tests_to_run = test_cases.copy()
    available_agent_ids = agent_ids.copy()
    final_results = []

    while tests_to_run and available_agent_ids:
        tasks = []
        task_mapping = {}
        batch_size = min(len(available_agent_ids), len(tests_to_run))
        current_batch_tests = [tests_to_run.pop(0) for _ in range(batch_size)]
        agents_for_batch = available_agent_ids[:batch_size]

        for i, test_case in enumerate(current_batch_tests):
            agent_id = agents_for_batch[i]
            agent_name = agent_registry[agent_id].name
            logger.debug(f"Assigning test case {test_case.key} to agent {agent_name} (ID: {agent_id})")
            tasks.append(_execute_single_test(agent_id, test_case, test_type))
            task_mapping[i] = (agent_id, test_case)

        if not tasks:
            break

        results = await asyncio.gather(*tasks, return_exceptions=True)

        failed_agent_ids = set()
        for i, res in enumerate(results):
            agent_id, test_case = task_mapping[i]
            if isinstance(res, Exception):
                agent_name = agent_registry.get(agent_id).name if agent_registry.get(agent_id) else agent_id
                logger.error(f"Agent {agent_name} failed to execute test case {test_case.key}. Error: {res}. "
                             f"Re-queueing test.")
                tests_to_run.append(test_case)
                failed_agent_ids.add(agent_id)
            elif res:
                final_results.append(res)

        if failed_agent_ids:
            available_agent_ids = [aid for aid in available_agent_ids if aid not in failed_agent_ids]
            for agent_id in failed_agent_ids:
                if agent_id in agent_registry:
                    logger.warning(f"Removing agent {agent_registry[agent_id].name} (ID: {agent_id}) from registry "
                                   f"due to execution failure.")
                    del agent_registry[agent_id]

    if tests_to_run:
        logger.warning(
            f"Could not execute the following test cases due to lack of available agents: {[tc.key for tc in tests_to_run]}")

    return final_results


async def _execute_single_test(agent_id: str, test_case: TestCase,
                               test_type: str) -> TestExecutionResult | None:
    task_description = f"Execution of test case {test_case.key} (type: {test_type})"
    execution_request = TestExecutionRequest(test_case=test_case)
    artifacts = []
    start_timestamp = datetime.now()
    try:
        completed_task = await _send_task_to_agent(agent_id, execution_request.model_dump_json(),
                                                   task_description)
        artifacts = _get_artifacts_from_task(completed_task, task_description)
    except Exception as e:
        _handle_exception(f"Failed to execute test case {test_case.key}. Error: {e}", 500)
    finally:
        end_timestamp = datetime.now()

    if not artifacts:
        _handle_exception(f"No test case execution results received from agent {agent_registry[agent_id].name}", 500)
    text_results = _get_text_content_from_artifacts(artifacts, task_description)
    if not text_results:
        _handle_exception(f"No test case execution information received from agent {agent_registry[agent_id].name}",
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
    if not test_execution_result.start_timestamp:
        test_execution_result.start_timestamp = start_timestamp.isoformat()
    if not test_execution_result.end_timestamp:
        test_execution_result.end_timestamp = end_timestamp.isoformat()
    file_artifacts = _get_file_contents_from_artifacts(artifacts)
    test_execution_result.artifacts = file_artifacts

    logger.info(f"Executed test case {test_case.key}. Status: {test_execution_result.testExecutionStatus}")
    return test_execution_result


async def _request_test_cases_generation(user_story_id) -> GeneratedTestCases:
    task_description = "Generate test cases"
    agent_id = await _choose_agent_id(task_description)
    completed_task = await _send_task_to_agent(agent_id,
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
    completed_task = await _send_task_to_agent(agent_id,
                                               f"Test cases:\n{test_cases}", task_description)
    return _get_artifacts_from_task(completed_task,
                                    f"Classification of test cases for the user story {user_story_id}")


async def _request_test_cases_review(test_cases: List[TestCase]) -> list[Artifact]:
    task_description = "Review test cases"
    agent_id = await _choose_agent_id(task_description)
    completed_task = await _send_task_to_agent(agent_id, f"Test cases:\n{test_cases}", task_description)
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


async def _send_task_to_agent(agent_id: str, input_data: str, task_description: str) -> Task | None:
    agent_card = agent_registry.get(agent_id, None)
    if not agent_card:
        raise ValueError(f"Agent with ID '{agent_id}' is not yet registered with his card")

    async with httpx.AsyncClient(timeout=config.OrchestratorConfig.TASK_EXECUTION_TIMEOUT) as client:
        client_config = ClientConfig(httpx_client=client)
        client_factory = ClientFactory(config=client_config)
        a2a_client = client_factory.create(card=agent_card)

        response_iterator = a2a_client.send_message(new_agent_text_message(input_data))
        start_time = time.time()
        last_task = None
        while (time_left := _get_time_left_for_task_completion_waiting(start_time)) > 0:
            try:
                response = await asyncio.wait_for(response_iterator.__anext__(), timeout=time_left)
            except StopAsyncIteration:
                if last_task and last_task.status.state in (TaskState.completed, TaskState.failed, TaskState.rejected):
                    return last_task
                _handle_exception(f"Task '{task_description}' iterator finished before completion.", 500)
            except asyncio.TimeoutError:
                _handle_exception(f"Task '{task_description}' timed out while waiting for completion.", 408)

            if isinstance(response, JSONRPCErrorResponse):
                _handle_exception(f"Couldn't execute the task '{task_description}'. Root cause: {response.error}")

            if isinstance(response, tuple):
                task, _ = response
                last_task = task
                if task.status.state in (TaskState.completed, TaskState.failed, TaskState.rejected):
                    logger.info(f"Task '{task_description}' was completed with status '{str(task.status.state)}'.")
                    return task
                else:
                    logger.debug(
                        f"Task for {task_description} is still in '{task.status.state}' state. Waiting for its "
                        f"completion. Agent: '{agent_card.name}' (ID: {agent_id})")
            elif isinstance(response, Message):
                logger.info(
                    f"Received a message from agent in the scope of the "
                    f"task '{task_description}': {get_message_text(response)}")

        _handle_exception(f"Task for {task_description} wasn't complete within timeout.", 408)
        return None


async def _choose_agent_id(agent_task_description):
    if not agent_registry:
        _handle_exception("Orchestrator has currently no registered agents.", 404)
    agent_id = await _select_agent(agent_task_description)
    if not agent_id:
        _handle_exception(f"No agent found to handle the task '{agent_task_description}'.", 404)
    logger.info(
        f"Selected agent '{agent_registry[agent_id].name}' (ID: {agent_id}) for task '{agent_task_description}'.")
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
    valid_agent_ids = [agent_id for agent_id in selected_agent_ids if agent_id in agent_registry]
    for agent_id in valid_agent_ids:
        agent_name = agent_registry[agent_id].name
        logger.info(f"Selected agent '{agent_name}' with ID '{agent_id}' for task '{task_description}'.")
    return valid_agent_ids


async def _get_agents_info():
    agents_info = ""
    for agent_id, card in agent_registry.items():
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
    if selected_agent_id and selected_agent_id in agent_registry:
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
    for agent_card in await asyncio.gather(*tasks):
        if agent_card:
            # Check if an agent with this URL is already registered
            already_registered = False
            for agent_id, existing_card in agent_registry.items():
                if existing_card.url == agent_card.url:
                    logger.info(f"Agent with URL {agent_card.url} is already registered with ID {agent_id}. Skipping.")
                    already_registered = True
                    break
            if not already_registered:
                agent_id = str(uuid4())
                agent_registry[agent_id] = agent_card
                found_urls.append(agent_card.url)

    if found_urls:
        logger.info(f"Discovered and pre-registered agents with following URLs: {', '.join(found_urls)}")


if __name__ == "__main__":
    uvicorn.run(orchestrator_app, host=config.ORCHESTRATOR_HOST, port=config.ORCHESTRATOR_PORT)
