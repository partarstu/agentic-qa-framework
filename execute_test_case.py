# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

import argparse
import asyncio
import json
import time

from a2a.client import create_client
from a2a.types import Artifact, TaskState
from a2a.helpers import get_message_text, new_text_message

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
    except Exception:
        logger.exception(f"Failed to load test case '{test_case_key}'")
        raise


async def send_test_case_to_agent(agent_port: int, test_case: TestCase):
    """
    Sends the loaded test case to a locally running agent.
    """
    agent_base_url = f"{config.AGENT_BASE_URL}:{agent_port}"
    task_description = f"Execution of test case {test_case.key}"
    task_completion_timeout = 5000  # seconds

    try:
        a2a_client = await create_client(agent_base_url)

        response_iterator = a2a_client.send_message(request=new_text_message(test_case.model_dump_json()))
        logger.info(f"Successfully sent task for test case {test_case.key} to agent on port {agent_port}.")
        logger.info("Waiting for agent's response.")
        start_time = time.time()
        final_state = None
        final_status_message = None
        artifacts: list[Artifact] = []
        while (time.time() - start_time) < task_completion_timeout:
            time_left = task_completion_timeout - (time.time() - start_time)
            if time_left <= 0:
                break
            try:
                chunk = await asyncio.wait_for(response_iterator.__anext__(), timeout=time_left)
            except StopAsyncIteration:
                if final_state not in (
                    TaskState.TASK_STATE_COMPLETED,
                    TaskState.TASK_STATE_FAILED,
                    TaskState.TASK_STATE_REJECTED,
                ):
                    logger.error(f"Task '{task_description}' iterator finished before completion.")
                break
            except TimeoutError:
                logger.error(f"Task '{task_description}' timed out while waiting for completion.")
                break

            if chunk.HasField("error"):
                logger.error(f"Couldn't execute the task '{task_description}'. Root cause: {chunk.error}")
                return
            elif chunk.HasField("status_update"):
                task_status = chunk.status_update.status
                final_state = task_status.state
                final_status_message = task_status.message
                if final_state in (
                    TaskState.TASK_STATE_COMPLETED,
                    TaskState.TASK_STATE_FAILED,
                    TaskState.TASK_STATE_REJECTED,
                ):
                    break
                else:
                    logger.debug(
                        f"Task for {task_description} is still in '{final_state}' state. Waiting for its completion."
                    )
            elif chunk.HasField("artifact_update"):
                artifacts.append(chunk.artifact_update.artifact)
            elif chunk.HasField("message"):
                logger.info(
                    f"Received a message from agent during task '{task_description}': {get_message_text(chunk.message)}"
                )

        if final_state not in (
            TaskState.TASK_STATE_COMPLETED,
            TaskState.TASK_STATE_FAILED,
            TaskState.TASK_STATE_REJECTED,
        ):
            logger.error(f"Task for {task_description} wasn't complete within timeout.")
            return

        if final_state != TaskState.TASK_STATE_COMPLETED:
            status_message = (
                get_message_text(final_status_message) if final_status_message else "No details provided."
            )
            logger.error(
                f"Task for {task_description} has an unexpected status '{final_state!s}'. Root cause: {status_message}"
            )
            return

        logger.info("Retrieving agent's response.")
        if not artifacts:
            logger.warning(f"Agent provided no artifacts for task '{task_description}'.")
            return

        text_parts: list[str] = []
        if artifacts and artifacts[0] and artifacts[0].parts:
            for part in artifacts[0].parts:
                if part.HasField("text") and part.text:
                    text_parts.append(part.text)

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
    except Exception:
        logger.exception("An error occurred.")


if __name__ == "__main__":
    asyncio.run(main())
