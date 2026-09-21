# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""A/B comparison of this smoke run's outputs against a committed baseline.

The rest of the suite proves the flows work; this checks whether a change to the model, its
settings or the agents' prompts made what they produce better or worse. It reuses the same
session-wide webhook run - it costs no extra flow, only the judge's own calls - and compares
the run against the snapshot in ``baselines/``, structurally and on judged quality. A metric
regression or a much worse judged dimension fails; a somewhat worse one only warns.

Capture a baseline (once per configuration you want to compare against)::

    SMOKE_WRITE_BASELINE=1 SMOKE_BASELINE_NAME=gemini uv run pytest tests/smoke -m smoke

Compare a later run against it::

    SMOKE_BASELINE_NAME=gemini uv run pytest tests/smoke -m smoke

Environment variables: ``SMOKE_BASELINE_NAME`` (which baseline to use, default ``default``),
``SMOKE_WRITE_BASELINE`` (capture instead of compare), ``SMOKE_RUN_LABEL`` (what to call this
run in the report) and ``SMOKE_JUDGE_MODEL`` (see ``judge.py``). To skip the comparison
entirely - e.g. while the outputs are expected to change - deselect it with ``-m "smoke and
not ab"``.
"""

import os
import warnings
from pathlib import Path

import httpx
import pytest

import config
from tests.smoke import judge
from tests.smoke.ab_report import AbResult, render_html
from tests.smoke.artifacts import (
    METRIC_TOLERANCE,
    RunSnapshot,
    collect_snapshot,
    compute_metrics,
    find_metric_regressions,
    load_snapshot,
    save_snapshot,
)

pytestmark = [pytest.mark.smoke, pytest.mark.ab]

BASELINE_NAME = os.environ.get("SMOKE_BASELINE_NAME", "default")
BASELINE_PATH = Path(__file__).parent / "baselines" / f"{BASELINE_NAME}.json"
WRITE_BASELINE = os.environ.get("SMOKE_WRITE_BASELINE", "").lower() in ("true", "1", "t")
# What this run is called in the report. The default is the model docker-compose.smoke.yml configures
# for the stack; name the run explicitly when the two differ.
RUN_LABEL = os.environ.get("SMOKE_RUN_LABEL", "google-gla:gemini-3.8-flash")
REPORT_PATH = Path(config.LOG_DIR) / "smoke_ab_report.html"
CAPTURE_HINT = f"SMOKE_WRITE_BASELINE=1 SMOKE_BASELINE_NAME={BASELINE_NAME} uv run pytest tests/smoke -m smoke"


@pytest.fixture(scope="session")
def candidate_snapshot(webhook_responses: dict[str, httpx.Response], http_client: httpx.Client) -> RunSnapshot:
    """What this run produced, read back once all four flows have completed."""
    return collect_snapshot(http_client, RUN_LABEL)


@pytest.fixture(scope="session")
def baseline_snapshot() -> RunSnapshot:
    if WRITE_BASELINE:
        pytest.skip("Capturing a baseline, so there is nothing to compare this run against.")
    if not BASELINE_PATH.exists():
        pytest.skip(f"No baseline at {BASELINE_PATH}. Capture one with: {CAPTURE_HINT}")
    return load_snapshot(BASELINE_PATH)


@pytest.fixture(scope="session")
def ab_result(baseline_snapshot: RunSnapshot, candidate_snapshot: RunSnapshot, judge_google_api_key: None) -> AbResult:
    """Compare the run against the baseline once: the judging costs real model calls."""
    baseline_metrics = compute_metrics(baseline_snapshot)
    candidate_metrics = compute_metrics(candidate_snapshot)
    result = AbResult(
        baseline_metrics=baseline_metrics,
        candidate_metrics=candidate_metrics,
        metric_regressions=find_metric_regressions(baseline_metrics, candidate_metrics),
        comparisons=judge.compare(baseline_snapshot, candidate_snapshot),
    )
    _write_report(baseline_snapshot, candidate_snapshot, result)
    return result


def test_baseline_snapshot_written(candidate_snapshot: RunSnapshot) -> None:
    """With SMOKE_WRITE_BASELINE set, this run becomes the baseline later runs are compared against."""
    if not WRITE_BASELINE:
        pytest.skip(f"Not capturing a baseline; refresh {BASELINE_PATH.name} with: {CAPTURE_HINT}")
    assert candidate_snapshot.test_cases and candidate_snapshot.review_comments and candidate_snapshot.bugs, (
        f"This run produced no outputs on some dimension, so it cannot serve as a baseline: {candidate_snapshot}"
    )
    save_snapshot(BASELINE_PATH, candidate_snapshot)


def test_output_metrics_did_not_regress(ab_result: AbResult) -> None:
    """No structural metric may fall below its baseline value: a run must not produce less."""
    assert not ab_result.metric_regressions, (
        f"This run produced less than the '{BASELINE_NAME}' baseline, beyond the "
        f"{METRIC_TOLERANCE:.0%} tolerance:\n"
        + "\n".join(f"  - {regression}" for regression in ab_result.metric_regressions)
        + f"\nFull report: {REPORT_PATH}"
    )


def test_judged_output_quality_did_not_regress(ab_result: AbResult) -> None:
    """No dimension may be judged much worse than the baseline in both orders; merely worse only warns."""
    degraded = [comparison for comparison in ab_result.comparisons if comparison.degraded]
    if degraded:
        warnings.warn(_judged_findings("somewhat worse", degraded), stacklevel=1)
    regressed = [comparison for comparison in ab_result.comparisons if comparison.regressed]
    assert not regressed, _judged_findings("much worse", regressed)


def _judged_findings(severity: str, comparisons: list[judge.Comparison]) -> str:
    return (
        f"The judge found this run {severity} than the '{BASELINE_NAME}' baseline on:\n"
        + "\n".join(
            f"  - {comparison}\n" + "\n".join(f"    {line}" for line in _justification(comparison))
            for comparison in comparisons
        )
        + f"\nFull report: {REPORT_PATH}"
    )


def _justification(comparison: judge.Comparison) -> list[str]:
    """The judge's evidence for each order's verdict, so a regression can be analysed from the output alone."""
    return [
        f"Candidate as Output B, judged {comparison.forward}: {comparison.forward_rationale}",
        f"Candidate as Output A, judged {comparison.swapped}: {comparison.swapped_rationale}",
    ]


def _write_report(baseline: RunSnapshot, candidate: RunSnapshot, result: AbResult) -> None:
    """Write the whole comparison out, so a verdict can be read without re-running the suite."""
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(render_html(BASELINE_NAME, baseline, candidate, result), encoding="utf-8")
