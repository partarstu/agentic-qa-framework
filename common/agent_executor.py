# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

import asyncio
import contextlib
import logging

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import (
    Artifact,
    Part,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from a2a.helpers import (
    new_text_message,
    new_text_status_update_event,
    new_task_from_user_message,
)

import config
from common import utils
from common.agent_log_capture import AgentLogCaptureHandler
from common.models import AgentRuntimeError
from common.streaming import (
    StreamEmitter,
    reset_current_emitter,
    reset_current_log_handler,
    set_current_emitter,
    set_current_log_handler,
)

logger = utils.get_logger("agent_executor")

_LOG_FLUSH_INTERVAL_SECONDS = 2


def _make_artifact_event(
    task_id: str, context_id: str, name: str, parts: list
) -> TaskArtifactUpdateEvent:
    """Build a TaskArtifactUpdateEvent for the given artifact name and parts."""
    return TaskArtifactUpdateEvent(
        context_id=context_id,
        task_id=task_id,
        artifact=Artifact(name=name, parts=parts),
    )


class DefaultAgentExecutor(AgentExecutor):
    """
    Executes tasks by invoking the pydantic-ai agent.

    Log handler ownership: this executor creates an AgentLogCaptureHandler per task,
    attaches it to the root logger, and exposes it via a ContextVar so that AgentBase.run
    can reuse the same buffer for the final message-with-logs artifact.
    """

    def __init__(self, agent):
        self.agent = agent
        self._active_runs: dict[str, tuple[asyncio.Task, EventQueue]] = {}

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id = context.task_id
        logger.info(f"Executing task {task_id}")

        try:
            received_message = context.message
            if not received_message:
                raise ValueError("No message found in the request message.")

            # v1.0: Must enqueue the Task object FIRST
            task = context.current_task or new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)

            await self._update_task_status(context, event_queue, TaskState.TASK_STATE_WORKING)

            emitter = self._build_emitter(task_id, context.context_id, event_queue)
            log_handler = AgentLogCaptureHandler()
            log_handler.setLevel(config.LOG_LEVEL)
            root_logger = logging.getLogger()
            root_logger.addHandler(log_handler)
            emitter_token = set_current_emitter(emitter)
            handler_token = set_current_log_handler(log_handler)

            # create_task snapshots the current context, so the agent sees both contextvars
            flush_task = asyncio.create_task(self._flush_logs_loop(log_handler, emitter))
            run_task = asyncio.create_task(self.agent.run(received_message))
            self._active_runs[task_id] = (run_task, event_queue)
            try:
                result = await run_task
            finally:
                self._active_runs.pop(task_id, None)
                flush_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await flush_task
                # Final drain BEFORE detaching — ensures no log lines are lost
                remaining = log_handler.drain()
                if remaining:
                    emitter.on_log_batch(remaining)
                reset_current_emitter(emitter_token)
                reset_current_log_handler(handler_token)
                root_logger.removeHandler(log_handler)

            await event_queue.enqueue_event(
                _make_artifact_event(task_id, context.context_id, "agent_execution_result", result.parts)
            )
            await self._update_task_status(context, event_queue, TaskState.TASK_STATE_COMPLETED)
            logger.info(f"Task {task_id} completed successfully.")

        except AgentRuntimeError as e:
            logger.error(f"Agent execution failed for task {task_id}: {e}")
            await event_queue.enqueue_event(
                _make_artifact_event(task_id, context.context_id, "agent_execution_result", e.parts)
            )
            await self._update_task_status(context, event_queue, TaskState.TASK_STATE_FAILED, message=str(e))

        except Exception as e:
            logger.exception(f"Error executing task {task_id}: {e}")
            await self._update_task_status(
                context, event_queue, TaskState.TASK_STATE_FAILED, message=f"An error occurred: {e!s}"
            )

    def _build_emitter(self, task_id: str, context_id: str, event_queue: EventQueue) -> StreamEmitter:
        """Create a StreamEmitter whose callbacks push A2A artifact events into event_queue."""

        def on_activity(text: str) -> None:
            asyncio.get_running_loop().create_task(
                event_queue.enqueue_event(
                    _make_artifact_event(task_id, context_id, "agent_activity", [Part(text=text)])
                )
            )

        def on_log_batch(lines: list[str]) -> None:
            asyncio.get_running_loop().create_task(
                event_queue.enqueue_event(
                    _make_artifact_event(task_id, context_id, "agent_logs_stream", [Part(text="\n".join(lines))])
                )
            )

        def on_step_result(payload_json: str) -> None:
            asyncio.get_running_loop().create_task(
                event_queue.enqueue_event(
                    _make_artifact_event(task_id, context_id, "test_step_result", [Part(text=payload_json)])
                )
            )

        return StreamEmitter(on_activity=on_activity, on_log_batch=on_log_batch, on_step_result=on_step_result)

    @staticmethod
    async def _flush_logs_loop(handler: AgentLogCaptureHandler, emitter: StreamEmitter) -> None:
        """Drain the log handler every 2 s and emit batches; runs until cancelled."""
        try:
            while True:
                await asyncio.sleep(_LOG_FLUSH_INTERVAL_SECONDS)
                batch = handler.drain()
                if batch:
                    emitter.on_log_batch(batch)
        except asyncio.CancelledError:
            pass

    @staticmethod
    async def _update_task_status(
        context: RequestContext, event_queue: EventQueue, state: TaskState, message: str | None = None
    ):
        status = TaskStatus(state=state, message=new_text_message(message) if message else None)
        event = TaskStatusUpdateEvent(
            context_id=context.context_id, task_id=context.task_id, status=status
        )
        await event_queue.enqueue_event(event)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id = context.task_id
        entry = self._active_runs.get(task_id)
        if entry is not None:
            run_task, original_queue = entry
            run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await run_task
            await self._update_task_status(context, original_queue, TaskState.TASK_STATE_CANCELED)
        else:
            logger.warning(f"No active run found for task {task_id}; emitting CANCELED on cancel-call's queue")
            await self._update_task_status(context, event_queue, TaskState.TASK_STATE_CANCELED)
