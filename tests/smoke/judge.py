# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Blinded pairwise judging of two smoke runs' outputs by an LLM judge.

The metrics in ``artifacts.py`` see how much a run produced; this sees how good it is. Both
runs' outputs for a dimension are handed to a judge model as anonymous "Output A" and
"Output B" and judged against the requirement they were produced from on a five-level verdict
scale, with a rationale naming the concrete content behind the label. The same pair is judged
a second time with the two swapped - the judge's position bias would otherwise be charged to
whichever run happens to come second - and only a verdict both orders agree on counts; orders
that disagree are judge noise, reported as such and never a regression.
"""

import os
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from common import utils
from common.model_factory import build_model
from common.token_usage import TokenUsage
from tests.smoke.artifacts import DIMENSIONS, RunSnapshot, execution_context, render_for_judge, story_context

# The judge runs the same model the smoke stack is configured with in docker-compose.smoke.yml.
# Overridable for a stack that cannot reach Gemini.
JUDGE_MODEL_NAME = os.environ.get("SMOKE_JUDGE_MODEL", "google-gla:gemini-3.8-flash")

logger = utils.get_logger("smoke_judge")

# The label the judge picks for a blinded pair, on the five-level scale Arena-Hard uses.
Label = Literal["A>>B", "A>B", "A=B", "B>A", "B>>A"]
# The same label read from the candidate's side, once its slot is known.
Verdict = Literal["much_better", "better", "same", "worse", "much_worse"]
# What both orders say together: a verdict they agree on, or "inconsistent" when they do not.
Outcome = Literal["much_better", "better", "same", "worse", "much_worse", "inconsistent"]

_WORSE: frozenset[Verdict] = frozenset({"worse", "much_worse"})
_BETTER: frozenset[Verdict] = frozenset({"much_better", "better"})
# What each label means for the output in slot A; the output in slot B gets the mirror image.
_FOR_SLOT_A: dict[Label, Verdict] = {
    "A>>B": "much_better",
    "A>B": "better",
    "A=B": "same",
    "B>A": "worse",
    "B>>A": "much_worse",
}
_MIRROR: dict[Verdict, Verdict] = {
    "much_better": "much_worse",
    "better": "worse",
    "same": "same",
    "worse": "better",
    "much_worse": "much_better",
}

JUDGE_INSTRUCTIONS = (
    "You are an impartial QA expert comparing the outputs of two systems that were given the same "
    "requirement. Judge only their content against the stated criteria: the outputs are anonymised, their "
    "order carries no meaning, and length is worth nothing on its own. Write your rationale first, then "
    "pick exactly one label:\n"
    "  A>>B - A is clearly superior: B misses acceptance criteria, contains errors or is unfit for its purpose.\n"
    "  A>B - A is somewhat better: B has minor gaps but is still fit for its purpose.\n"
    "  A=B - equivalent: the differences are stylistic or trade off evenly.\n"
    "  B>A - B is somewhat better: A has minor gaps but is still fit for its purpose.\n"
    "  B>>A - B is clearly superior: A misses acceptance criteria, contains errors or is unfit for its purpose.\n"
    "The rationale must ground the label in specific evidence: name the concrete findings, cases, steps or "
    "details that one output has and the other lacks or gets wrong. Do not pick a label the rationale does "
    "not support."
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


class _Judgement(BaseModel):
    """What the judge returns for one blinded pair: the reasoning first, then the label it supports."""

    rationale: str = Field(description="The specific differences in content that justify the label.")
    label: Label


@dataclass(slots=True)
class Comparison:
    """How the candidate was judged against the baseline on one dimension, in both orders."""

    dimension: str
    forward: Verdict
    """The verdict with the candidate shown as Output B."""
    swapped: Verdict
    """The verdict with the candidate shown as Output A."""
    forward_rationale: str
    swapped_rationale: str

    @property
    def outcome(self) -> Outcome:
        """The verdict both orders agree on, at the milder of their two magnitudes."""
        if self.forward == self.swapped:
            return self.forward
        if self.forward in _WORSE and self.swapped in _WORSE:
            return "worse"
        if self.forward in _BETTER and self.swapped in _BETTER:
            return "better"
        return "inconsistent"

    @property
    def regressed(self) -> bool:
        return self.outcome in _WORSE

    def __str__(self) -> str:
        return (
            f"{self.dimension}: {self.outcome} (candidate judged {self.forward} as Output B, "
            f"{self.swapped} as Output A)"
        )


def verdict_for_candidate(label: Label, candidate_slot: Literal["A", "B"]) -> Verdict:
    """The judge's blinded label read from the candidate's side."""
    for_slot_a = _FOR_SLOT_A[label]
    return for_slot_a if candidate_slot == "A" else _MIRROR[for_slot_a]


def compare(baseline: RunSnapshot, candidate: RunSnapshot) -> list[Comparison]:
    """Judge the candidate against the baseline on every dimension either of them produced something for."""
    agent = Agent(build_model(JUDGE_MODEL_NAME), output_type=_Judgement, instructions=JUDGE_INSTRUCTIONS)
    story = story_context(baseline)
    # The bug report is written from the failed execution, so its judge must see that too - the
    # test case key, its test data and the failure are facts of the run, not inventions.
    contexts = dict.fromkeys(DIMENSIONS, story) | {"incident_report": f"{story}\n\n{execution_context(baseline)}"}
    comparisons: list[Comparison] = []
    for dimension in DIMENSIONS:
        baseline_output = render_for_judge(dimension, baseline)
        candidate_output = render_for_judge(dimension, candidate)
        if not baseline_output.strip() and not candidate_output.strip():
            continue
        forward = _judge(agent, dimension, contexts[dimension], baseline_output, candidate_output)
        swapped = _judge(agent, dimension, contexts[dimension], candidate_output, baseline_output)
        comparisons.append(
            Comparison(
                dimension=dimension,
                forward=verdict_for_candidate(forward.label, "B"),
                swapped=verdict_for_candidate(swapped.label, "A"),
                forward_rationale=forward.rationale,
                swapped_rationale=swapped.rationale,
            )
        )
    return comparisons


def _judge(agent: Agent, dimension: str, requirement: str, output_a: str, output_b: str) -> _Judgement:
    prompt = (
        f"Requirement under test:\n{requirement}\n\n"
        f"Both outputs are {CRITERIA[dimension]}\n\n"
        f"--- OUTPUT A ---\n{output_a or '(nothing was produced)'}\n\n"
        f"--- OUTPUT B ---\n{output_b or '(nothing was produced)'}"
    )
    result = agent.run_sync(prompt)
    logger.info(
        "Judge [%s]: %s - %s",
        dimension,
        result.output.label,
        TokenUsage.from_run_usage(result.usage(), JUDGE_MODEL_NAME).summary_line(),
    )
    return result.output
