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


class TestCaseReviewSystemPrompt(PromptBase):
    """
    Loads a prompt template for instructions, replaces placeholders with actual values,
    and provides the final prompt as a string.
    """

    def get_script_dir(self) -> Path:
        return _get_prompts_root()

    def __init__(self, template_file_name: str = "main_prompt_template.md"):
        super().__init__(template_file_name)

    def get_prompt(self) -> str:
        """Returns the formatted prompt as a string."""
        logger.info("Generating test case review system prompt")
        return self.template


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
