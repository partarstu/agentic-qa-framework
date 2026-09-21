# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Comparable snapshots of what a smoke run actually produced.

The assertions in ``test_smoke.py`` prove that a flow *ran*; they say nothing about the
quality of what the model wrote, so a model or prompt change can degrade every output while
the whole suite stays green. A snapshot captures those outputs - the requirements review,
the generated test cases, their review comments and the bug created for a failed execution -
so one run can be compared against a committed baseline, structurally here and on judged
quality in ``judge.py``.
"""

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

import httpx

from tests.smoke.conftest import (
    JIRA_MCP_RECORDED_URL,
    JIRA_MCP_SEEDED_ATTACHMENTS_URL,
    JIRA_MCP_SEEDED_STORY_URL,
    JIRA_REST_RECORDED_URL,
    PROMPT_OVERRIDE_MARKER,
    SEEDED_EXECUTABLE_TC_KEY,
    SEEDED_ISSUE_KEY,
    ZEPHYR_RECORDED_URL,
)
from tests.smoke.recordings import wait_for_recorded

ZEPHYR_URL = ZEPHYR_RECORDED_URL.removesuffix("/__recorded")

# The output dimensions a run is compared on, each produced by a different agent.
DIMENSIONS = ("requirements_review", "test_case_generation", "test_case_review", "incident_report")

# How far below the baseline a metric may fall before it counts as a regression. Every
# artifact here is written by a non-deterministic model, so two runs of the very same
# configuration differ by a case or a few sentences; only a drop beyond that is a signal.
METRIC_TOLERANCE = 0.25


@dataclass(slots=True)
class RunSnapshot:
    """Everything an A/B comparison needs from one smoke run."""

    label: str
    captured_at: str
    story: dict
    attachments: dict[str, str]
    review_comments: list[str]
    test_cases: list[dict]
    bugs: list[dict]
    execution: dict
    """The failed test execution the bug was created from: the executed test case and its failure."""


@dataclass(slots=True)
class MetricRegression:
    """A metric of the candidate run that fell below its baseline value."""

    dimension: str
    metric: str
    baseline: float
    candidate: float

    def __str__(self) -> str:
        return (
            f"{self.dimension}.{self.metric}: {self.candidate:.2f} vs baseline {self.baseline:.2f} "
            f"(below the {1 - METRIC_TOLERANCE:.0%} floor)"
        )


def collect_snapshot(http_client: httpx.Client, label: str) -> RunSnapshot:
    """Read one finished run's outputs back from the recording mocks.

    Waits for the outputs of the slowest flows the same way the assertions do, so the snapshot
    cannot capture a half-written run when it is collected right after the webhooks return.
    """
    jira_mcp = wait_for_recorded(
        http_client, JIRA_MCP_RECORDED_URL, lambda d: bool(d.get("comments")) and bool(d.get("created_issues"))
    )
    zephyr = wait_for_recorded(
        http_client,
        ZEPHYR_RECORDED_URL,
        lambda d: bool(d.get("test_cases")) and all(tc.get("review_comments", "").strip() for tc in d["test_cases"]),
    )
    jira_rest = http_client.get(JIRA_REST_RECORDED_URL).json()
    return RunSnapshot(
        label=label,
        captured_at=datetime.now(UTC).isoformat(timespec="seconds"),
        story=http_client.get(JIRA_MCP_SEEDED_STORY_URL).json(),
        attachments=http_client.get(JIRA_MCP_SEEDED_ATTACHMENTS_URL).json(),
        review_comments=_review_comments(jira_rest, jira_mcp),
        test_cases=[_normalized_test_case(tc) for tc in zephyr.get("test_cases", [])],
        bugs=[
            {"summary": issue.get("summary", ""), "description": issue.get("description", "")}
            for issue in jira_mcp.get("created_issues", [])
            if issue.get("issue_type") == "Bug"
        ],
        execution=_failed_execution(http_client, zephyr),
    )


def _failed_execution(http_client: httpx.Client, zephyr: dict) -> dict:
    """The seeded test case /execute-tests ran, with the failure the executor reported for it."""
    test_case = http_client.get(f"{ZEPHYR_URL}/testcases/{SEEDED_EXECUTABLE_TC_KEY}").json()
    failures = [
        step.get("actualResult", "")
        for execution in zephyr.get("test_executions", [])
        if execution.get("testCaseKey") == SEEDED_EXECUTABLE_TC_KEY and execution.get("statusName") == "Fail"
        for step in execution.get("testScriptResults", [])
    ]
    return {**_normalized_test_case(test_case), "failure": next(iter(failures), "")}


def save_snapshot(path: Path, snapshot: RunSnapshot) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(snapshot), indent=2, ensure_ascii=False), encoding="utf-8")


def load_snapshot(path: Path) -> RunSnapshot:
    return RunSnapshot(**json.loads(path.read_text(encoding="utf-8")))


def compute_metrics(snapshot: RunSnapshot) -> dict[str, dict[str, float]]:
    """The structural side of a run's outputs, per dimension.

    Every metric is "higher is better", so a candidate value below its baseline is a regression;
    together they catch the degradations a quality judge cannot see, such as a run that produced
    three test cases where the baseline produced eight.
    """
    cases = snapshot.test_cases
    steps = [step for case in cases for step in case["steps"]]
    reviewed = [case for case in cases if case["review_comments"].strip()]
    return {
        "requirements_review": {
            "comments": float(len(snapshot.review_comments)),
            "avg_comment_length": _mean([len(comment) for comment in snapshot.review_comments]),
        },
        "test_case_generation": {
            "test_cases": float(len(cases)),
            "avg_steps_per_case": _mean([len(case["steps"]) for case in cases]),
            "cases_with_objective": _ratio([case for case in cases if case["objective"].strip()], cases),
            "cases_with_labels": _ratio([case for case in cases if case["labels"]], cases),
            "steps_with_expected_result": _ratio([s for s in steps if s["expected_result"].strip()], steps),
        },
        "test_case_review": {
            "reviewed_cases": _ratio(reviewed, cases),
            "avg_review_comment_length": _mean([len(case["review_comments"]) for case in reviewed]),
        },
        "incident_report": {
            "bugs": float(len(snapshot.bugs)),
            "avg_bug_description_length": _mean([len(bug["description"]) for bug in snapshot.bugs]),
        },
    }


def find_metric_regressions(
    baseline_metrics: dict[str, dict[str, float]], candidate_metrics: dict[str, dict[str, float]]
) -> list[MetricRegression]:
    """Every candidate metric that fell more than the tolerance below its baseline value."""
    return [
        MetricRegression(dimension, metric, baseline_value, candidate_metrics.get(dimension, {}).get(metric, 0.0))
        for dimension, metrics in baseline_metrics.items()
        for metric, baseline_value in metrics.items()
        if candidate_metrics.get(dimension, {}).get(metric, 0.0) < baseline_value * (1 - METRIC_TOLERANCE)
    ]


def story_context(snapshot: RunSnapshot) -> str:
    """The requirement every output of the run was produced from: the story and the attachments handed over with it.

    The attachments belong here because the agents read them: a review finding grounded in an attachment is
    correct, and a judge that never saw the attachment would take it for an invention.
    """
    fields = snapshot.story.get("fields", {})
    story = f"{snapshot.story.get('key', '')}: {fields.get('summary', '')}\n\n{fields.get('description', '')}".strip()
    attachments = [f"Attachment {name}:\n{text.strip()}" for name, text in snapshot.attachments.items()]
    return "\n\n".join([story, *attachments])


def execution_context(snapshot: RunSnapshot) -> str:
    """The failed execution the bug report was produced from, as the plain text a judge reads."""
    execution = snapshot.execution
    return (
        f"Failed automated test case {execution['key']}:\n{_render_test_case(execution)}\n"
        f"Failure: {execution['failure']}"
    )


def render_for_judge(dimension: str, snapshot: RunSnapshot) -> str:
    """One dimension's outputs as the plain text a judge reads."""
    match dimension:
        case "requirements_review":
            return "\n\n".join(snapshot.review_comments)
        case "test_case_generation":
            return "\n\n".join(_render_test_case(case) for case in snapshot.test_cases)
        case "test_case_review":
            return "\n\n".join(
                f"Test case: {case['name']}\nReview comment: {case['review_comments']}"
                for case in snapshot.test_cases
                if case["review_comments"].strip()
            )
        case "incident_report":
            return "\n\n".join(f"Summary: {bug['summary']}\nDescription: {bug['description']}" for bug in snapshot.bugs)
        case _:
            raise ValueError(f"Unknown dimension: {dimension}")


