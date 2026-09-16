# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for the additional Jira custom fields feature (WS4).

Tests cover:
- _parse_additional_field_ids: parsing, trimming, blank/duplicate removal and format validation.
- build_additional_fields_instruction: rendering the instruction template from the setting.
- _build_jira_issue_task_text: appending the instruction to the task text only when configured.
"""

import contextlib
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

import config
from orchestrator.main import (
    _build_jira_issue_task_text,
    _request_test_cases_generation,
    _request_test_cases_review,
    _validate_api_key,
    orchestrator_app,
)
from orchestrator.prompt import ADDITIONAL_FIELDS_INSTRUCTION_TEMPLATE, build_additional_fields_instruction

# =============================================================================
# Config parsing
# =============================================================================


def test_parse_additional_field_ids_drops_blanks_and_duplicates_and_trims():
    raw = " customfield_10001 , ,customfield_10001,customfield_20002 "
    assert config._parse_additional_field_ids(raw) == ("customfield_10001", "customfield_20002")


def test_parse_additional_field_ids_unset_or_empty_returns_empty_tuple():
    assert config._parse_additional_field_ids(None) == ()
    assert config._parse_additional_field_ids("") == ()


@pytest.mark.parametrize(
    "raw",
    [
        "customfield",
        "customfield_",
        "customfield_abc",
        "customfield_10001x",
        "Customfield_10001",
        "customfield-10001",
        "summary",
    ],
)
def test_parse_additional_field_ids_rejects_invalid_entries(raw):
    with pytest.raises(ValueError, match="not a valid Jira custom field ID"):
        config._parse_additional_field_ids(raw)


# =============================================================================
# Instruction rendering
# =============================================================================


def test_instruction_template_loads_with_expected_placeholder():
    assert "{additional_field_ids}" in ADDITIONAL_FIELDS_INSTRUCTION_TEMPLATE.template


def test_build_additional_fields_instruction_empty_when_unset(monkeypatch):
    monkeypatch.setattr(config, "JIRA_ADDITIONAL_FIELD_IDS", ())
    assert build_additional_fields_instruction() == ""


def test_build_additional_fields_instruction_names_configured_ids(monkeypatch):
    monkeypatch.setattr(config, "JIRA_ADDITIONAL_FIELD_IDS", ("customfield_10001", "customfield_20002"))
    instruction = build_additional_fields_instruction()
    assert "customfield_10001, customfield_20002" in instruction
    # The pitfall wording: the agent must not lose the base issue content through the fields parameter.
    assert "standard content fields" in instruction
    assert "review or generation tools" in instruction


# =============================================================================
# Task text building
# =============================================================================


def test_build_jira_issue_task_text_without_additional_fields(monkeypatch):
    monkeypatch.setattr(config, "JIRA_ADDITIONAL_FIELD_IDS", ())
    assert _build_jira_issue_task_text("PROJ-42") == "Jira user story with key PROJ-42"


def test_build_jira_issue_task_text_with_additional_fields(monkeypatch):
    monkeypatch.setattr(config, "JIRA_ADDITIONAL_FIELD_IDS", ("customfield_10001",))
    task_text = _build_jira_issue_task_text("PROJ-42")
    assert task_text.startswith("Jira user story with key PROJ-42")
    assert "customfield_10001" in task_text
    assert build_additional_fields_instruction() in task_text


# =============================================================================
# Every flow that hands a Jira issue to an agent
# =============================================================================


class _FlowStopped(Exception):
    """Stops a flow right after its task was sent, so only the task text is inspected."""


async def _run_requirements_review_flow(issue_key: str) -> None:
    with patch.dict(orchestrator_app.dependency_overrides, {_validate_api_key: lambda: None}):
        TestClient(orchestrator_app).post("/new-requirements-available", json={"issue_key": issue_key})


@pytest.mark.parametrize(
    "run_flow",
    [
        _run_requirements_review_flow,
        _request_test_cases_generation,
        lambda issue_key: _request_test_cases_review([], issue_key),
    ],
    ids=["requirements-review", "test-case-generation", "test-case-review"],
)
async def test_every_jira_issue_flow_sends_the_additional_fields_instruction(monkeypatch, run_flow):
    monkeypatch.setattr(config, "JIRA_ADDITIONAL_FIELD_IDS", ("customfield_10001",))
    with patch("orchestrator.main._send_task_to_agent", new_callable=AsyncMock) as mock_send:
        mock_send.side_effect = _FlowStopped
        with contextlib.suppress(_FlowStopped):
            await run_flow("PROJ-42")

    mock_send.assert_awaited_once()
    assert build_additional_fields_instruction() in mock_send.await_args.args[0]
