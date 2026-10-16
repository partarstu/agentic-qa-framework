# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Client of the procedure knowledge agent, reached through the orchestrator's delegation endpoint, and the rendering of
its selections for the models that assess them.
"""

import asyncio
import json
from typing import Any
from uuid import uuid4

import httpx
from a2a.client import ClientConfig, create_client
from a2a.helpers import get_message_text
from a2a.types import Artifact, Message, Role, SendMessageRequest, TaskState, TaskStatus
from pydantic import ValidationError

import config
from common import utils
from common.a2a_data import data_objects, data_part
from common.models import ProcedureNode, ProcedureSelectionResult, TestCase

logger = utils.get_logger("procedure_knowledge")

SELECTION_ARTIFACT_NAME = "procedure_selection"
_MAX_RESPONSE_BYTES = 2_000_000
_API_KEY_HEADER = "X-API-Key"


class ProcedureKnowledgeError(Exception):
    """Raised when the recorded procedures of a test case cannot be selected."""


def precondition_lines(test_case: TestCase) -> list[str]:
    """Return the non-blank lines of the test case's preconditions, one precondition each."""
    return [line.strip() for line in (test_case.preconditions or "").splitlines() if line.strip()]


def precondition_ids(test_case: TestCase) -> list[str]:
    """Return the IDs of the test case's preconditions as the knowledge agent numbers them: P1, P2, …."""
    return [f"P{number}" for number in range(1, len(precondition_lines(test_case)) + 1)]


def step_ids(test_case: TestCase) -> list[str]:
    """Return the IDs of the test case's steps as the knowledge agent numbers them: S1, S2, …."""
    return [f"S{number}" for number in range(1, len(test_case.steps) + 1)]


async def try_select_procedures(test_case: TestCase, label: str) -> ProcedureSelectionResult | None:
    """Return the recorded procedures selected for the test case, or None after logging why they are unavailable."""
    try:
        return await select_procedures(test_case)
    except ProcedureKnowledgeError as exc:
        logger.error("The recorded procedures of %s are unavailable: %s", label, exc)
        return None


async def select_procedures(test_case: TestCase) -> ProcedureSelectionResult:
    """Return the recorded procedures the knowledge agent selects for the items of the test case.

    Raises:
        ProcedureKnowledgeError: When the request cannot be sent, fails, times out or returns an invalid selection.
    """
    known_item_ids = [*precondition_ids(test_case), *step_ids(test_case)]
    if not known_item_ids:
        return ProcedureSelectionResult()
    if not config.INTERNAL_SERVICE_API_KEY:
        raise ProcedureKnowledgeError("INTERNAL_SERVICE_API_KEY is not configured.")
    timeout_seconds = config.TestCaseDesignAgentConfig.PROCEDURE_KNOWLEDGE_TIMEOUT_SECONDS
    try:
        async with asyncio.timeout(timeout_seconds):
            artifacts = await _delegate(_knowledge_request(test_case), timeout_seconds)
    except ProcedureKnowledgeError:
        raise
    except TimeoutError as exc:
        raise ProcedureKnowledgeError(f"No selection arrived within {timeout_seconds:.0f} s.") from exc
    except Exception as exc:
        # Every failure of the remote call means the same to the caller: the test case goes on without the selection.
        raise ProcedureKnowledgeError(f"The delegation request failed: {exc!r}") from exc
    return _selection(artifacts, known_item_ids)


def _knowledge_request(test_case: TestCase) -> dict[str, Any]:
    return {
        "name": test_case.name,
        "preconditions": precondition_lines(test_case),
        "steps": [
            {"action": step.action, "test_data": step.test_data, "expected_results": step.expected_results}
            for step in test_case.steps
        ],
    }


async def _delegate(payload: dict[str, Any], timeout_seconds: float) -> list[Artifact]:
    """Send the payload to the orchestrator for the knowledge agent and return the artifacts of the completed task."""
    request = {
        "capability": config.TestCaseDesignAgentConfig.PROCEDURE_KNOWLEDGE_CAPABILITY,
        "payload": payload,
        "timeout_seconds": timeout_seconds,
    }
    message = Message(role=Role.ROLE_USER, message_id=str(uuid4()), parts=[data_part(request)])
    headers = {_API_KEY_HEADER: config.INTERNAL_SERVICE_API_KEY or ""}
    async with httpx.AsyncClient(timeout=timeout_seconds, headers=headers) as httpx_client:
        client = await create_client(
            config.ORCHESTRATOR_DELEGATION_URL, client_config=ClientConfig(httpx_client=httpx_client)
        )
        status: TaskStatus | None = None
        artifacts: list[Artifact] = []
        async for chunk in client.send_message(SendMessageRequest(message=message)):
            if chunk.HasField("task"):
                status = chunk.task.status
                artifacts.extend(chunk.task.artifacts)
            elif chunk.HasField("status_update"):
                status = chunk.status_update.status
            elif chunk.HasField("artifact_update"):
                artifacts.append(chunk.artifact_update.artifact)
    if status is None or status.state != TaskState.TASK_STATE_COMPLETED:
        state = TaskState.Name(status.state) if status else "no status"
        reason = get_message_text(status.message) if status and status.HasField("message") else "no reason given"
        raise ProcedureKnowledgeError(f"The delegated task ended with {state}: {reason}")
    return artifacts


