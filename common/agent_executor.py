# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import (
    TaskStatus,
    TaskState,
    TaskStatusUpdateEvent,
    TaskArtifactUpdateEvent, Message, )
from a2a.utils import new_agent_text_message, new_artifact

from common import utils

logger = utils.get_logger("agent_executor")


class DefaultAgentExecutor(AgentExecutor):
    """
    Executes tasks by invoking the pydantic-ai agent.
    """

    def __init__(self, agent):
        self.agent = agent

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id = context.task_id
        logger.info(f"Executing task {task_id}")

        try:
            received_message = context.message
            if not received_message:
                raise ValueError("No message found in the request message.")
            await self._update_task_status(context, event_queue, TaskState.working)

            result:Message = await self.agent.run(received_message)
            event = TaskArtifactUpdateEvent(
                context_id=context.context_id,
                task_id=task_id,
                artifact=new_artifact(
                    name='agent_execution_result',
                    parts=result.parts
                )
            )
            await event_queue.enqueue_event(event)

            await self._update_task_status(context, event_queue, TaskState.completed, final=True)
            logger.info(f"Task {task_id} completed successfully.")

        except Exception as e:
            logger.exception(f"Error executing task {task_id}: {e}", exc_info=e)
            error_message = f"An error occurred: {str(e)}"
            await self._update_task_status(context, event_queue, TaskState.failed,
                                           final=True, message=error_message)

    @staticmethod
    async def _update_task_status(context: RequestContext, event_queue: EventQueue, state: TaskState, final=False,
                                  message: str = None):
        status = TaskStatus(state=state)
        if message:
            status.message = new_agent_text_message(message)
        event = TaskStatusUpdateEvent(
            context_id=context.context_id,
            task_id=context.task_id,
            status=status,
            final=final
        )
        await event_queue.enqueue_event(event)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        logger.warning(f"Got request to cancel task {context.task_id}, but cancelling is not supported for now")
