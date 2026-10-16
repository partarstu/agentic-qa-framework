# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import asyncio
import logging
from collections.abc import AsyncIterator, Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from a2a.helpers import new_text_message
from a2a.types import (
    Artifact,
    StreamResponse,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)

import config
from common.a2a_data import data_objects, data_part
from common.models import ProcedureSelectionResult, TestCase, TestStep
from common.services import procedure_knowledge
from common.services.procedure_knowledge import (
    ProcedureKnowledgeError,
    procedure_nodes_by_id,
    render_procedure_knowledge,
    select_procedures,
    try_select_procedures,
)

_KEY = "internal-key"


def _node(node_id: str, children: list[dict[str, Any]] | None = None, **fields: Any) -> dict[str, Any]:
    return {"id": node_id, "description": f"Procedure {node_id}", "children": children or [], **fields}


_SELECTION = {
    "items": [
        {"item_id": "P1", "procedures": []},
        {"item_id": "S1", "procedures": [_node("login", [_node("type-user", atomic=True)], success_count=3.0)]},
    ],
    "aggregations": [{"item_ids": ["S1", "S2"], "procedures": [_node("checkout")]}],
}


def _test_case() -> TestCase:
    return TestCase(
        key=None, labels=[], name="Checkout", summary="", comment="", parent_issue_key=None,
        preconditions="User exists\n\n  Cart is filled  ",
        steps=[
            TestStep(action="Log in", expected_results="Logged in", test_data=["user: john"]),
            TestStep(action="Pay", expected_results="Paid", test_data=[]),
        ],
    )  # fmt: skip


def _status(state: TaskState, reason: str | None = None) -> StreamResponse:
    status = TaskStatus(state=state, message=new_text_message(reason) if reason else None)
    return StreamResponse(status_update=TaskStatusUpdateEvent(task_id="task-1", status=status))


def _artifact(data: dict[str, Any], name: str = procedure_knowledge.SELECTION_ARTIFACT_NAME) -> StreamResponse:
    artifact = Artifact(artifact_id=name, name=name, parts=[data_part(data)])
    return StreamResponse(artifact_update=TaskArtifactUpdateEvent(task_id="task-1", artifact=artifact))


def _completed_with(*artifact_chunks: StreamResponse) -> list[StreamResponse]:
    return [_status(TaskState.TASK_STATE_WORKING), *artifact_chunks, _status(TaskState.TASK_STATE_COMPLETED)]


@pytest.fixture
def orchestrator(monkeypatch: pytest.MonkeyPatch) -> Iterator[MagicMock]:
    """The orchestrator's A2A client, answering every message with the chunks set on `chunks`."""
    monkeypatch.setattr(config, "INTERNAL_SERVICE_API_KEY", _KEY)
    client = MagicMock()
    client.chunks = _completed_with(_artifact(_SELECTION))

    async def stream(_request: Any) -> AsyncIterator[StreamResponse]:
        for chunk in client.chunks:
            yield chunk

    client.send_message = MagicMock(side_effect=stream)
    with patch("common.services.procedure_knowledge.create_client", new_callable=AsyncMock) as create:
        create.return_value = client
        client.create = create
        yield client


async def test_the_delegation_request_carries_the_numbered_test_case_and_the_selection_is_returned(orchestrator):
    selection = await select_procedures(_test_case())

    assert selection == ProcedureSelectionResult.model_validate(_SELECTION)
    assert selection.items[1].procedures[0].success_count == 3
    url = orchestrator.create.await_args.args[0]
    httpx_client = orchestrator.create.await_args.kwargs["client_config"].httpx_client
    assert url == config.ORCHESTRATOR_DELEGATION_URL
    assert httpx_client.headers["X-API-Key"] == _KEY
    message = orchestrator.send_message.call_args.args[0].message
    assert data_objects(message.parts) == [
        {
            "capability": config.TestCaseDesignAgentConfig.PROCEDURE_KNOWLEDGE_CAPABILITY,
            "timeout_seconds": config.TestCaseDesignAgentConfig.PROCEDURE_KNOWLEDGE_TIMEOUT_SECONDS,
            "payload": {
                "name": "Checkout",
                "preconditions": ["User exists", "Cart is filled"],
                "steps": [
                    {"action": "Log in", "test_data": ["user: john"], "expected_results": "Logged in"},
                    {"action": "Pay", "test_data": [], "expected_results": "Paid"},
                ],
            },
        }
    ]


async def test_other_artifacts_of_the_delegated_task_are_ignored(orchestrator):
    orchestrator.chunks = _completed_with(_artifact({"input_tokens": 3.0}, name="token_usage"), _artifact(_SELECTION))

    selection = await select_procedures(_test_case())

    assert [item.item_id for item in selection.items] == ["P1", "S1"]


async def test_a_selection_answered_as_a_whole_task_is_returned(orchestrator):
    completed = Task(
        id="task-1",
        status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED),
        artifacts=[Artifact(artifact_id="selection", name="procedure_selection", parts=[data_part(_SELECTION)])],
    )
    orchestrator.chunks = [StreamResponse(task=completed)]

    selection = await select_procedures(_test_case())

    assert selection == ProcedureSelectionResult.model_validate(_SELECTION)


async def test_a_test_case_without_items_needs_no_request(orchestrator):
    empty = _test_case().model_copy(update={"preconditions": " \n", "steps": []})

    assert await select_procedures(empty) == ProcedureSelectionResult()
    orchestrator.create.assert_not_awaited()


async def test_a_missing_internal_service_key_fails_without_a_request(orchestrator, monkeypatch):
    monkeypatch.setattr(config, "INTERNAL_SERVICE_API_KEY", None)

    with pytest.raises(ProcedureKnowledgeError, match="INTERNAL_SERVICE_API_KEY"):
        await select_procedures(_test_case())
    orchestrator.create.assert_not_awaited()


