# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

"""
Example of parallel agent execution for processing multiple items concurrently.
"""

import asyncio

from common import utils
from orchestrator.main import _send_task_to_agent

logger = utils.get_logger("parallel_execution")


async def _process_items_in_parallel(items: list) -> list:
    """Process multiple items using parallel agent tasks."""
    
    async def _process_single_item(item) -> dict:
        """Helper coroutine for processing a single item."""
        task = await _send_task_to_agent(
            item.model_dump_json(),
            f"Process item {item.id}"
        )
        # Parse and return result
        return _parse_result(task)
    
    # Execute all tasks in parallel
    results = await asyncio.gather(
        *[_process_single_item(item) for item in items],
        return_exceptions=True  # Continue on individual failures
    )
    
    # Filter successful results and log failures
    successful_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"Failed to process item {i}: {result}")
        else:
            successful_results.append(result)
    
    return successful_results


def _parse_result(task):
    """Parse the result from a completed task."""
    # Implement based on your result model
    pass
