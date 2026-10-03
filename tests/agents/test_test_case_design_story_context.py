# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

from unittest.mock import patch

from pydantic_ai.messages import BinaryContent

from agents.test_case_design.story_context import fetch_session_attachments, story_context_parts
from common.models import AcceptanceCriteriaItem, AcceptanceCriteriaList, TestCaseDesignSession


async def test_session_attachments_are_downloaded_once_and_then_reused() -> None:
    session = TestCaseDesignSession(story_key="PROJ-5")
    attachment = BinaryContent(data=b"x", media_type="text/plain")

    with patch("common.services.jira_attachments.download_issue_attachments", return_value={"a.txt": attachment}) as dl:
        first = await fetch_session_attachments(session)
        second = await fetch_session_attachments(session)

    dl.assert_called_once_with("PROJ-5")
    assert first == second == {"a.txt": attachment}
    assert session.attachments == {"a.txt": attachment}


async def test_the_story_context_starts_with_the_story_then_its_criteria_then_its_attachments() -> None:
    criteria = [AcceptanceCriteriaItem(id="AC-1", text="Criterion", additional_info="")]
    attachment = BinaryContent(data=b"x", media_type="text/plain")
    session = TestCaseDesignSession(
        story_key="PROJ-5", story_content="Story", acceptance_criteria=criteria, attachments={"a.txt": attachment}
    )

    assert await story_context_parts(session) == [
        "Jira Issue content:\n```Story```",
        f"Acceptance criteria:\n```{AcceptanceCriteriaList(items=criteria).model_dump_json()}```",
        "Attachment: a.txt",
        attachment,
    ]
