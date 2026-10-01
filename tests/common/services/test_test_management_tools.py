# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

from common.models import (
    DesignedTestCase,
    DesignStopReason,
    FindingAction,
    FindingSeverity,
    OverlappingTestCase,
    ReviewFinding,
    TestCaseDesignSession,
    TestCaseDuplicateCheck,
)
from common.services import test_management_tools as tools
from common.services.test_management_base import TestManagementClientBase
from common.services.test_management_tools import (
    DUPLICATE_CHECK_HEADING,
    render_duplicate_check,
    render_review_comment,
)


@pytest.fixture
def client() -> Iterator[MagicMock]:
    mock_client = MagicMock(spec=TestManagementClientBase)
    with patch("common.services.test_management_tools.get_test_management_client", return_value=mock_client):
        yield mock_client


def _test_case(name: str, key: str | None = None) -> DesignedTestCase:
    return DesignedTestCase(
        key=key,
        labels=[],
        name=name,
        summary="s",
        comment="",
        preconditions=None,
        steps=[],
        parent_issue_key="P-1",
        ac_ids=["AC-1"],
    )


def _finding(
    owner: str | None,
    severity: FindingSeverity = FindingSeverity.MEDIUM,
    category: str = "clarity",
    related: list[str] | None = None,
    action: FindingAction = FindingAction.MODIFY,
) -> ReviewFinding:
    return ReviewFinding(
        owner_test_case_id=owner,
        action=action,
        severity=severity,
        category=category,
        description=f"{category} problem",
        suggested_fix=f"fix {category}",
        related_test_case_ids=related or [],
    )


def _saved_session() -> TestCaseDesignSession:
    session = TestCaseDesignSession(story_key="PROJ-7", story_id=70, iteration=2, uploaded=True)
    session.test_cases = {"PROJ-T1": _test_case("First", "PROJ-T1"), "PROJ-T2": _test_case("Second", "PROJ-T2")}
    session.duplicate_checks = {"PROJ-T1": TestCaseDuplicateCheck(), "PROJ-T2": TestCaseDuplicateCheck()}
    return session


async def test_upload_saves_the_drafts_in_order_and_replaces_their_ids_everywhere(client):
    session = TestCaseDesignSession(story_key="PROJ-7", story_id=70)
    first, second = session.add_draft(_test_case("First")), session.add_draft(_test_case("Second"))
    session.findings = {first: [_finding(first, related=[second])]}
    session.suite_findings = [_finding(second, related=[first]), _finding(None, action=FindingAction.ADD_TEST_CASE)]
    session.duplicate_checks = {first: TestCaseDuplicateCheck(), second: TestCaseDuplicateCheck()}
    client.create_test_cases.return_value = ["PROJ-T1", "PROJ-T2"]

    await tools.upload_test_cases(session)

    saved, project_key, story_id = client.create_test_cases.call_args.args
    assert [test_case.name for test_case in saved] == ["First", "Second"]
    assert (project_key, story_id) == ("PROJ", 70)
    assert {key: test_case.key for key, test_case in session.test_cases.items()} == {
        "PROJ-T1": "PROJ-T1",
        "PROJ-T2": "PROJ-T2",
    }
    assert session.findings["PROJ-T1"][0].related_test_case_ids == ["PROJ-T2"]
    assert [f.owner_test_case_id for f in session.suite_findings] == ["PROJ-T2", None]
    assert session.suite_findings[0].related_test_case_ids == ["PROJ-T1"]
    assert set(session.duplicate_checks) == {"PROJ-T1", "PROJ-T2"}
    assert session.changed_test_case_ids == {"PROJ-T1", "PROJ-T2"}
    assert session.uploaded


async def test_upload_without_the_story_id_fails(client):
    session = TestCaseDesignSession(story_key="PROJ-7")
    session.add_draft(_test_case("First"))

    with pytest.raises(RuntimeError, match="no generated test cases"):
        await tools.upload_test_cases(session)

    client.create_test_cases.assert_not_called()


async def test_upload_fails_when_not_every_test_case_was_saved(client):
    session = TestCaseDesignSession(story_key="PROJ-7", story_id=70)
    session.add_draft(_test_case("First"))
    session.add_draft(_test_case("Second"))
    client.create_test_cases.return_value = ["PROJ-T1"]

    with pytest.raises(RuntimeError, match="Saved only 1 of 2"):
        await tools.upload_test_cases(session)

    assert not session.uploaded
    assert set(session.test_cases) == {"DRAFT-1", "DRAFT-2"}


