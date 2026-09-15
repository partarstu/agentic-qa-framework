# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Blinded pairwise scoring of two smoke runs' outputs by an LLM judge.

The metrics in ``artifacts.py`` see how much a run produced; this sees how good it is. Both
runs' outputs for a dimension are handed to a judge model as anonymous "Output A" and
"Output B", scored against the requirement they were produced from, and the same pair is
judged a second time with the two swapped - the judge's position bias would otherwise be
charged to whichever run happens to come second.
"""

import os
from dataclasses import dataclass

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from common.model_factory import build_model
from tests.smoke.artifacts import DIMENSIONS, RunSnapshot, render_for_judge, story_context

# The judge is pinned to a model independent of the one under test, so that a candidate is
# never scored by itself. Overridable for a stack that cannot reach Gemini.
JUDGE_MODEL_NAME = os.environ.get("SMOKE_JUDGE_MODEL", "google-gla:gemini-3.7-flash")

# How far below the baseline a candidate may score before it counts as a regression. The
# judge re-scores identical inputs about a point apart, so a smaller gap says nothing.
JUDGE_SCORE_TOLERANCE = 1.0

JUDGE_INSTRUCTIONS = (
    "You are an impartial QA expert comparing the outputs of two systems that were given the same "
    "requirement. Score each output from 1 (unusable) to 10 (excellent) against the stated criteria, "
    "judging only its content: the outputs are anonymised, their order carries no meaning, and length "
    "is worth nothing on its own. Justify both scores in two or three sentences."
)

CRITERIA: dict[str, str] = {
    "requirements_review": (
        "reviews of the requirement above, written for its author. Reward concrete, correct findings - "
        "ambiguities, contradictions, missing or untestable acceptance criteria - that are grounded in what "
        "the requirement actually says. Penalise generic advice, invented facts and vagueness."
    ),
    "test_case_generation": (
        "sets of test cases generated from the requirement above. Reward coverage of its acceptance criteria, "
        "including negative and boundary cases, and steps concrete enough to execute with unambiguous expected "
        "results. Penalise duplicated cases, cases unrelated to the requirement and steps too vague to follow."
    ),
    "test_case_review": (
        "review comments written about generated test cases. Reward specific, actionable findings about the very "
        "case they refer to. Penalise empty praise, generic remarks and comments that ignore the case's content."
    ),
    "incident_report": (
        "bug reports created from a failed automated test of the requirement above. Reward a summary naming the "
        "actual failure and a description someone could reproduce and triage it from. Penalise vagueness and "
        "details the run cannot support."
    ),
}


class _Verdict(BaseModel):
    """The scores a judge returns for one blinded pair of outputs."""

    score_a: int = Field(ge=1, le=10)
    score_b: int = Field(ge=1, le=10)
    rationale: str


@dataclass(slots=True)
class Comparison:
    """How the baseline and the candidate scored on one dimension."""

    dimension: str
    baseline_score: float
    candidate_score: float
    rationale: str

    @property
    def regressed(self) -> bool:
        return self.baseline_score - self.candidate_score > JUDGE_SCORE_TOLERANCE

    def __str__(self) -> str:
        return (
            f"{self.dimension}: candidate {self.candidate_score:.1f} vs baseline {self.baseline_score:.1f} "
            f"(tolerance {JUDGE_SCORE_TOLERANCE:.1f})"
        )


def compare(baseline: RunSnapshot, candidate: RunSnapshot) -> list[Comparison]:
    """Score both runs on every dimension either of them produced something for."""
    agent = Agent(build_model(JUDGE_MODEL_NAME), output_type=_Verdict, instructions=JUDGE_INSTRUCTIONS)
    requirement = story_context(baseline)
    comparisons: list[Comparison] = []
    for dimension in DIMENSIONS:
        baseline_output = render_for_judge(dimension, baseline)
        candidate_output = render_for_judge(dimension, candidate)
        if not baseline_output.strip() and not candidate_output.strip():
            continue
        forward = _score(agent, dimension, requirement, baseline_output, candidate_output)
        reverse = _score(agent, dimension, requirement, candidate_output, baseline_output)
        comparisons.append(
            Comparison(
                dimension=dimension,
                baseline_score=(forward.score_a + reverse.score_b) / 2,
                candidate_score=(forward.score_b + reverse.score_a) / 2,
                rationale=f"{forward.rationale} || (swapped) {reverse.rationale}",
            )
        )
    return comparisons


def _score(agent: Agent, dimension: str, requirement: str, output_a: str, output_b: str) -> _Verdict:
    prompt = (
        f"Requirement under test:\n{requirement}\n\n"
        f"Both outputs are {CRITERIA[dimension]}\n\n"
        f"--- OUTPUT A ---\n{output_a or '(nothing was produced)'}\n\n"
        f"--- OUTPUT B ---\n{output_b or '(nothing was produced)'}"
    )
    return agent.run_sync(prompt).output
