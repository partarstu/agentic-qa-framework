# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

import argparse
import asyncio
import json
from uuid import uuid4

import httpx
from a2a.client import A2AClient
from a2a.types import SendMessageRequest, MessageSendParams, JSONRPCErrorResponse, Task, Artifact, TextPart
from a2a.utils import new_agent_text_message

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

    try:
        async with httpx.AsyncClient(timeout=5000) as client:
            a2a_client: A2AClient = A2AClient(httpx_client=client, url=agent_base_url)
            request = SendMessageRequest(
                id=uuid4().hex,
                params=MessageSendParams(message=new_agent_text_message(test_case.model_dump_json()))
            )

            response = await a2a_client.send_message(request)
            logger.info(f"Successfully sent task for test case {test_case.key} to agent on port {agent_port}.")

            logger.info("Retrieving agent's response.")
            result = response.root
            if isinstance(result, JSONRPCErrorResponse):
                logger.error(f"Couldn't execute the task '{task_description}'. Root cause: {result.error}")
            else:
                task:Task = result.result
                results: list[Artifact] = task.artifacts
                text_parts: list[str] = []
                for part in (results[0] or []).parts or []:
                    if isinstance(part.root, TextPart):
                        text_parts.append(part.root.text)
                logger.info(f"Successfully sent task for test case {test_case.key} to agent on port {agent_port}.")

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
