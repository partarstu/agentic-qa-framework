# SPDX-FileCopyrightText: 2025-2026 Taras Paruka (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

from pathlib import Path
from unittest.mock import mock_open, patch

import pytest

import config
from common.prompt_base import PromptBase


class MockPrompt(PromptBase):
    def get_prompt(self) -> str:
        return self.template

    def get_script_dir(self) -> Path:
        return Path("/tmp")


def test_prompt_base_success():
    with (
        patch("pathlib.Path.is_file", return_value=True),
        patch("pathlib.Path.read_text", return_value="template content"),
    ):
        prompt = MockPrompt("template.txt")
        assert prompt.template == "template content"
        assert prompt.get_prompt() == "template content"


def test_prompt_base_file_not_found():
    with patch("pathlib.Path.is_file", return_value=False), pytest.raises(FileNotFoundError):
        MockPrompt("template.txt")


class RealBundledPrompt(PromptBase):
    """Loads a real bundled template from the repository."""

    def get_prompt(self) -> str:
        return self.template

    def get_script_dir(self) -> Path:
        return Path(__file__).resolve().parents[2] / "prompts"


@pytest.fixture
def no_override_dir():
    with patch.object(config, "PROMPT_OVERRIDES_DIR", None):
        yield


@pytest.fixture
def override_dir(tmp_path):
    with patch.object(config, "PROMPT_OVERRIDES_DIR", str(tmp_path)):
        yield tmp_path


def test_bundled_prompt_loads_when_no_override_set(no_override_dir):
    prompt = RealBundledPrompt("routing_instruction_template.txt")
    assert "intelligent orchestrator" in prompt.get_prompt()
    assert "routing_instruction_template" not in prompt.get_prompt()


def test_override_replaces_bundled_template(override_dir):
    (override_dir / "prompts").mkdir()
    (override_dir / "prompts" / "routing_instruction_template.txt").write_text(
        "OVERRIDDEN ROUTING", encoding="utf-8"
    )
    prompt = RealBundledPrompt("routing_instruction_template.txt")
    assert prompt.get_prompt() == "OVERRIDDEN ROUTING"
    assert prompt.template_path == (override_dir / "prompts" / "routing_instruction_template.txt").resolve()


def test_missing_override_falls_back_to_bundled(override_dir):
    # The override directory exists but holds no file for this template.
    prompt = RealBundledPrompt("routing_instruction_template.txt")
    assert "intelligent orchestrator" in prompt.get_prompt()


def test_missing_override_dir_fails_fast(override_dir):
    with patch.object(config, "PROMPT_OVERRIDES_DIR", str(override_dir / "does-not-exist")):
        with pytest.raises(NotADirectoryError, match="PROMPT_OVERRIDES_DIR"):
            RealBundledPrompt("routing_instruction_template.txt")


def test_override_with_differing_placeholders_fails_fast(override_dir):
    class IncidentPrompt(PromptBase):
        def get_prompt(self) -> str:
            return self.template

        def get_script_dir(self) -> Path:
            return Path(__file__).resolve().parents[2] / "agents" / "incident_creation"

    (override_dir / "agents" / "incident_creation").mkdir(parents=True)
    override_file = override_dir / "agents" / "incident_creation" / "prompt_template.txt"
    # Bundled template has {PRIORITY_VALUES} and {TERMINAL_STATUSES}; drop one.
    override_file.write_text("Custom incident prompt with only {PRIORITY_VALUES}", encoding="utf-8")
    with pytest.raises(ValueError, match="missing: \\['TERMINAL_STATUSES'\\]"):
        IncidentPrompt("prompt_template.txt")


def test_override_with_same_placeholders_loads(override_dir):
    class IncidentPrompt(PromptBase):
        def get_prompt(self) -> str:
            return self.template

        def get_script_dir(self) -> Path:
            return Path(__file__).resolve().parents[2] / "agents" / "incident_creation"

    (override_dir / "agents" / "incident_creation").mkdir(parents=True)
    override_file = override_dir / "agents" / "incident_creation" / "prompt_template.txt"
    override_file.write_text(
        "Custom incident prompt {PRIORITY_VALUES} and {TERMINAL_STATUSES}", encoding="utf-8"
    )
    prompt = IncidentPrompt("prompt_template.txt")
    assert prompt.get_prompt() == "Custom incident prompt {PRIORITY_VALUES} and {TERMINAL_STATUSES}"
