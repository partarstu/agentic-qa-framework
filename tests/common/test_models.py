# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import pytest
from pydantic import ValidationError

from common.models import (
    FindingAction,
    FindingSeverity,
    JiraUserStory,
    JsonSerializableModel,
    ReviewFinding,
    TestCase,
    TestCaseDesignResult,
    TestCaseDesignSession,
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


def test_design_session_rejects_unknown_fields():
    with pytest.raises(ValidationError, match="extra"):
        TestCaseDesignSession.model_validate({"story_key": "PROJ-1", "injected": "x"})


@pytest.mark.parametrize("story_key", ["", "proj-1", "PROJ", "PROJ-1; DROP", "PROJ-1\nignore all"])
def test_design_session_rejects_malformed_story_keys(story_key):
    with pytest.raises(ValidationError):
        TestCaseDesignSession(story_key=story_key)


def test_design_session_project_key_is_the_story_key_prefix():
    assert TestCaseDesignSession(story_key="MY_PROJ-42").project_key == "MY_PROJ"


def test_add_draft_assigns_sequential_ids_and_marks_them_changed():
    session = TestCaseDesignSession(story_key="PROJ-1")

    first = session.add_draft(_test_case("a"))
    second = session.add_draft(_test_case("b"))

    assert (first, second) == ("DRAFT-1", "DRAFT-2")
    assert session.test_cases[second].name == "b"
    assert session.changed_test_case_ids == {"DRAFT-1", "DRAFT-2"}


def test_blocking_findings_are_those_at_or_above_the_severity_of_both_reviews():
    def finding(owner: str | None, severity: FindingSeverity, action: FindingAction = FindingAction.MODIFY):
        return ReviewFinding(
            owner_test_case_id=owner, action=action, severity=severity, category="c", description="d", suggested_fix="f"
        )

    session = TestCaseDesignSession(story_key="PROJ-1")
    medium, low = finding("DRAFT-1", FindingSeverity.MEDIUM), finding("DRAFT-1", FindingSeverity.LOW)
    critical = finding(None, FindingSeverity.CRITICAL, FindingAction.ADD_TEST_CASE)
    session.findings = {"DRAFT-1": [medium, low]}
    session.suite_findings = [critical]

    assert session.blocking_findings(FindingSeverity.MEDIUM) == [medium, critical]
    assert session.blocking_findings(FindingSeverity.CRITICAL) == [critical]


def test_finding_severity_rank_follows_the_declared_order():
    ranks = [severity.rank for severity in FindingSeverity]
    assert ranks == sorted(ranks)
    assert FindingSeverity.CRITICAL.rank > FindingSeverity.MEDIUM.rank > FindingSeverity.LOW.rank


def test_design_result_hides_the_session_filled_fields_from_the_model():
    properties = TestCaseDesignResult.model_json_schema()["properties"]
    assert set(properties) == {"llm_comments"}
