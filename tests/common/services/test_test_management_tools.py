# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic_ai import ModelRetry

from common import agent_base
from common.models import (
    DesignStopReason,
    FindingAction,
    FindingSeverity,
    OverlappingTestCase,
    ReviewFinding,
    TestCase,
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


def _test_case(name: str, key: str | None = None) -> TestCase:
    return TestCase(
        key=key, labels=[], name=name, summary="s", comment="", preconditions=None, steps=[], parent_issue_key="P-1"
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


def _ctx(session: TestCaseDesignSession) -> SimpleNamespace:
    return SimpleNamespace(deps=session)


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

    result = await tools.upload_test_cases(_ctx(session))

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
    assert "PROJ-T1, PROJ-T2" in result


async def test_upload_twice_is_refused_without_writing(client):
    session = _saved_session()

    with pytest.raises(ModelRetry, match="already saved"):
        await tools.upload_test_cases(_ctx(session))

    client.create_test_cases.assert_not_called()


async def test_upload_without_the_story_id_fails(client):
    session = TestCaseDesignSession(story_key="PROJ-7")
    session.add_draft(_test_case("First"))

    with pytest.raises(RuntimeError, match="no generated test cases"):
        await tools.upload_test_cases(_ctx(session))

    client.create_test_cases.assert_not_called()


async def test_upload_fails_when_not_every_test_case_was_saved(client):
    session = TestCaseDesignSession(story_key="PROJ-7", story_id=70)
    session.add_draft(_test_case("First"))
    session.add_draft(_test_case("Second"))
    client.create_test_cases.return_value = ["PROJ-T1"]

    with pytest.raises(RuntimeError, match="Saved only 1 of 2"):
        await tools.upload_test_cases(_ctx(session))

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

    await tools.add_review_feedback(_ctx(session), "PROJ-T1")

    key, comment = client.add_test_case_review_comment.call_args.args
    assert key == "PROJ-T1"
    assert comment.startswith("<h4>Test case review</h4><p>Review iterations: 2, stop reason: iteration_limit.</p>")
    assert comment.index("[CRITICAL] coverage gap") < comment.index("[HIGH] clarity") < comment.index("[LOW] wording")
    assert "Related test cases: PROJ-T2" in comment
    assert "other test case" not in comment
    assert comment.endswith(render_duplicate_check(TestCaseDuplicateCheck()))
    assert "\n" not in comment
    assert session.feedback_added_ids == {"PROJ-T1"}


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


async def test_review_feedback_is_added_only_once(client):
    session = _saved_session()
    session.feedback_added_ids = {"PROJ-T1"}

    with pytest.raises(ModelRetry, match="already added"):
        await tools.add_review_feedback(_ctx(session), "PROJ-T1")

    client.add_test_case_review_comment.assert_not_called()


@pytest.mark.parametrize(
    ("test_case_key", "message"),
    [("DRAFT-1", "is a draft"), ("PROJ-T9", "no test case of this design"), ("PROJ-T3", "No duplicate check")],
)
async def test_review_feedback_is_refused_for_a_test_case_it_cannot_describe(client, test_case_key, message):
    session = _saved_session()
    session.test_cases["PROJ-T3"] = _test_case("Unreviewed", "PROJ-T3")

    with pytest.raises(ModelRetry, match=message):
        await tools.add_review_feedback(_ctx(session), test_case_key)

    client.add_test_case_review_comment.assert_not_called()


async def test_review_complete_status_is_set_once_per_saved_test_case(client):
    session = _saved_session()

    result = await tools.set_test_case_status_to_review_complete(_ctx(session), "PROJ-T2")
    with pytest.raises(ModelRetry, match="already set"):
        await tools.set_test_case_status_to_review_complete(_ctx(session), "PROJ-T2")

    client.change_test_case_status.assert_called_once_with("PROJ", "PROJ-T2", "Review Complete")
    assert session.review_completed_ids == {"PROJ-T2"}
    assert "Review Complete" in result


async def test_review_complete_status_is_refused_for_a_draft(client):
    session = TestCaseDesignSession(story_key="PROJ-7")
    session.add_draft(_test_case("First"))

    with pytest.raises(ModelRetry, match="is a draft"):
        await tools.set_test_case_status_to_review_complete(_ctx(session), "DRAFT-1")

    client.change_test_case_status.assert_not_called()


async def test_write_tools_are_hidden_only_in_a_delegated_run():
    tool_def = MagicMock()
    ctx = _ctx(_saved_session())

    assert await tools.hide_while_designing(ctx, tool_def) is tool_def
    token = agent_base._delegated_run.set(True)
    try:
        assert await tools.hide_while_designing(ctx, tool_def) is None
    finally:
        agent_base._delegated_run.reset(token)


def test_rendered_check_without_duplicates_says_so():
    rendered = render_duplicate_check(TestCaseDuplicateCheck())

    assert rendered == f"<h4>{DUPLICATE_CHECK_HEADING}</h4><p>No duplicate test cases found.</p>"


def test_rendered_check_lists_every_overlap_escaped():
    check = TestCaseDuplicateCheck(
        overlapping_test_cases=[
            OverlappingTestCase(test_case_key="TC-7", overlap_explanation="Both check <script>login</script>"),
            OverlappingTestCase(test_case_key="TC-8", overlap_explanation="Same logout"),
        ]
    )

    rendered = render_duplicate_check(check)

    assert rendered.startswith(f"<h4>{DUPLICATE_CHECK_HEADING}</h4><p>This test case overlaps in coverage with:</p>")
    assert "<li><b>TC-7</b>: Both check &lt;script&gt;login&lt;/script&gt;</li>" in rendered
    assert "<li><b>TC-8</b>: Same logout</li>" in rendered
