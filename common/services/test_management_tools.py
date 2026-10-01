# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Test management system writes that publish the test cases of a test case design session."""

import asyncio
import html

import config
from common import utils
from common.models import (
    OverlappingTestCase,
    TestCaseDesignSession,
    TestCaseDuplicateCheck,
    TestCaseReviewFinding,
)
from common.services.test_management_system_client_provider import get_test_management_client

logger = utils.get_logger("test_management_tools")

DUPLICATE_CHECK_HEADING = "Duplicate check"
REVIEW_COMMENT_HEADING = "Test case review"


async def upload_test_cases(session: TestCaseDesignSession) -> None:
    """Saves each not yet saved test case of the design, linked to the user story, and re-keys it right away."""
    if session.story_id is None or not session.test_cases:
        raise RuntimeError(f"There are no generated test cases of the user story {session.story_key} to save.")
    client = get_test_management_client()
    # One test case per request, so a failure leaves every earlier one re-keyed and a repeated upload saves none twice.
    for draft_id in [
        test_case_id for test_case_id in session.test_cases if test_case_id not in session.saved_test_case_keys
    ]:
        keys = await asyncio.to_thread(
            client.create_test_cases, [session.test_cases[draft_id]], session.project_key, session.story_id
        )
        if len(keys) != 1:
            raise RuntimeError(f"Saving the test case {draft_id} of {session.story_key} returned the keys {keys}.")
        _rekey(session, {draft_id: keys[0]})
        session.saved_test_case_keys.add(keys[0])
        logger.info("Saved the test case %s of %s as %s.", draft_id, session.story_key, keys[0])


async def add_review_feedback(session: TestCaseDesignSession, test_case_key: str) -> None:
    """Adds the final review of a saved test case to it as a comment, once, rendered from its review findings."""
    if test_case_key in session.commented_test_case_keys:
        return
    client = get_test_management_client()
    await asyncio.to_thread(
        client.add_test_case_review_comment, test_case_key, render_review_comment(session, test_case_key)
    )
    session.commented_test_case_keys.add(test_case_key)
    logger.info("Added the review feedback to the test case %s.", test_case_key)


async def set_test_case_status_to_review_complete(session: TestCaseDesignSession, test_case_key: str) -> None:
    if test_case_key in session.review_complete_test_case_keys:
        return
    status_name = config.TestCaseReviewAgentConfig.REVIEW_COMPLETE_STATUS_NAME
    client = get_test_management_client()
    await asyncio.to_thread(client.change_test_case_status, session.project_key, test_case_key, status_name)
    session.review_complete_test_case_keys.add(test_case_key)
    logger.info("Set the status of the test case %s to '%s'.", test_case_key, status_name)


def render_review_comment(session: TestCaseDesignSession, test_case_key: str) -> str:
    """Renders the review comment of a test case as HTML: header, latest findings by severity, duplicate check."""
    header = f"<h4>{REVIEW_COMMENT_HEADING}</h4><p>Review iterations: {session.iteration}"
    if session.stop_reason is not None:
        header += f", stop reason: {session.stop_reason.value}"
    body = _render_findings(_latest_findings(session, test_case_key)) or "<p>No findings.</p>"
    # A missing test case is owned by none, so every comment shows the ones the last review left open.
    unowned = _render_findings([finding for finding in session.suite_findings if finding.owner_test_case_id is None])
    test_set_section = f"<h4>Open findings of the test set</h4>{unowned}" if unowned else ""
    duplicate_section = render_duplicate_check(session.duplicate_checks[test_case_key])
    return f"{header}.</p>{body}{test_set_section}{duplicate_section}"


def render_duplicate_check(duplicate_check: TestCaseDuplicateCheck) -> str:
    """Renders the duplicate check as the HTML section of the test case's review comment."""
    heading = f"<h4>{DUPLICATE_CHECK_HEADING}</h4>"
    if not duplicate_check.overlapping_test_cases:
        return f"{heading}<p>No duplicate test cases found.</p>"
    overlaps = duplicate_check.overlapping_test_cases
    sections = (
        ("Fully covered by:", [overlap for overlap in overlaps if overlap.fully_covers]),
        ("Partially overlapping with:", [overlap for overlap in overlaps if not overlap.fully_covers]),
    )
    return heading + "".join(
        f"<p>{title}</p><ul>{_render_overlaps(section)}</ul>" for title, section in sections if section
    )


def _render_overlaps(overlaps: list[OverlappingTestCase]) -> str:
    return "".join(
        f"<li><b>{html.escape(overlap.test_case_key)}</b>: {html.escape(overlap.overlap_explanation)}</li>"
        for overlap in overlaps
    )


def _latest_findings(session: TestCaseDesignSession, test_case_key: str) -> list[TestCaseReviewFinding]:
    """The test case's own findings plus the whole-set findings it owns, as the last review left them."""
    owned_suite_findings = [
        finding for finding in session.suite_findings if finding.owner_test_case_id == test_case_key
    ]
    return [*session.findings.get(test_case_key, []), *owned_suite_findings]


def _render_findings(findings: list[TestCaseReviewFinding]) -> str:
    """The findings as an HTML list, most severe first, or an empty string when there are none."""
    if not findings:
        return ""
    ordered = sorted(findings, key=lambda finding: -finding.severity.rank)
    return f"<ul>{''.join(_render_finding(finding) for finding in ordered)}</ul>"


def _render_finding(finding: TestCaseReviewFinding) -> str:
    ac_ref = f" ({html.escape(finding.ac_ref)})" if finding.ac_ref else ""
    related = (
        f"<br>Related test cases: {html.escape(', '.join(finding.related_test_case_ids))}"
        if finding.related_test_case_ids
        else ""
    )
    return (
        f"<li><b>[{finding.severity.value.upper()}] {html.escape(finding.category)}</b>{ac_ref}: "
        f"{html.escape(finding.description)}<br>Suggested fix: {html.escape(finding.suggested_fix)}{related}</li>"
    )


def _rekey(session: TestCaseDesignSession, new_ids: dict[str, str]) -> None:
    """Replaces the draft IDs by the saved keys everywhere in the session."""

    def rekey_finding(finding: TestCaseReviewFinding) -> TestCaseReviewFinding:
        owner = finding.owner_test_case_id
        return finding.model_copy(
            update={
                "owner_test_case_id": owner and new_ids.get(owner, owner),
                "related_test_case_ids": [
                    new_ids.get(related_id, related_id) for related_id in finding.related_test_case_ids
                ],
            }
        )

    session.test_cases = {
        new_ids.get(test_case_id, test_case_id): test_case.model_copy(
            update={"key": new_ids.get(test_case_id, test_case.key)}
        )
        for test_case_id, test_case in session.test_cases.items()
    }
    session.findings = {
        new_ids.get(test_case_id, test_case_id): [rekey_finding(finding) for finding in findings]
        for test_case_id, findings in session.findings.items()
    }
    session.suite_findings = [rekey_finding(finding) for finding in session.suite_findings]
    session.duplicate_checks = {
        new_ids.get(test_case_id, test_case_id): check for test_case_id, check in session.duplicate_checks.items()
    }
    session.changed_test_case_ids = {
        new_ids.get(test_case_id, test_case_id) for test_case_id in session.changed_test_case_ids
    }
