# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Test management system write tools that act on the test cases of a test case design session."""

import asyncio
import html

from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.tools import ToolDefinition

import config
from common import utils
from common.agent_base import is_delegated_run
from common.models import (
    DRAFT_ID_PREFIX,
    ReviewFinding,
    TestCaseDesignSession,
    TestCaseDuplicateCheck,
)
from common.services.test_management_system_client_provider import get_test_management_client

logger = utils.get_logger("test_management_tools")

DUPLICATE_CHECK_HEADING = "Duplicate check"
REVIEW_COMMENT_HEADING = "Test case review"


async def upload_test_cases(ctx: RunContext[TestCaseDesignSession]) -> str:
    """Saves every test case of the design session in the test management system, linked to the user story.

    Returns:
        A confirmation message with the keys of the saved test cases, which replace their draft IDs.
    """
    session = ctx.deps
    if session.uploaded:
        raise ModelRetry("The test cases are already saved; never save them twice.")
    if session.story_id is None or not session.test_cases:
        raise RuntimeError(f"There are no generated test cases of the user story {session.story_key} to save.")
    draft_ids = list(session.test_cases)
    client = get_test_management_client()
    keys = await asyncio.to_thread(
        client.create_test_cases,
        [session.test_cases[draft_id] for draft_id in draft_ids],
        session.project_key,
        session.story_id,
    )
    if len(keys) != len(draft_ids):
        raise RuntimeError(f"Saved only {len(keys)} of {len(draft_ids)} test cases of {session.story_key}: {keys}.")
    _rekey(session, dict(zip(draft_ids, keys, strict=True)))
    session.uploaded = True
    logger.info("Saved %d test case(s) of %s: %s", len(keys), session.story_key, keys)
    return f"Successfully saved the test cases with the following keys: {', '.join(keys)}"


async def add_review_feedback(ctx: RunContext[TestCaseDesignSession], test_case_key: str) -> str:
    """Adds the final review of a saved test case to it as a comment, rendered from its review findings.

    Args:
        test_case_key: The key of the saved test case.

    Returns:
        A confirmation message.
    """
    session = ctx.deps
    _require_saved(session, test_case_key)
    if test_case_key in session.feedback_added_ids:
        raise ModelRetry(f"The review feedback of '{test_case_key}' is already added; never add it twice.")
    if test_case_key not in session.duplicate_checks:
        raise ModelRetry(
            f"No duplicate check exists for the test case '{test_case_key}'. Pass exactly the key of a reviewed "
            "test case."
        )
    client = get_test_management_client()
    await asyncio.to_thread(
        client.add_test_case_review_comment, test_case_key, render_review_comment(session, test_case_key)
    )
    session.feedback_added_ids.add(test_case_key)
    logger.info("Added the review feedback to the test case %s.", test_case_key)
    return f"Successfully added the review feedback to the test case '{test_case_key}'."


async def set_test_case_status_to_review_complete(ctx: RunContext[TestCaseDesignSession], test_case_key: str) -> str:
    """Sets the status of a saved test case to "Review Complete".

    Args:
        test_case_key: The key of the saved test case.

    Returns:
        A confirmation message.
    """
    session = ctx.deps
    _require_saved(session, test_case_key)
    if test_case_key in session.review_completed_ids:
        raise ModelRetry(f"The status of '{test_case_key}' is already set; never set it twice.")
    status_name = config.TestCaseReviewAgentConfig.REVIEW_COMPLETE_STATUS_NAME
    client = get_test_management_client()
    await asyncio.to_thread(client.change_test_case_status, session.project_key, test_case_key, status_name)
    session.review_completed_ids.add(test_case_key)
    logger.info("Set the status of the test case %s to '%s'.", test_case_key, status_name)
    return f"Successfully set the status of the test case '{test_case_key}' to '{status_name}'."


def is_designing(session: TestCaseDesignSession) -> bool:
    """Whether the session holds unsaved drafts, i.e. a test case design is still in progress."""
    return any(test_case_id.startswith(DRAFT_ID_PREFIX) for test_case_id in session.test_cases)


async def hide_while_designing(
    ctx: RunContext[TestCaseDesignSession], tool_def: ToolDefinition
) -> ToolDefinition | None:
    """Offers a write tool only outside a delegated run: while designing, the design agent does every write."""
    return None if is_delegated_run() else tool_def


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
    items = "".join(
        f"<li><b>{html.escape(overlap.test_case_key)}</b>: {html.escape(overlap.overlap_explanation)}</li>"
        for overlap in duplicate_check.overlapping_test_cases
    )
    return f"{heading}<p>This test case overlaps in coverage with:</p><ul>{items}</ul>"


def _latest_findings(session: TestCaseDesignSession, test_case_key: str) -> list[ReviewFinding]:
    """The test case's own findings plus the whole-set findings it owns, as the last review left them."""
    owned_suite_findings = [
        finding for finding in session.suite_findings if finding.owner_test_case_id == test_case_key
    ]
    return [*session.findings.get(test_case_key, []), *owned_suite_findings]


def _render_findings(findings: list[ReviewFinding]) -> str:
    """The findings as an HTML list, most severe first, or an empty string when there are none."""
    if not findings:
        return ""
    ordered = sorted(findings, key=lambda finding: -finding.severity.rank)
    return f"<ul>{''.join(_render_finding(finding) for finding in ordered)}</ul>"


def _render_finding(finding: ReviewFinding) -> str:
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


def _require_saved(session: TestCaseDesignSession, test_case_key: str) -> None:
    if test_case_key.startswith(DRAFT_ID_PREFIX):
        raise ModelRetry(f"'{test_case_key}' is a draft; save the test cases first and pass the saved key.")
    if test_case_key not in session.test_cases:
        raise ModelRetry(
            f"'{test_case_key}' is no test case of this design; use one of: {', '.join(session.test_cases)}."
        )


def _rekey(session: TestCaseDesignSession, new_ids: dict[str, str]) -> None:
    """Replaces the draft IDs by the saved keys everywhere in the session."""

    def rekey_finding(finding: ReviewFinding) -> ReviewFinding:
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
        new_ids[draft_id]: test_case.model_copy(update={"key": new_ids[draft_id]})
        for draft_id, test_case in session.test_cases.items()
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