@pytest.mark.parametrize(
    ("final_state", "reason", "expected"),
    [
        (TaskState.TASK_STATE_FAILED, "No agent fits", "TASK_STATE_FAILED: No agent fits"),
        (TaskState.TASK_STATE_REJECTED, None, "TASK_STATE_REJECTED: no reason given"),
    ],
)
async def test_a_failed_delegated_task_raises_with_its_reason(orchestrator, final_state, reason, expected):
    orchestrator.chunks = [_status(TaskState.TASK_STATE_WORKING), _status(final_state, reason)]

    with pytest.raises(ProcedureKnowledgeError, match=expected):
        await select_procedures(_test_case())


async def test_a_stream_without_a_status_raises(orchestrator):
    orchestrator.chunks = []

    with pytest.raises(ProcedureKnowledgeError, match="no status"):
        await select_procedures(_test_case())


@pytest.mark.parametrize(
    ("artifacts", "expected"),
    [
        ([], "Expected one 'procedure_selection' data object, got 0"),
        ([_artifact(_SELECTION), _artifact(_SELECTION)], "got 2"),
        ([_artifact({"items": [{"item_id": "S1", "procedures": [{"id": "x"}]}]})], "The selection is invalid"),
        ([_artifact({"items": [{"item_id": "S9", "procedures": []}]})], r"unknown items \['S9'\]"),
        ([_artifact({"aggregations": [{"item_ids": ["P3", "S1"], "procedures": []}]})], r"unknown items \['P3'\]"),
    ],
    ids=["no-selection", "two-selections", "procedure-without-description", "unknown-item", "unknown-aggregated-item"],
)
async def test_an_invalid_selection_raises(orchestrator, artifacts, expected):
    orchestrator.chunks = _completed_with(*artifacts)

    with pytest.raises(ProcedureKnowledgeError, match=expected):
        await select_procedures(_test_case())


async def test_an_oversized_selection_raises(orchestrator, monkeypatch):
    monkeypatch.setattr(procedure_knowledge, "_MAX_RESPONSE_BYTES", 100)

    with pytest.raises(ProcedureKnowledgeError, match="more than the 100 allowed"):
        await select_procedures(_test_case())


async def test_a_request_without_an_answer_in_time_raises(orchestrator, monkeypatch):
    monkeypatch.setattr(config.TestCaseDesignAgentConfig, "PROCEDURE_KNOWLEDGE_TIMEOUT_SECONDS", 0.01)

    async def silent(_request: Any) -> AsyncIterator[StreamResponse]:
        await asyncio.Event().wait()
        yield _status(TaskState.TASK_STATE_COMPLETED)

    orchestrator.send_message.side_effect = silent

    with pytest.raises(ProcedureKnowledgeError, match="No selection arrived within 0 s"):
        await select_procedures(_test_case())


async def test_an_unreachable_orchestrator_raises(orchestrator):
    orchestrator.create.side_effect = httpx.ConnectError("connection refused")

    with pytest.raises(ProcedureKnowledgeError, match="connection refused"):
        await select_procedures(_test_case())


async def test_an_unavailable_selection_is_logged_as_an_error_and_returned_as_none(orchestrator, caplog):
    orchestrator.chunks = [_status(TaskState.TASK_STATE_FAILED, "Agent broken")]

    with caplog.at_level(logging.ERROR, logger="procedure_knowledge"):
        assert await try_select_procedures(_test_case(), "test case DRAFT-1 of PROJ-1") is None

    assert "The recorded procedures of test case DRAFT-1 of PROJ-1 are unavailable" in caplog.text
    assert "Agent broken" in caplog.text


def test_the_procedures_by_id_include_the_descendants_of_every_selected_procedure():
    selection = ProcedureSelectionResult.model_validate(_SELECTION)

    assert sorted(procedure_nodes_by_id(selection)) == ["checkout", "login", "type-user"]
    assert procedure_nodes_by_id(ProcedureSelectionResult()) == {}


def test_the_rendering_numbers_the_items_and_indents_the_procedure_trees():
    selection = ProcedureSelectionResult.model_validate(
        {
            **_SELECTION,
            "items": [
                {"item_id": "P1", "procedures": []},
                {
                    "item_id": "S1",
                    "procedures": [
                        _node(
                            "login",
                            [
                                _node(
                                    "type-user", atomic=True, test_data=["username"], ui_element={"name": "User field"}
                                )
                            ],
                            is_precondition=True,
                            prerequisites=["app opened"],
                            effects=["logged in"],
                            children_truncated=True,
                        )
                    ],
                },
            ],
        }
    )

    rendered = render_procedure_knowledge(_test_case(), selection)

    assert rendered == (
        "Items:\n"
        "P1: User exists\n"
        "P2: Cart is filled\n"
        "S1: Action: Log in; Data: user: john; Expected: Logged in\n"
        "S2: Action: Pay; Data: ; Expected: Paid\n\n"
        "Selected for P1: no recorded procedure matches\n\n"
        "Selected for S1:\n"
        "  - [login] Procedure login (composite, precondition, executed successfully 0 time(s))\n"
        "    Prerequisites: app opened\n"
        "    Effects: logged in\n"
        "    (further children are not shown)\n"
        "    - [type-user] Procedure type-user (atomic, executed successfully 0 time(s))\n"
        "      Test data names: username\n"
        "      UI element: User field\n\n"
        "Selected for S1, S2 together:\n"
        "  - [checkout] Procedure checkout (composite, executed successfully 0 time(s))"
    )
