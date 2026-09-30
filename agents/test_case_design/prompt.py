# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

from pathlib import Path

from common import utils
from common.prompt_base import PromptBase

logger = utils.get_logger("test_case_design_agent")


class TestCaseDesignSystemPrompt(PromptBase):
    __test__ = False

    def get_script_dir(self) -> Path:
        return Path(__file__).resolve().parent / "system_prompts"

    def __init__(self, template_file_name: str = "main_prompt_template.md") -> None:
        super().__init__(template_file_name)

    def get_prompt(self) -> str:
        logger.info("Generating test case design system prompt")
        return self.template
