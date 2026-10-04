# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""A/B comparison of every LLM-driven workflow's outputs on a real model against its committed baseline.

Every run costs real model calls, so select only the workflows a change touches with ``-k``; the README's *A/B tests
against a baseline* describes how to capture and compare baselines.
"""

import os
import warnings
from pathlib import Path

import httpx
import pytest

import config
from tests.ab import judge
from tests.ab.ab_report import AbResult, render_html
from tests.ab.artifacts import (
    METRIC_TOLERANCE,
    WORKFLOWS,
    RunSnapshot,
    Workflow,
    collect_snapshot,
    compute_metrics,
    find_metric_regressions,
    load_snapshot,
    render_for_judge,
    save_snapshot,
)
from tests.smoke.conftest import WEBHOOKS, post_webhook

pytestmark = pytest.mark.ab

BASELINE_NAME = os.environ.get("AB_BASELINE_NAME", "default")
BASELINES_DIR = Path(__file__).parent / "baselines" / BASELINE_NAME
WRITE_BASELINE = os.environ.get("AB_WRITE_BASELINE", "").lower() in ("true", "1", "t")
RUN_LABEL = os.environ.get("AB_RUN_LABEL")
CAPTURE_HINT = f"AB_WRITE_BASELINE=1 AB_BASELINE_NAME={BASELINE_NAME} uv run pytest tests/ab -m ab -k <workflow>"


def _baseline_path(workflow: Workflow) -> Path:
    return BASELINES_DIR / f"{workflow.name}.json"


def _report_path(workflow: Workflow) -> Path:
    return Path(config.LOG_DIR) / f"ab_report_{workflow.name}.html"


@pytest.fixture(scope="session", params=WORKFLOWS, ids=lambda workflow: workflow.name)
def workflow(request: pytest.FixtureRequest) -> Workflow:
    return request.param


@pytest.fixture(scope="session")
def candidate_snapshot(
    workflow: Workflow,
    stack_model: str,
    synced_knowledge_bases: None,
    judge_google_api_key: None,
    webhook_headers: dict[str, str],
    http_client: httpx.Client,
) -> RunSnapshot:
    """What one run of the workflow produced; the run costs real model calls, so it happens once."""
    path, payload = WEBHOOKS[workflow.webhook]
    response = post_webhook(path, webhook_headers, payload)
    if response.is_error:
        pytest.fail(f"The {workflow.name} workflow failed: {response.status_code} {response.text}")
    return collect_snapshot(http_client, RUN_LABEL or stack_model, workflow)


@pytest.fixture(scope="session")
def baseline_snapshot(workflow: Workflow) -> RunSnapshot:
    if WRITE_BASELINE:
        pytest.skip("Capturing a baseline, so there is nothing to compare this run against.")
    if not _baseline_path(workflow).exists():
        pytest.skip(f"No baseline at {_baseline_path(workflow)}. Capture one with: {CAPTURE_HINT}")
    return load_snapshot(_baseline_path(workflow))


@pytest.fixture(scope="session")
def ab_result(workflow: Workflow, baseline_snapshot: RunSnapshot, candidate_snapshot: RunSnapshot) -> AbResult:
    """Compare the run against the baseline once: the judging costs real model calls."""
    baseline_metrics = compute_metrics(baseline_snapshot, workflow.dimensions)
    candidate_metrics = compute_metrics(candidate_snapshot, workflow.dimensions)
    result = AbResult(
        baseline_metrics=baseline_metrics,
        candidate_metrics=candidate_metrics,
        metric_regressions=find_metric_regressions(baseline_metrics, candidate_metrics),
        comparisons=judge.compare(baseline_snapshot, candidate_snapshot, workflow.dimensions),
    )
    _write_report(workflow, baseline_snapshot, candidate_snapshot, result)
    return result


def test_baseline_snapshot_written(workflow: Workflow, request: pytest.FixtureRequest) -> None:
    """With AB_WRITE_BASELINE set, this run becomes the baseline later runs of the workflow are compared against."""
    if not WRITE_BASELINE:
        pytest.skip(f"Not capturing a baseline; refresh {_baseline_path(workflow).name} with: {CAPTURE_HINT}")
    # Requested only now, so a run that captures nothing does not pay for the workflow here.
    candidate_snapshot: RunSnapshot = request.getfixturevalue("candidate_snapshot")
    empty = [d for d in workflow.dimensions if not render_for_judge(d, candidate_snapshot).strip()]
    assert not empty, f"This run produced no outputs on {empty}, so it cannot serve as a baseline: {candidate_snapshot}"
    save_snapshot(_baseline_path(workflow), candidate_snapshot)


def test_output_metrics_did_not_regress(workflow: Workflow, ab_result: AbResult) -> None:
    """No structural metric may fall below its baseline value: a run must not produce less."""
    assert not ab_result.metric_regressions, (
        f"This {workflow.name} run produced less than the '{BASELINE_NAME}' baseline, beyond the "
        f"{METRIC_TOLERANCE:.0%} tolerance:\n"
        + "\n".join(f"  - {regression}" for regression in ab_result.metric_regressions)
        + f"\nFull report: {_report_path(workflow)}"
    )


def test_judged_output_quality_did_not_regress(workflow: Workflow, ab_result: AbResult) -> None:
    """No dimension may be judged much worse than the baseline in both orders; merely worse only warns."""
    degraded = [comparison for comparison in ab_result.comparisons if comparison.degraded]
    if degraded:
        warnings.warn(_judged_findings(workflow, "somewhat worse", degraded), stacklevel=1)
    regressed = [comparison for comparison in ab_result.comparisons if comparison.regressed]
    assert not regressed, _judged_findings(workflow, "much worse", regressed)


def _judged_findings(workflow: Workflow, severity: str, comparisons: list[judge.Comparison]) -> str:
    return (
        f"The judge found this {workflow.name} run {severity} than the '{BASELINE_NAME}' baseline on:\n"
        + "\n".join(
            f"  - {comparison}\n" + "\n".join(f"    {line}" for line in _justification(comparison))
            for comparison in comparisons
        )
        + f"\nFull report: {_report_path(workflow)}"
    )


def _justification(comparison: judge.Comparison) -> list[str]:
    """The judge's evidence for each order's verdict, so a regression can be analysed from the output alone."""
    return [
        f"Candidate as Output B, judged {comparison.forward}: {comparison.forward_rationale}",
        f"Candidate as Output A, judged {comparison.swapped}: {comparison.swapped_rationale}",
    ]


def _write_report(workflow: Workflow, baseline: RunSnapshot, candidate: RunSnapshot, result: AbResult) -> None:
    """Write the whole comparison out, so a verdict can be read without re-running the workflow."""
    report_path = _report_path(workflow)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_html(workflow.name, BASELINE_NAME, baseline, candidate, result), encoding="utf-8")
