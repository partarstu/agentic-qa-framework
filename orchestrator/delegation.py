# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""The orchestrator's own A2A agent, through which the agents it supervises delegate a task to the registered agent whose
capability fits it.
"""

import asyncio
import hmac
import json
from collections.abc import Awaitable, Callable
from typing import Any, Protocol
from uuid import uuid4

from a2a.helpers import new_task_from_user_message, new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, Artifact, Message, Role
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

import config
from common import utils
from common.a2a_data import data_objects, data_part

logger = utils.get_logger("orchestrator_delegation")

DELEGATION_CAPABILITY = (
    "Delegates a task to the registered agent whose capability fits it and returns that agent's artifacts."
)
DELEGATION_PATH = config.ORCHESTRATOR_DELEGATION_PATH
_MAX_CAPABILITY_LENGTH = 1000
_MAX_PAYLOAD_BYTES = 1_000_000
_API_KEY_HEADER = "X-API-Key"
_JSON_MODE = "application/json"


class DelegationRequest(BaseModel):
    """The data part of a delegation request: the capability that selects the agent and the payload it receives."""

    model_config = ConfigDict(extra="forbid")

    capability: str = Field(min_length=1, max_length=_MAX_CAPABILITY_LENGTH)
    payload: dict[str, Any]
    timeout_seconds: float = Field(gt=0)

    @field_validator("payload")
    @classmethod
    def _limit_payload_size(cls, payload: dict[str, Any]) -> dict[str, Any]:
        size = len(json.dumps(payload).encode("utf-8"))
        if size > _MAX_PAYLOAD_BYTES:
            raise ValueError(f"payload has {size} bytes, more than the {_MAX_PAYLOAD_BYTES} allowed")
        return payload


class Delegate(Protocol):
    """Sends the message to the agent the routing selects for the description and returns its artifacts.

    Raises:
        HTTPException: When no agent fits, the task times out or the agent fails; the error is already recorded.
    """

    def __call__(
        self, message: Message, task_description: str, timeout_seconds: float
    ) -> Awaitable[list[Artifact]]: ...


def read_delegation_request(message: Message | None) -> DelegationRequest:
    """Return the delegation request of the message's single data part.

    Raises:
        ValueError: When the message carries no single data part with a valid request.
    """
    objects = data_objects(message.parts) if message else []
    if len(objects) != 1:
        raise ValueError(f"the message must carry exactly one data part, but carries {len(objects)}")
    try:
        return DelegationRequest.model_validate(objects[0])
    except ValidationError as exc:
        reasons = "; ".join(f"{'.'.join(map(str, error['loc']))}: {error['msg']}" for error in exc.errors())
        raise ValueError(reasons) from None


class DelegationExecutor(AgentExecutor):
    """Runs each delegation request as one task of the agent the routing selects; requests run concurrently."""

    def __init__(self, delegate: Delegate, record_error: Callable[[str], None]) -> None:
        self._delegate = delegate
        self._record_error = record_error
        self._active_delegations: dict[str, asyncio.Task[list[Artifact]]] = {}

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await event_queue.enqueue_event(context.current_task or new_task_from_user_message(context.message))
        await updater.start_work()
        try:
            request = read_delegation_request(context.message)
        except ValueError as exc:
            reason = f"Invalid delegation request: {exc}"
            self._record_error(reason)
            await updater.failed(message=new_text_message(reason))
            return
        try:
            artifacts = await self._run_delegation(context.task_id, request)
        except asyncio.CancelledError:
            current_task = asyncio.current_task()
            if current_task is not None and current_task.cancelling():
                raise
            logger.info("Delegation task %s was cancelled.", context.task_id)
            await updater.cancel()
            return
        except HTTPException as exc:
            await updater.failed(message=new_text_message(str(exc.detail)))
            return
        except Exception as exc:
            reason = f"Delegating the task '{request.capability}' failed: {exc}"
            self._record_error(reason)
            await updater.failed(message=new_text_message(reason))
            return
        for artifact in artifacts:
            await updater.add_artifact(parts=list(artifact.parts), name=artifact.name or None)
        await updater.complete()

    async def _run_delegation(self, task_id: str, request: DelegationRequest) -> list[Artifact]:
        message = Message(role=Role.ROLE_USER, message_id=str(uuid4()), parts=[data_part(request.payload)])
        timeout_seconds = min(request.timeout_seconds, config.OrchestratorConfig.DELEGATION_MAX_TIMEOUT_SECONDS)
        delegation = asyncio.create_task(self._delegate(message, request.capability, timeout_seconds))
        self._active_delegations[task_id] = delegation
        try:
            return await delegation
        finally:
            self._active_delegations.pop(task_id, None)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        delegation = self._active_delegations.get(context.task_id)
        if delegation is not None:
            # execute() emits the CANCELED status once the delegation has stopped.
            delegation.cancel()
        else:
            await TaskUpdater(event_queue, context.task_id, context.context_id).cancel()


class InternalServiceKeyMiddleware:
    """Admits only requests carrying the internal service key, and fails closed while that key is not configured."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            rejection = _rejection(Headers(scope=scope).get(_API_KEY_HEADER))
            if rejection is not None:
                await rejection(scope, receive, send)
                return
        await self._app(scope, receive, send)


def _rejection(api_key: str | None) -> JSONResponse | None:
    configured_key = config.INTERNAL_SERVICE_API_KEY
    if not configured_key:
        logger.error("INTERNAL_SERVICE_API_KEY is not configured; rejecting a request to the delegation endpoint.")
        return JSONResponse({"detail": "Server authentication is not configured."}, status_code=503)
    if not api_key or not hmac.compare_digest(api_key, configured_key):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return None


def build_agent_card(url: str) -> AgentCard:
    return AgentCard(
        name="QuAIA Orchestrator",
        description=DELEGATION_CAPABILITY,
        version=config.OrchestratorConfig.VERSION,
        default_input_modes=[_JSON_MODE],
        default_output_modes=[_JSON_MODE],
        capabilities=AgentCapabilities(streaming=True),
        skills=[
            AgentSkill(
                id="task_delegation",
                name="Task Delegation",
                description=DELEGATION_CAPABILITY,
                tags=["delegation", "routing"],
            )
        ],
        supported_interfaces=[AgentInterface(protocol_binding="JSONRPC", url=url)],
    )


def create_delegation_app(executor: DelegationExecutor, url: str) -> Starlette:
    """Return the A2A application of the orchestrator, guarded by the internal service key, to mount at the given URL."""
    agent_card = build_agent_card(url)
    request_handler = DefaultRequestHandler(
        agent_executor=executor, task_store=InMemoryTaskStore(), agent_card=agent_card
    )
    routes = [*create_agent_card_routes(agent_card), *create_jsonrpc_routes(request_handler, "/")]
    return Starlette(routes=routes, middleware=[Middleware(InternalServiceKeyMiddleware)])
