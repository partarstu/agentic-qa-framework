# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for the additional Jira custom fields feature (WS4).

Tests cover:
- _parse_additional_field_ids: parsing, trimming, blank/duplicate removal and format validation.
- build_additional_fields_instruction: rendering the instruction template from the setting.
- _build_jira_issue_task_text: appending the instruction to the task text only when configured.
"""

import pytest

import config
from orchestrator.main import _build_jira_issue_task_text
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