def _review_comments(jira_rest: dict, jira_mcp: dict) -> list[str]:
    """The non-empty review comments that reached the seeded story, over either Jira transport.

    The prompt-override marker the smoke stack makes the agent append is stripped: it is a fixture of the
    suite, not of the review, and a judge reads it as a stray artifact.
    """
    rest = [c.get("body", "") for c in jira_rest.get("comments", []) if c.get("issue_key") == SEEDED_ISSUE_KEY]
    mcp = [c.get("comment", "") for c in jira_mcp.get("comments", []) if c.get("issue_key") == SEEDED_ISSUE_KEY]
    comments = [text.replace(PROMPT_OVERRIDE_MARKER, "").strip() for text in rest + mcp]
    return [text for text in comments if text]


def _normalized_test_case(test_case: dict) -> dict:
    """A generated test case reduced to the fields a comparison looks at."""
    return {
        "key": test_case.get("key", ""),
        "name": test_case.get("name", ""),
        "objective": test_case.get("objective", ""),
        "precondition": test_case.get("precondition") or "",
        "labels": test_case.get("labels", []),
        "review_comments": test_case.get("review_comments", ""),
        "steps": [
            {
                "description": step.get("description", ""),
                "expected_result": step.get("expectedResult", ""),
                "test_data": step.get("testData", ""),
            }
            for step in test_case.get("steps", [])
        ],
    }


def _render_test_case(case: dict) -> str:
    steps = "\n".join(
        f"  {number}. {step['description']} -> expected: {step['expected_result']}"
        + (f" (test data: {step['test_data']})" if step["test_data"] else "")
        for number, step in enumerate(case["steps"], start=1)
    )
    return (
        f"Name: {case['name']}\n"
        f"Objective: {case['objective']}\n"
        f"Precondition: {case['precondition']}\n"
        f"Labels: {', '.join(case['labels'])}\n"
        f"Steps:\n{steps}"
    )


def _mean(values: list[int]) -> float:
    return float(mean(values)) if values else 0.0


def _ratio(matching: list, total: list) -> float:
    return len(matching) / len(total) if total else 0.0
