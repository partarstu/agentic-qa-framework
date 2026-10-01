# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

from pathlib import Path

from common import utils
from common.prompt_base import PromptBase

logger = utils.get_logger("test_case_review_agent")
PROMPTS_ROOT = "system_prompts"


def _get_prompts_root() -> Path:
    return Path(__file__).resolve().parent.joinpath(PROMPTS_ROOT)


class TestCaseReviewWithAttachmentsPrompt(PromptBase):
    """
    Prompt for the sub-agent that reviews test cases with binary attachments.
    """

    def get_script_dir(self) -> Path:
        return _get_prompts_root()

    def __init__(self, template_file_name: str = "review_with_attachments_prompt.md"):
        super().__init__(template_file_name)

    def get_prompt(self) -> str:
        """Returns the formatted prompt as a string."""
        logger.info(
            "Generating system prompt for sub-agent which performs test case review with all attachments included"
        )
        return self.template.format(
            severity_rubric=SeverityRubricFragment().get_prompt(),
            test_step_quality_criteria=TestStepQualityCriteriaFragment().get_prompt(),
        )


class TestSuiteReviewPrompt(PromptBase):
    """Prompt for the sub-agent which reviews the whole set of test cases for coverage gaps and duplicates."""

    __test__ = False

    def get_script_dir(self) -> Path:
        return _get_prompts_root()

    def __init__(self, template_file_name: str = "test_suite_review_prompt.md") -> None:
        super().__init__(template_file_name)

    def get_prompt(self) -> str:
        logger.info("Generating system prompt for the test suite reviewer sub-agent")
        return self.template.format(severity_rubric=SeverityRubricFragment().get_prompt())


class SeverityRubricFragment(PromptBase):
    """The findings and severity rules shared by the per-test-case and the whole-set review prompts."""

    def get_script_dir(self) -> Path:
        return _get_prompts_root()

    def __init__(self, template_file_name: str = "severity_rubric.md") -> None:
        super().__init__(template_file_name)

    def get_prompt(self) -> str:
        return self.template


class TestStepQualityCriteriaFragment(PromptBase):
    """The test step rules shared by the steps generation, the per-test-case review and the fixer prompts."""

    __test__ = False

    def get_script_dir(self) -> Path:
        return _get_prompts_root()

    def __init__(self, template_file_name: str = "test_step_quality_criteria.md") -> None:
        super().__init__(template_file_name)

    def get_prompt(self) -> str:
        return self.template


class TestCaseDuplicateJudgePrompt(PromptBase):
    """Prompt for the sub-agent which judges the coverage overlap of duplicate candidates."""

    __test__ = False

    def get_script_dir(self) -> Path:
        return _get_prompts_root()

    def __init__(self, template_file_name: str = "test_case_duplicate_judge_prompt.md"):
        """Initializes the duplicate judge prompt from its template file."""
        super().__init__(template_file_name)

    def get_prompt(self) -> str:
        """Returns the prompt as a string."""
        logger.info("Generating system prompt for the test case duplicate judge sub-agent")
        return self.template
