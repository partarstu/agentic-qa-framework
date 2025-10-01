# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

import argparse
import asyncio
import json
import time

import httpx
from a2a.client import ClientFactory, ClientConfig, minimal_agent_card
from a2a.types import JSONRPCErrorResponse, Task, Artifact, TextPart, TaskState, Message
from a2a.utils import new_agent_text_message, get_message_text

import config
from common import utils
from common.models import TestCase
from common.services.test_management_system_client_provider import get_test_management_client

logger = utils.get_logger("test_case_executor")


async def load_test_case(test_case_key: str) -> TestCase:
    """
    Loads a single test case by its key from the test management system.
    """
    try:
        test_management_client = get_test_management_client()
        test_case = test_management_client.fetch_test_case_by_key(test_case_key)
        if not test_case:
            raise ValueError(f"Test case with key '{test_case_key}' not found.")
        return test_case
    except Exception as e:
        logger.error(f"Failed to load test case '{test_case_key}': {e}")
        raise


async def send_test_case_to_agent(agent_port: int, test_case: TestCase):
    """
    Sends the loaded test case to a locally running agent.
    """
    agent_base_url = f"{config.AGENT_BASE_URL}:{agent_port}"
    task_description = f"Execution of test case {test_case.key}"
    task_completion_timeout = 5000  # seconds

    try:
        async with httpx.AsyncClient(timeout=task_completion_timeout) as client:
            client_config = ClientConfig(httpx_client=client)
            client_factory = ClientFactory(config=client_config)
            a2a_client = client_factory.create(minimal_agent_card(url=agent_base_url))

            response_iterator = a2a_client.send_message(request=new_agent_text_message(test_case.model_dump_json()))
            logger.info(f"Successfully sent task for test case {test_case.key} to agent on port {agent_port}.")
            logger.info("Waiting for agent's response.")
            start_time = time.time()
            last_task = None
            completed_task = None
            while (time.time() - start_time) < task_completion_timeout:
                time_left = task_completion_timeout - (time.time() - start_time)
                if time_left <= 0:
                    break
                try:
                    response = await asyncio.wait_for(response_iterator.__anext__(), timeout=time_left)
                except StopAsyncIteration:
                    if last_task and last_task.status.state in (
                            TaskState.completed, TaskState.failed, TaskState.rejected):
                        completed_task = last_task
                    else:
                        logger.error(f"Task '{task_description}' iterator finished before completion.")
                    break  # Exit while loop
                except asyncio.TimeoutError:
                    logger.error(f"Task '{task_description}' timed out while waiting for completion.")
                    break  # Exit while loop

                if isinstance(response, JSONRPCErrorResponse):
                    logger.error(f"Couldn't execute the task '{task_description}'. Root cause: {response.error}")
                    return

                if isinstance(response, tuple):
                    task, _ = response
                    last_task = task
                    if task.status.state in (TaskState.completed, TaskState.failed, TaskState.rejected):
                        completed_task = task
                        break
                    else:
                        logger.debug(
                            f"Task for {task_description} is still in '{task.status.state}' state. Waiting for its "
                            f"completion.")
                elif isinstance(response, Message):
                    logger.info(
                        f"Received a message from agent during task '{task_description}': {get_message_text(response)}")

            if not completed_task:
                logger.error(f"Task for {task_description} wasn't complete within timeout.")
                return

            if completed_task.status.state != TaskState.completed:
                status_message = get_message_text(
                    completed_task.status.message) if completed_task.status.message else "No details provided."
                logger.error(f"Task for {task_description} has an unexpected status "
                             f"'{str(completed_task.status.state)}'. Root cause: {status_message}")
                return

            logger.info("Retrieving agent's response.")
            results: list[Artifact] = completed_task.artifacts
            if not results:
                logger.warning(f"Agent provided no artifacts for task '{task_description}'.")
                return

            text_parts: list[str] = []
            if results and results[0] and results[0].parts:
                for part in results[0].parts:
                    if isinstance(part.root, TextPart):
                        text_parts.append(part.root.text)

            if not text_parts:
                logger.info("No text parts in the result artifacts.")
                return

            logger.info(f"Successfully processed task for test case {test_case.key} from agent on port {agent_port}.")

            for text_part in text_parts:
                try:
                    parsed_json = json.loads(text_part)
                    pretty_results = json.dumps(parsed_json, indent=2)
                    logger.info(f"Results:\n{pretty_results}")
                except json.JSONDecodeError:
                    logger.info(f"Results (raw):\n{text_part}")

    except Exception as e:
        logger.exception(f"Failed to send test case to agent on port {agent_port}. Error: {e}")


async def main():
    """
    Main function to parse arguments and orchestrate the process.
    """
    parser = argparse.ArgumentParser(description="Load a test case and send it to a local agent.")
    parser.add_argument("test_case_key", help="The ID or key of the test case to load.")
    parser.add_argument("agent_port", type=int, help="The port of the locally running test execution agent.")
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv()
        
        test_case = await load_test_case(args.test_case_key)
        await send_test_case_to_agent(args.agent_port, test_case)
    except Exception as e:
        logger.error(f"An error occurred: {e}")


if __name__ == "__main__":
    asyncio.run(main())
