# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path
from common.prompt_base import PromptBase
from common import utils

logger = utils.get_logger("test_case_review_agent")


class TestCaseReviewSystemPrompt(PromptBase):
    def get_script_dir(self) -> Path:
        return Path(__file__).resolve().parent

    def __init__(self, template_file_name: str = "prompt_template.txt"):
        super().__init__(template_file_name)

    def get_prompt(self) -> str:
        logger.info("Generating test case review system prompt")
        return self.template