# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Recording mock of the procedure knowledge agent of the test-execution-agents repository for the smoke suite.

Like the real agent it declares its task capacity in a card extension, reads the test case from one data part and
answers with the Java agents' ``token_usage`` text artifact and the ``procedure_selection`` data artifact; it records
every request at ``GET /__recorded``.
"""

import json

from a2a.helpers import new_task_from_user_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentExtension, AgentInterface, AgentSkill, Part
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from common.a2a_data import data_objects, data_part
from common.models import (
    AggregationProcedures,
    ItemProcedures,
    ProcedureNode,
    ProcedureSelectionResult,
    ProcedureUiElement,
)

PROCEDURE_KNOWLEDGE_AGENT_NAME = "Smoke Procedure Knowledge Agent"
TASK_CAPACITY = 4
_TASK_CAPACITY_EXTENSION_URI = "urn:quaia:extensions:task-capacity:v1"
_CAPABILITY = (
    "Provides the recorded procedures (knowledge items) that best match each precondition and test step of a test "
    "case, and those that combine consecutive ones into one workflow."
)
_URL = "http://procedure_knowledge_agent:8001/"
_JSON_MODE = "application/json"

PRECONDITION_PROCEDURE = ProcedureNode(
    id="proc-register-user",
    description="Register a user account for registered.user@example.com through the sign-up form",
    is_precondition=True,
    effects=["A user account exists for registered.user@example.com"],
    success_count=12,
    children=[
        ProcedureNode(
            id="proc-submit-sign-up",
            description="Submit the sign-up form with the email address",
            atomic=True,
            test_data=["Email"],
            expected_results="The account confirmation page is shown",
            success_count=12,
            ui_element=ProcedureUiElement(name="Sign up button", own_description="Primary button of the sign-up form"),
        )
    ],
)
WORKFLOW_PROCEDURE = ProcedureNode(
    id="proc-request-reset-email",
    description="Request a password-reset link for registered.user@example.com and open the reset email",
    test_data=["Email"],
    expected_results="The password-reset email with a single-use reset link is open",
    prerequisites=["A user account exists for registered.user@example.com"],
    success_count=7,
    children=[
        ProcedureNode(
            id="proc-submit-forgot-password",
            description="Submit the email address on the 'Forgot password' form",
            atomic=True,
            test_data=["Email"],
            expected_results="The form confirms that a password-reset email was sent",
            success_count=7,
            ui_element=ProcedureUiElement(name="Send reset link button"),
        ),
        ProcedureNode(
            id="proc-open-reset-email",
            description="Open the password-reset email in the mailbox",
            atomic=True,
            expected_results="The email contains a single-use password-reset link",
            success_count=7,
        ),
    ],
)
# The usage as the Java agents report it: their input token counts include the cached ones.
TOKEN_USAGE = [
    {
        "operationName": "procedure_item_selection",
        "responseModel": "smoke-knowledge-model",
        "inputTokens": 1200,
        "outputTokens": 60,
        "cachedTokens": 200,
    },
    {
        "operationName": "procedure_aggregation_selection",
        "responseModel": "smoke-knowledge-model",
        "inputTokens": 900,
        "outputTokens": 40,
        "cachedTokens": 0,
    },
]

_recorded: dict[str, list[dict]] = {"requests": []}


def select_procedures(request: dict) -> ProcedureSelectionResult:
    """The registration procedure for the first precondition, the reset workflow for a step that is already that
    workflow, and the reset workflow for the first two steps together."""
    items = [ItemProcedures(item_id="P1", procedures=[PRECONDITION_PROCEDURE])] if request["preconditions"] else []
    steps = request["steps"]
    items += [
        ItemProcedures(item_id=f"S{number}", procedures=[WORKFLOW_PROCEDURE])
        for number, step in enumerate(steps, start=1)
        if step["action"] == WORKFLOW_PROCEDURE.description
    ]
    aggregations = (
        [AggregationProcedures(item_ids=["S1", "S2"], procedures=[WORKFLOW_PROCEDURE])] if len(steps) >= 2 else []
    )
    return ProcedureSelectionResult(items=items, aggregations=aggregations)


class _ProcedureKnowledgeExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await event_queue.enqueue_event(context.current_task or new_task_from_user_message(context.message))
        await updater.start_work()
        [request] = data_objects(context.message.parts)
        _recorded["requests"].append(request)
        await updater.add_artifact(parts=[Part(text=json.dumps(TOKEN_USAGE))], name="token_usage")
        selection = select_procedures(request).model_dump(mode="json")
        await updater.add_artifact(parts=[data_part(selection)], name="procedure_selection")
        await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        await TaskUpdater(event_queue, context.task_id, context.context_id).cancel()


def _agent_card() -> AgentCard:
    card = AgentCard(
        name=PROCEDURE_KNOWLEDGE_AGENT_NAME,
        description=_CAPABILITY,
        version="1.0.0",
        default_input_modes=[_JSON_MODE],
        default_output_modes=[_JSON_MODE],
        capabilities=AgentCapabilities(
            streaming=True, extensions=[AgentExtension(uri=_TASK_CAPACITY_EXTENSION_URI, required=False)]
        ),
        skills=[
            AgentSkill(
                id="procedure-knowledge", name="Procedure Knowledge", description=_CAPABILITY, tags=["knowledge"]
            )
        ],
        supported_interfaces=[AgentInterface(protocol_binding="JSONRPC", url=_URL)],
    )
    card.capabilities.extensions[0].params.update({"capacity": TASK_CAPACITY})
    return card


async def _recorded_requests(_request: Request) -> JSONResponse:
    return JSONResponse(_recorded)


_card = _agent_card()
_request_handler = DefaultRequestHandler(
    agent_executor=_ProcedureKnowledgeExecutor(), task_store=InMemoryTaskStore(), agent_card=_card
)
app = Starlette(
    routes=[
        Route("/__recorded", _recorded_requests),
        *create_agent_card_routes(_card),
        *create_jsonrpc_routes(_request_handler, "/"),
    ]
)
