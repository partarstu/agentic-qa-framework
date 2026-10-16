# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for the procedure knowledge agent mock; they need no stack, so they carry no ``smoke`` marker."""

from a2a.types import AgentCard
from fastapi.testclient import TestClient
from google.protobuf.json_format import ParseDict

from orchestrator.models import task_capacity
from tests.smoke.mocks import procedure_knowledge_agent
from tests.smoke.mocks.procedure_knowledge_agent import (
    PRECONDITION_PROCEDURE,
    TASK_CAPACITY,
    WORKFLOW_PROCEDURE,
    select_procedures,
)


def test_the_orchestrator_reads_the_declared_capacity_from_the_card() -> None:
    response = TestClient(procedure_knowledge_agent.app).get("/.well-known/agent-card.json")

    card = ParseDict(response.json(), AgentCard(), ignore_unknown_fields=True)

    assert task_capacity(card) == TASK_CAPACITY


def test_a_draft_gets_the_precondition_procedure_and_its_first_two_steps_one_workflow() -> None:
    selection = select_procedures(
        {"preconditions": ["A user account is registered."], "steps": [{"action": "Submit"}, {"action": "Open"}]}
    )

    assert [(item.item_id, [p.id for p in item.procedures]) for item in selection.items] == [
        ("P1", [PRECONDITION_PROCEDURE.id])
    ]
    assert [(a.item_ids, [p.id for p in a.procedures]) for a in selection.aggregations] == [
        (["S1", "S2"], [WORKFLOW_PROCEDURE.id])
    ]


def test_a_rebuilt_test_case_gets_the_workflow_for_its_step_that_already_is_the_workflow() -> None:
    selection = select_procedures({"preconditions": [], "steps": [{"action": WORKFLOW_PROCEDURE.description}]})

    assert [(item.item_id, [p.id for p in item.procedures]) for item in selection.items] == [
        ("S1", [WORKFLOW_PROCEDURE.id])
    ]
    assert selection.aggregations == []