def _selection(artifacts: list[Artifact], known_item_ids: list[str]) -> ProcedureSelectionResult:
    """Return the validated selection of the selection artifact, whose item IDs must be the request's."""
    selection_artifacts = [artifact for artifact in artifacts if artifact.name == SELECTION_ARTIFACT_NAME]
    objects = data_objects(part for artifact in selection_artifacts for part in artifact.parts)
    if len(objects) != 1:
        raise ProcedureKnowledgeError(f"Expected one '{SELECTION_ARTIFACT_NAME}' data object, got {len(objects)}.")
    size = len(json.dumps(objects[0]).encode("utf-8"))
    if size > _MAX_RESPONSE_BYTES:
        raise ProcedureKnowledgeError(f"The selection has {size} bytes, more than the {_MAX_RESPONSE_BYTES} allowed.")
    try:
        selection = ProcedureSelectionResult.model_validate(objects[0])
    except ValidationError as exc:
        raise ProcedureKnowledgeError(f"The selection is invalid: {exc}") from None
    returned_ids = [item.item_id for item in selection.items]
    returned_ids += [item_id for aggregation in selection.aggregations for item_id in aggregation.item_ids]
    if unknown := sorted(set(returned_ids) - set(known_item_ids)):
        raise ProcedureKnowledgeError(f"The selection names unknown items {unknown}.")
    return selection


def procedure_nodes_by_id(selection: ProcedureSelectionResult) -> dict[str, ProcedureNode]:
    """Return every procedure of the selection's trees, the selected ones and their descendants, by its ID."""
    nodes: dict[str, ProcedureNode] = {}
    pending = [node for item in [*selection.items, *selection.aggregations] for node in item.procedures]
    while pending:
        node = pending.pop()
        nodes.setdefault(node.id, node)
        pending.extend(node.children)
    return nodes


def render_procedure_knowledge(test_case: TestCase, selection: ProcedureSelectionResult) -> str:
    """Render the test case's numbered items and the recorded procedures selected for them as indented trees."""
    preconditions = precondition_lines(test_case)
    item_lines = [f"P{number}: {text}" for number, text in enumerate(preconditions, start=1)]
    item_lines += [
        f"S{number}: Action: {step.action}; Data: {', '.join(step.test_data)}; Expected: {step.expected_results}"
        for number, step in enumerate(test_case.steps, start=1)
    ]
    sections = [f"Items:\n{'\n'.join(item_lines)}"]
    for item in selection.items:
        sections.append(_render_selected(f"Selected for {item.item_id}", item.procedures))
    for aggregation in selection.aggregations:
        sections.append(
            _render_selected(f"Selected for {', '.join(aggregation.item_ids)} together", aggregation.procedures)
        )
    return "\n\n".join(sections)


def _render_selected(heading: str, procedures: list[ProcedureNode]) -> str:
    if not procedures:
        return f"{heading}: no recorded procedure matches"
    lines = [line for procedure in procedures for line in _render_node(procedure, depth=1)]
    return f"{heading}:\n{'\n'.join(lines)}"


def _render_node(node: ProcedureNode, depth: int) -> list[str]:
    indent = "  " * depth
    flags = ["atomic" if node.atomic else "composite"]
    flags += [flag for flag, is_set in (("precondition", node.is_precondition), ("optional", node.optional)) if is_set]
    flags.append(f"executed successfully {node.success_count} time(s)")
    details = {
        "Test data names": ", ".join(node.test_data),
        "Expected results": node.expected_results,
        "Prerequisites": "; ".join(node.prerequisites),
        "Effects": "; ".join(node.effects),
        "Negated effects": "; ".join(node.negated_effects),
        "Additional info": node.additional_info or "",
        "UI element": _render_ui_element(node),
    }
    lines = [f"{indent}- [{node.id}] {node.description} ({', '.join(flags)})"]
    lines += [f"{indent}  {label}: {value}" for label, value in details.items() if value]
    if node.children_truncated:
        lines.append(f"{indent}  (further children are not shown)")
    for child in node.children:
        lines += _render_node(child, depth + 1)
    return lines


def _render_ui_element(node: ProcedureNode) -> str:
    element = node.ui_element
    if element is None:
        return ""
    parts = (element.name, element.own_description, element.anchors_description, element.parent_summary)
    return "; ".join(part for part in parts if part)
