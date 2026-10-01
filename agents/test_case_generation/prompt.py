# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

from pathlib import Path

from agents.test_case_review.prompt import TestStepQualityCriteriaFragment
from common.prompt_base import PromptBase

PROMPTS_ROOT = "system_prompts"


def _get_prompts_root() -> Path:
    return Path(__file__).resolve().parent.joinpath(PROMPTS_ROOT)


class AcExtractionPrompt(PromptBase):
    def get_script_dir(self) -> Path:
        return _get_prompts_root()

    def __init__(self, template_file_name: str = "ac_extraction_prompt.md"):
        super().__init__(template_file_name)

    def get_prompt(self) -> str:
        return self.template


class StepsGenerationPrompt(PromptBase):
    def get_script_dir(self) -> Path:
        return _get_prompts_root()

    def __init__(self, template_file_name: str = "steps_generation_prompt.md"):
        super().__init__(template_file_name)

    def get_prompt(self) -> str:
        return self.template.format(test_step_quality_criteria=TestStepQualityCriteriaFragment().get_prompt())


class TestCaseFixerPrompt(PromptBase):
    __test__ = False

    def get_script_dir(self) -> Path:
        return _get_prompts_root()

    def __init__(self, template_file_name: str = "test_case_fixer_prompt.md") -> None:
        super().__init__(template_file_name)

    def get_prompt(self) -> str:
        return self.template.format(test_step_quality_criteria=TestStepQualityCriteriaFragment().get_prompt())


class TestCaseCreationPrompt(PromptBase):
    def get_script_dir(self) -> Path:
        return _get_prompts_root()

    def __init__(self, template_file_name: str = "test_case_creation_prompt.md"):
        super().__init__(template_file_name)

    def get_prompt(self) -> str:
        return self.template
