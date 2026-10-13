# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import pytest

import config


def test_unset_thinking_level_gives_the_default(monkeypatch):
    monkeypatch.delenv("SOME_AGENT_THINKING_LEVEL", raising=False)

    assert config._thinking_level("SOME_AGENT", "medium") == "medium"
    assert config._thinking_level("SOME_AGENT", None) is None


def test_blank_thinking_level_gives_the_default(monkeypatch):
    monkeypatch.setenv("SOME_AGENT_THINKING_LEVEL", "  ")

    assert config._thinking_level("SOME_AGENT", "low") == "low"


@pytest.mark.parametrize("raw", ["none", "NONE", " None "])
def test_none_turns_thinking_off_whatever_the_default(monkeypatch, raw):
    monkeypatch.setenv("SOME_AGENT_THINKING_LEVEL", raw)

    assert config._thinking_level("SOME_AGENT", "high") is None


@pytest.mark.parametrize("level", ["minimal", "low", "medium", "high", "xhigh"])
def test_each_level_overrides_the_default(monkeypatch, level):
    monkeypatch.setenv("SOME_AGENT_THINKING_LEVEL", level.upper())

    assert config._thinking_level("SOME_AGENT", None) == level


@pytest.mark.parametrize("raw", ["true", "off", "extreme"])
def test_an_unknown_thinking_level_raises(monkeypatch, raw):
    monkeypatch.setenv("SOME_AGENT_THINKING_LEVEL", raw)

    with pytest.raises(ValueError, match="SOME_AGENT_THINKING_LEVEL"):
        config._thinking_level("SOME_AGENT", "low")


def test_agent_default_thinking_levels():
    assert {
        "orchestrator": config.OrchestratorConfig.THINKING_LEVEL,
        "requirements_review": config.RequirementsReviewAgentConfig.THINKING_LEVEL,
        "test_case_design": config.TestCaseDesignAgentConfig.THINKING_LEVEL,
        "test_case_generation": config.TestCaseGenerationAgentConfig.THINKING_LEVEL,
        "test_case_review": config.TestCaseReviewAgentConfig.THINKING_LEVEL,
        "test_case_classification": config.TestCaseClassificationAgentConfig.THINKING_LEVEL,
        "incident_creation": config.IncidentCreationAgentConfig.THINKING_LEVEL,
    } == {
        "orchestrator": "low",
        "requirements_review": "medium",
        "test_case_design": "low",
        "test_case_generation": "medium",
        "test_case_review": "medium",
        "test_case_classification": "medium",
        "incident_creation": "medium",
    }


def test_qwen_presence_penalty_defaults():
    assert config.QWEN_NON_THINKING_PRESENCE_PENALTY == 0.0
    assert config.QWEN_THINKING_PRESENCE_PENALTY == 0.5
