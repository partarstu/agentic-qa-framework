# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for the orchestrator's instruction templates (WS3)."""

import pytest

from orchestrator import prompt as orchestrator_prompt


@pytest.mark.parametrize(
    ("instruction_name", "expected_phrase"),
    [
        ("ROUTING_INSTRUCTION", "justification"),
        ("MULTI_ROUTING_INSTRUCTION", "justification"),
        ("RESULTS_EXTRACTOR_INSTRUCTION", ""),
    ],
)
def test_orchestrator_instruction_template_loads_from_its_bundled_file(
    instruction_name: str, expected_phrase: str
) -> None:
    instruction = getattr(orchestrator_prompt, instruction_name)

    assert instruction.strip()
    assert expected_phrase in instruction.lower()


def test_execution_agent_selection_prompt_states_the_run_is_unattended() -> None:
    """WS15: the execution-agent selection must exclude agents that need a human during the run."""
    instruction = orchestrator_prompt.MULTI_ROUTING_INSTRUCTION.lower()

    assert "fully automated, unattended ci/cd execution" in instruction
    assert "exclude every agent which is supervised, operator-attended or interactive" in instruction
