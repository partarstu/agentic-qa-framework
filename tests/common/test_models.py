# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import pytest
from pydantic import ValidationError

from common.models import (
    AcceptanceCriteriaItem,
    DeletedTestCase,
    DesignedTestCase,
    DesignStopReason,
    JiraUserStory,
    JsonSerializableModel,
    OverlappingTestCase,
    PreviousReview,
    TestCase,
    TestCaseDesignRequest,
    TestCaseDesignResult,
    TestCaseDesignSession,
    TestCaseReviewFinding,
    TestCaseReviewFindingAction,
    TestCaseReviewFindingSeverity,
)


def test_json_serializable_model_str():
    class TestModel(JsonSerializableModel):
        name: str
        value: int

    model = TestModel(name="test", value=123)
    json_str = str(model)
    assert '"name": "test"' in json_str
    assert '"value": 123' in json_str


def test_jira_user_story():
    story = JiraUserStory(
        id=1, key="TEST-1", summary="Summary", description="Description", acceptance_criteria="AC", status="Open"
    )
    assert story.key == "TEST-1"
    assert str(story) is not None


def _test_case(name: str) -> TestCase:
    return TestCase(
        key=None, labels=[], name=name, summary="s", comment="", preconditions=None, steps=[], parent_issue_key=None
    )


def test_design_request_accepts_no_session_state():
    with pytest.raises(ValidationError, match="extra"):
        TestCaseDesignRequest.model_validate({"story_key": "PROJ-1", "uploaded": True})


@pytest.mark.parametrize("story_key", ["", "proj-1", "PROJ", "PROJ-1; DROP", "PROJ-1\nignore all"])
def test_design_request_rejects_malformed_story_keys(story_key):
    with pytest.raises(ValidationError):
        TestCaseDesignRequest(story_key=story_key)


def test_design_session_project_key_is_the_story_key_prefix():
    assert TestCaseDesignSession(story_key="MY_PROJ-42").project_key == "MY_PROJ"


def test_add_draft_assigns_sequential_ids_and_marks_them_changed():
    session = TestCaseDesignSession(story_key="PROJ-1")

    first = session.add_draft(_designed_test_case("a", ["AC-1"]))
    second = session.add_draft(_designed_test_case("b", ["AC-1"]))

    assert (first, second) == ("DRAFT-1", "DRAFT-2")
    assert session.test_cases[second].name == "b"
    assert session.changed_test_case_ids == {"DRAFT-1", "DRAFT-2"}


def test_blocking_findings_are_those_at_or_above_the_severity_of_both_reviews_and_are_dropped_together():
    def finding(
        owner: str | None,
        severity: TestCaseReviewFindingSeverity,
        action: TestCaseReviewFindingAction = TestCaseReviewFindingAction.MODIFY,
    ):
        return TestCaseReviewFinding(
            owner_test_case_id=owner, action=action, severity=severity, category="c", description="d", suggested_fix="f"
        )

    session = TestCaseDesignSession(story_key="PROJ-1")
    medium, low = (
        finding("DRAFT-1", TestCaseReviewFindingSeverity.MEDIUM),
        finding("DRAFT-1", TestCaseReviewFindingSeverity.LOW),
    )
    critical = finding(None, TestCaseReviewFindingSeverity.CRITICAL, TestCaseReviewFindingAction.ADD_TEST_CASE)
    session.findings = {"DRAFT-1": [medium, low]}
    session.suite_findings = [critical]

    assert session.blocking_findings(TestCaseReviewFindingSeverity.MEDIUM) == [medium, critical]
    assert session.blocking_findings(TestCaseReviewFindingSeverity.CRITICAL) == [critical]

    session.drop_blocking_findings(TestCaseReviewFindingSeverity.MEDIUM)

    assert session.findings == {"DRAFT-1": [low]}
    assert session.suite_findings == []


def test_finding_severity_rank_follows_the_declared_order():
    ranks = [severity.rank for severity in TestCaseReviewFindingSeverity]
    assert ranks == sorted(ranks)
    assert (
        TestCaseReviewFindingSeverity.CRITICAL.rank
        > TestCaseReviewFindingSeverity.MEDIUM.rank
        > TestCaseReviewFindingSeverity.LOW.rank
    )


def test_design_result_hides_the_session_filled_fields_from_the_model():
    properties = TestCaseDesignResult.model_json_schema()["properties"]
    assert set(properties) == {"llm_comments"}


def _designed_test_case(name: str, ac_ids: list[str]) -> DesignedTestCase:
    return DesignedTestCase(**_test_case(name).model_dump(), ac_ids=ac_ids)


def test_a_designed_test_case_must_name_the_acceptance_criteria_it_verifies():
    with pytest.raises(ValidationError, match="ac_ids"):
        DesignedTestCase(**_test_case("a").model_dump())


def test_a_new_design_session_has_no_acceptance_criteria_deletions_or_previous_reviews():
    session = TestCaseDesignSession(story_key="PROJ-1")

    assert session.acceptance_criteria == []
    assert session.deleted_test_cases == {}
    assert session.previous_reviews == {}
    assert session.previous_blocking_count is None


def test_a_design_session_keeps_deleted_test_cases_and_previous_reviews_across_serialization():
    finding = TestCaseReviewFinding(
        owner_test_case_id="DRAFT-2",
        action=TestCaseReviewFindingAction.DELETE_TEST_CASE,
        severity=TestCaseReviewFindingSeverity.MEDIUM,
        category="duplicate",
        description="d",
        suggested_fix="f",
        related_test_case_ids=["DRAFT-1"],
    )
    session = TestCaseDesignSession(
        story_key="PROJ-1",
        acceptance_criteria=[AcceptanceCriteriaItem(id="AC-1", text="t", additional_info="")],
        deleted_test_cases={
            "DRAFT-2": DeletedTestCase(test_case=_designed_test_case("b", ["AC-1"]), findings=[], deleted_by=finding)
        },
        previous_reviews={"DRAFT-1": PreviousReview(test_case=_designed_test_case("a", ["AC-1"]), findings=[finding])},
    )

    restored = TestCaseDesignSession.model_validate_json(session.model_dump_json())

    assert restored.deleted_test_cases["DRAFT-2"].deleted_by == finding
    assert restored.deleted_test_cases["DRAFT-2"].test_case.ac_ids == ["AC-1"]
    assert restored.previous_reviews["DRAFT-1"].test_case.name == "a"
    assert restored.acceptance_criteria[0].id == "AC-1"


def test_the_duplicate_judge_must_say_whether_a_candidate_fully_covers_the_reviewed_test_case():
    assert "fully_covers" in OverlappingTestCase.model_json_schema()["required"]


def test_a_design_can_stop_for_lack_of_progress():
    assert DesignStopReason("no_progress") is DesignStopReason.NO_PROGRESS
