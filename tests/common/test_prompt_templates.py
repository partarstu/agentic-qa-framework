# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Every bundled prompt template loads and renders as Markdown."""

import re

import pytest

from agents.incident_creation import prompt as incident_prompts
from agents.requirements_review import prompt as requirements_prompts
from agents.test_case_classification import prompt as classification_prompts
from agents.test_case_generation import prompt as generation_prompts
from agents.test_case_review import prompt as review_prompts
from common import models
from orchestrator.prompt import OrchestratorPrompt

# A placeholder or an escaped brace left in a rendered prompt means a template was not formatted correctly.
_UNRENDERED = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}|\{\{|\}\}")

_PROMPTS = {
    "incident-creation": incident_prompts.IncidentCreationPrompt,
    "incident-duplicate-detection": incident_prompts.DuplicateDetectionPrompt,
    "requirements-review": requirements_prompts.RequirementsReviewSystemPrompt,
    "requirements-review-with-attachments": requirements_prompts.RequirementsReviewWithAttachmentsPrompt,
    "requirements-review-retrieval": requirements_prompts.RequirementsReviewRetrievalInstruction,
    "test-case-classification": classification_prompts.TestCaseClassificationSystemPrompt,
    "test-case-generation": generation_prompts.TestCaseGenerationSystemPrompt,
    "ac-extraction": generation_prompts.AcExtractionPrompt,
    "steps-generation": generation_prompts.StepsGenerationPrompt,
    "test-case-creation": generation_prompts.TestCaseCreationPrompt,
    "test-case-review": review_prompts.TestCaseReviewSystemPrompt,
    "test-case-review-with-attachments": review_prompts.TestCaseReviewWithAttachmentsPrompt,
    "test-case-duplicate-judge": review_prompts.TestCaseDuplicateJudgePrompt,
}

_ORCHESTRATOR_TEMPLATES = [
    "routing_instruction_template.md",
    "multi_routing_instruction_template.md",
    "results_extractor_instruction_template.md",
]


@pytest.mark.parametrize("prompt_class", list(_PROMPTS.values()), ids=list(_PROMPTS))
def test_agent_prompt_renders_as_markdown_without_placeholders(prompt_class):
    prompt = prompt_class().get_prompt()

    assert prompt.startswith("#")
    assert not _UNRENDERED.search(prompt), _UNRENDERED.search(prompt)


@pytest.mark.parametrize("template_file_name", _ORCHESTRATOR_TEMPLATES)
def test_orchestrator_prompt_is_markdown(template_file_name):
    prompt = OrchestratorPrompt(template_file_name).get_prompt()

    assert prompt.startswith("#")
    assert not _UNRENDERED.search(prompt)


def test_the_grounding_suffix_is_markdown():
    assert requirements_prompts.RequirementsReviewWithAttachmentsPrompt.grounding_suffix().startswith("#")


def test_classification_prompt_lists_every_test_type_with_its_label():
    prompt = classification_prompts.TestCaseClassificationSystemPrompt().get_prompt()

    for test_type in models.TestCaseType:
        assert f"- `{test_type.value}`: label `{test_type.label}`" in prompt
    assert "load_stress" not in prompt
