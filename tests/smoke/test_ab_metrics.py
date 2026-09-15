# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for the pure A/B comparison logic.

These need neither the smoke stack nor a model, so they carry no ``smoke`` marker and run
with the ordinary test suite.
"""

import pytest

from tests.smoke.artifacts import (
    METRIC_TOLERANCE,
    RunSnapshot,
    compute_metrics,
    find_metric_regressions,
    load_snapshot,
    render_for_judge,
    save_snapshot,
    story_context,
)
from tests.smoke.judge import JUDGE_SCORE_TOLERANCE, Comparison


def _snapshot(**overrides) -> RunSnapshot:
    """A snapshot of a run that produced one of everything."""
    defaults = {
        "label": "test-model",
        "captured_at": "2026-01-01T00:00:00+00:00",
        "story": {"fields": {"summary": "Reset password", "description": "As a user..."}},
        "review_comments": ["The expiry of the reset link is not specified."],
        "test_cases": [
            {
                "key": "SMOKE-T1",
                "name": "Reset link expires",
                "objective": "Verify expiry",
                "precondition": "A user exists",
                "labels": ["negative"],
                "review_comments": "Add the exact expiry period.",
                "steps": [
                    {"description": "Wait 61 minutes", "expected_result": "The link is rejected", "test_data": ""}
                ],
            }
        ],
        "bugs": [{"summary": "Reset link never expires", "description": "The link stays valid after 60 minutes."}],
    }
    return RunSnapshot(**(defaults | overrides))


class TestComputeMetrics:
    def test_metrics_describe_what_the_run_produced(self):
        metrics = compute_metrics(_snapshot())
        assert metrics["requirements_review"]["comments"] == 1.0
        assert metrics["test_case_generation"]["test_cases"] == 1.0
        assert metrics["test_case_generation"]["avg_steps_per_case"] == 1.0
        assert metrics["test_case_generation"]["cases_with_objective"] == 1.0
        assert metrics["test_case_generation"]["steps_with_expected_result"] == 1.0
        assert metrics["test_case_review"]["reviewed_cases"] == 1.0
        assert metrics["incident_report"]["bugs"] == 1.0

    def test_empty_run_yields_zeroes_instead_of_failing(self):
        metrics = compute_metrics(_snapshot(review_comments=[], test_cases=[], bugs=[]))
        assert metrics["test_case_generation"]["test_cases"] == 0.0
        assert metrics["test_case_generation"]["avg_steps_per_case"] == 0.0
        assert metrics["test_case_review"]["reviewed_cases"] == 0.0
        assert metrics["incident_report"]["avg_bug_description_length"] == 0.0

    def test_unreviewed_case_lowers_the_reviewed_ratio(self):
        reviewed_case = _snapshot().test_cases[0]
        cases = [reviewed_case, {**reviewed_case, "key": "SMOKE-T2", "review_comments": "  "}]
        metrics = compute_metrics(_snapshot(test_cases=cases))
        assert metrics["test_case_review"]["reviewed_cases"] == 0.5


class TestSnapshotStorage:
    def test_a_stored_baseline_is_read_back_unchanged(self, tmp_path):
        path = tmp_path / "baselines" / "default.json"
        save_snapshot(path, _snapshot())
        assert load_snapshot(path) == _snapshot()


class TestFindMetricRegressions:
    def test_identical_runs_do_not_regress(self):
        metrics = compute_metrics(_snapshot())
        assert find_metric_regressions(metrics, metrics) == []

    def test_a_drop_within_the_tolerance_is_not_a_regression(self):
        baseline = {"test_case_generation": {"test_cases": 8.0}}
        candidate = {"test_case_generation": {"test_cases": 8.0 * (1 - METRIC_TOLERANCE) + 0.1}}
        assert find_metric_regressions(baseline, candidate) == []

    def test_a_drop_beyond_the_tolerance_is_a_regression(self):
        baseline = {"test_case_generation": {"test_cases": 8.0}}
        candidate = {"test_case_generation": {"test_cases": 3.0}}
        regressions = find_metric_regressions(baseline, candidate)
        assert [(r.dimension, r.metric, r.candidate) for r in regressions] == [
            ("test_case_generation", "test_cases", 3.0)
        ]

    def test_a_dimension_the_candidate_never_produced_is_a_regression(self):
        regressions = find_metric_regressions({"incident_report": {"bugs": 1.0}}, {})
        assert len(regressions) == 1
        assert regressions[0].candidate == 0.0


class TestRenderForJudge:
    @pytest.mark.parametrize(
        ("dimension", "expected"),
        [
            ("requirements_review", "expiry of the reset link"),
            ("test_case_generation", "Wait 61 minutes"),
            ("test_case_review", "Add the exact expiry period."),
            ("incident_report", "Reset link never expires"),
        ],
    )
    def test_every_dimension_renders_its_own_outputs(self, dimension: str, expected: str):
        assert expected in render_for_judge(dimension, _snapshot())

    def test_unknown_dimension_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown dimension"):
            render_for_judge("nonsense", _snapshot())

    def test_story_context_carries_the_requirement(self):
        assert story_context(_snapshot()) == "Reset password\n\nAs a user..."


class TestJudgeComparison:
    def test_a_better_candidate_does_not_regress(self):
        assert not Comparison("test_case_generation", baseline_score=6.0, candidate_score=8.0, rationale="").regressed

    def test_a_gap_within_the_tolerance_does_not_regress(self):
        comparison = Comparison(
            "test_case_generation", baseline_score=8.0, candidate_score=8.0 - JUDGE_SCORE_TOLERANCE, rationale=""
        )
        assert not comparison.regressed

    def test_a_gap_beyond_the_tolerance_regresses(self):
        assert Comparison("test_case_generation", baseline_score=8.0, candidate_score=5.0, rationale="").regressed