async def test_review_feedback_comment_holds_header_findings_by_severity_and_duplicate_check(client):
    session = _saved_session()
    session.stop_reason = DesignStopReason.ITERATION_LIMIT
    session.findings = {
        "PROJ-T1": [_finding("PROJ-T1", FindingSeverity.LOW, "wording"), _finding("PROJ-T1", FindingSeverity.HIGH)],
        "PROJ-T2": [_finding("PROJ-T2", FindingSeverity.CRITICAL, "other test case")],
    }
    session.suite_findings = [_finding("PROJ-T1", FindingSeverity.CRITICAL, "coverage gap", related=["PROJ-T2"])]

    await tools.add_review_feedback(session, "PROJ-T1")

    key, comment = client.add_test_case_review_comment.call_args.args
    assert key == "PROJ-T1"
    assert comment.startswith("<h4>Test case review</h4><p>Review iterations: 2, stop reason: iteration_limit.</p>")
    assert comment.index("[CRITICAL] coverage gap") < comment.index("[HIGH] clarity") < comment.index("[LOW] wording")
    assert "Related test cases: PROJ-T2" in comment
    assert "other test case" not in comment
    assert comment.endswith(render_duplicate_check(TestCaseDuplicateCheck()))
    assert "\n" not in comment


def test_review_comment_escapes_the_model_written_text():
    session = _saved_session()
    finding = _finding("PROJ-T1", category="<script>x</script>").model_copy(
        update={"description": "a <b>", "suggested_fix": "b & c", "ac_ref": "<AC-1>", "related_test_case_ids": ["<i>"]}
    )
    session.findings = {"PROJ-T1": [finding]}

    comment = render_review_comment(session, "PROJ-T1")

    assert "<script>" not in comment
    assert "&lt;script&gt;x&lt;/script&gt;" in comment
    assert "a &lt;b&gt;" in comment
    assert "b &amp; c" in comment
    assert "(&lt;AC-1&gt;)" in comment
    assert "Related test cases: &lt;i&gt;" in comment


def test_review_comment_without_findings_or_stop_reason_says_so():
    session = _saved_session()

    comment = render_review_comment(session, "PROJ-T2")

    assert comment.startswith("<h4>Test case review</h4><p>Review iterations: 2.</p><p>No findings.</p>")
    assert "Open findings of the test set" not in comment


def test_every_review_comment_shows_the_test_set_findings_owned_by_no_test_case():
    session = _saved_session()
    gap = _finding(None, FindingSeverity.HIGH, "missing coverage of AC-3", action=FindingAction.ADD_TEST_CASE)
    session.suite_findings = [gap]

    comments = [render_review_comment(session, key) for key in ("PROJ-T1", "PROJ-T2")]

    for comment in comments:
        assert "<p>No findings.</p><h4>Open findings of the test set</h4><ul><li><b>[HIGH] missing coverage" in comment
        assert comment.endswith(render_duplicate_check(TestCaseDuplicateCheck()))


async def test_review_complete_status_is_set_in_the_project_of_the_story(client):
    await tools.set_test_case_status_to_review_complete(_saved_session(), "PROJ-T2")

    client.change_test_case_status.assert_called_once_with("PROJ", "PROJ-T2", "Review Complete")


def test_rendered_check_without_duplicates_says_so():
    rendered = render_duplicate_check(TestCaseDuplicateCheck())

    assert rendered == f"<h4>{DUPLICATE_CHECK_HEADING}</h4><p>No duplicate test cases found.</p>"


def test_rendered_check_lists_full_and_partial_overlaps_separately_and_escaped():
    check = TestCaseDuplicateCheck(
        overlapping_test_cases=[
            OverlappingTestCase(
                test_case_key="TC-7", overlap_explanation="Both check <script>login</script>", fully_covers=False
            ),
            OverlappingTestCase(test_case_key="TC-8", overlap_explanation="Same logout", fully_covers=True),
            OverlappingTestCase(test_case_key="TC-9", overlap_explanation="Same reset", fully_covers=False),
        ]
    )

    rendered = render_duplicate_check(check)

    assert rendered == (
        f"<h4>{DUPLICATE_CHECK_HEADING}</h4>"
        "<p>Fully covered by:</p><ul><li><b>TC-8</b>: Same logout</li></ul>"
        "<p>Partially overlapping with:</p><ul>"
        "<li><b>TC-7</b>: Both check &lt;script&gt;login&lt;/script&gt;</li><li><b>TC-9</b>: Same reset</li></ul>"
    )


@pytest.mark.parametrize(
    ("fully_covers", "title"), [(True, "Fully covered by:"), (False, "Partially overlapping with:")]
)
def test_rendered_check_shows_only_the_sub_section_which_has_overlaps(fully_covers, title):
    overlap = OverlappingTestCase(test_case_key="TC-7", overlap_explanation="Same login", fully_covers=fully_covers)

    rendered = render_duplicate_check(TestCaseDuplicateCheck(overlapping_test_cases=[overlap]))

    assert rendered == f"<h4>{DUPLICATE_CHECK_HEADING}</h4><p>{title}</p><ul><li><b>TC-7</b>: Same login</li></ul>"
