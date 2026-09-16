# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for the Requirements Review agent's reference documentation tool (WS10)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.messages import BinaryContent

from agents.requirements_review.main import RequirementsReviewAgent


@pytest.fixture
def mock_config():
    with patch("agents.requirements_review.main.config") as mock_conf:
        mock_conf.RequirementsReviewAgentConfig.OWN_NAME = "review_agent"
        mock_conf.AGENT_BASE_URL = "http://localhost"
        mock_conf.RequirementsReviewAgentConfig.PORT = 8001
        mock_conf.RequirementsReviewAgentConfig.EXTERNAL_PORT = 8001
        mock_conf.RequirementsReviewAgentConfig.PROTOCOL = "http"
        mock_conf.RequirementsReviewAgentConfig.MODEL_NAME = "test"
        mock_conf.RequirementsReviewAgentConfig.VERSION = "2.5"
        mock_conf.RequirementsReviewAgentConfig.SKILL_ID = "requirements-review"
        mock_conf.RequirementsReviewAgentConfig.SKILL_NAME = "Requirements Review"
        mock_conf.RequirementsReviewAgentConfig.SKILL_DESCRIPTION = "Reviews requirements"
        mock_conf.RequirementsReviewAgentConfig.THINKING_LEVEL = "LOW"
        mock_conf.RequirementsReviewAgentConfig.MAX_REQUESTS_PER_TASK = 5
        mock_conf.ATLASSIAN_MCP_SERVER_URL = "http://jira-mcp"
        mock_conf.MCP_SERVER_TIMEOUT_SECONDS = 30
        mock_conf.QdrantConfig.EMBEDDING_SERVICE_URL = "http://embeddings"
        mock_conf.DocumentRagConfig.DOCUMENTS_COLLECTION_NAME = "documents"
        yield mock_conf


@pytest.fixture
def agent(mock_config):
    with (
        patch("agents.requirements_review.main.RequirementsReviewSystemPrompt.get_prompt", return_value="Prompt"),
        patch("agents.requirements_review.main.RequirementsReviewWithAttachmentsPrompt.get_prompt", return_value="Sub"),
        patch("agents.requirements_review.main.RequirementsReviewRetrievalInstruction.get_prompt", return_value="Retr"),
        patch("agents.requirements_review.main.VectorDbService") as mock_db_cls,
        patch("agents.requirements_review.main.CustomLlmWrapper.create_agent"),
    ):
        review_agent = RequirementsReviewAgent()
        review_agent.documents_db = mock_db_cls.return_value
        review_agent.review_agent.run = AsyncMock(return_value=MagicMock(output=MagicMock(name="feedback")))
        yield review_agent


@pytest.fixture
def retrieved_page() -> MagicMock:
    return MagicMock()


@pytest.fixture
def retrieval(retrieved_page):
    from contextlib import ExitStack

    with ExitStack() as stack:
        patches = [
            stack.enter_context(
                patch("agents.requirements_review.main.download_issue_attachments", return_value={})
            ),
            stack.enter_context(
                patch("agents.requirements_review.main.retrieve_documents", AsyncMock(return_value=[retrieved_page]))
            ),
            stack.enter_context(
                patch("agents.requirements_review.main.assemble_retrieved_parts", return_value=["DOC-PART"])
            ),
        ]
        yield patches


def _ctx(issue_key: str = "PROJ-1") -> MagicMock:
    ctx = MagicMock()
    ctx.deps.key = issue_key
    return ctx


@pytest.mark.asyncio
async def test_blank_retrieval_query_raises_model_retry(agent, retrieval):
    with pytest.raises(ModelRetry, match="retrieval_query"):
        await agent._review_with_reference_documentation(_ctx(), "issue content", retrieval_query="  ")

    agent.review_agent.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_documentation_parts_are_appended_after_issue_and_attachments(agent, retrieval, retrieved_page):
    attachment = BinaryContent(data=b"png", media_type="image/png", identifier="mock.png")
    retrieval[0].return_value = {"mock.png": attachment}

    await agent._review_with_reference_documentation(_ctx(), "issue content", retrieval_query="login flow")

    mock_retrieve = retrieval[1]
    assert mock_retrieve.await_args.args[1] == "login flow"
    parts = agent.review_agent.run.await_args.args[0]
    assert parts[0] == "Jira Issue content:\n```issue content```"
    assert parts[1] == "Attachment: mock.png"
    assert parts[2] is attachment
    assert parts[3] == "DOC-PART"


@pytest.mark.asyncio
async def test_scope_parameters_are_length_capped(agent, retrieval):
    await agent._review_with_reference_documentation(
        _ctx(),
        "issue content",
        retrieval_query="q",
        space_key="S" * 500,
        page_id="P" * 500,
        document_name_pattern="D" * 500,
    )

    scope = retrieval[1].await_args.args[2]
    assert scope.space_key == "S" * 200
    assert scope.page_id == "P" * 200
    assert scope.document_name_pattern == "D" * 200
