# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""The user story context which the sub-agents of a test case design share."""

from pydantic_ai.messages import BinaryContent

from common.models import AcceptanceCriteriaList, TestCaseDesignSession
from common.services.jira_attachments import attachment_parts, fetch_issue_attachments


async def fetch_session_attachments(session: TestCaseDesignSession) -> dict[str, BinaryContent]:
    """The attachments of the design session's user story, downloaded once and then reused from the session."""
    if session.attachments is None:
        session.attachments = await fetch_issue_attachments(session.story_key)
    return session.attachments


async def story_context_parts(session: TestCaseDesignSession) -> list[str | BinaryContent]:
    """Build the story context every repeated sub-agent call of a design starts its message with."""
    # Identical in every call and placed first, so the provider can serve it from its prompt-prefix cache.
    criteria = AcceptanceCriteriaList(items=session.acceptance_criteria).model_dump_json()
    return [
        f"Jira Issue content:\n```{session.story_content}```",
        f"Acceptance criteria:\n```{criteria}```",
        *attachment_parts(await fetch_session_attachments(session)),
    ]
