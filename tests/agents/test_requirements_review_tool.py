# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for the Requirements Review agent's reference documentation tool."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.exceptions import ModelRetry, UsageLimitExceeded
from pydantic_ai.messages import BinaryContent

from agents.requirements_review.main import RequirementsReviewAgent
from common.models import RequirementsReviewFeedback
from common.services.document_retrieval import RetrievalResult


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
        mock_conf.RequirementsReviewAgentConfig.FOCUS_AREA_COUNT = 3
        mock_conf.BudgetConfig.TOTAL_TOKENS_LIMIT_PER_TASK = 1000
        mock_conf.ATLASSIAN_MCP_SERVER_URL = "http://jira-mcp"
        mock_conf.MCP_SERVER_TIMEOUT_SECONDS = 30
        mock_conf.QdrantConfig.EMBEDDING_SERVICE_URL = "http://embeddings"
        mock_conf.DocumentRagConfig.DOCUMENTS_COLLECTION_NAME = "documents"
        mock_conf.DocumentRagConfig.CONFLUENCE_RETRIEVAL_ENABLED = True
        mock_conf.DocumentRagConfig.SHAREPOINT_RETRIEVAL_ENABLED = False
        yield mock_conf


def _focused_review(parts: list, **_) -> MagicMock:
    """A reviewer run result whose findings name the focus area the run received first."""
    return MagicMock(output=RequirementsReviewFeedback(suggested_improvements=f"findings on {parts[0]}"))


@pytest.fixture
def agent(mock_config):
    with (
        patch("agents.requirements_review.main.RequirementsReviewSystemPrompt.get_prompt", return_value="Prompt"),
        patch("agents.requirements_review.main.RequirementsReviewWithAttachmentsPrompt.get_prompt", return_value="Sub"),
        patch("agents.requirements_review.main.RequirementsReviewRetrievalInstruction.get_prompt", return_value="Retr"),
        patch("agents.requirements_review.main.MergeReviewsPrompt.get_prompt", return_value="Merge"),
        patch("agents.requirements_review.main.VectorDbService") as mock_db_cls,
        # Distinct mocks, so the reviewer and the merge sub-agent can be told apart.
        patch("agents.requirements_review.main.CustomLlmWrapper.create_agent", side_effect=lambda **_: MagicMock()),
    ):
        review_agent = RequirementsReviewAgent()
        review_agent.documents_db = mock_db_cls.return_value
        review_agent.review_agent.run = AsyncMock(side_effect=_focused_review)
        review_agent.merge_agent.run = AsyncMock(
            return_value=MagicMock(output=RequirementsReviewFeedback(suggested_improvements="merged findings"))
        )
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
                patch("agents.requirements_review.main.fetch_issue_attachments", AsyncMock(return_value={}))
            ),
            stack.enter_context(
                patch(
                    "agents.requirements_review.main.retrieve_documents",
                    AsyncMock(return_value=RetrievalResult([retrieved_page], [])),
                )
            ),
            stack.enter_context(
                patch("agents.requirements_review.main.assemble_retrieved_parts", return_value=["DOC-PART"])
            ),
        ]
        yield patches


ISSUE_KEY = "PROJ-1"
FOCUS_AREAS = ["error handling"]


def _focus_areas_of_review_runs(agent: RequirementsReviewAgent) -> list[str]:
    return [call.args[0][0] for call in agent.review_agent.run.await_args_list]


@pytest.mark.asyncio
async def test_blank_retrieval_query_raises_model_retry(agent, retrieval):
    with pytest.raises(ModelRetry, match="retrieval_query"):
        await agent._review_with_reference_documentation(
            ISSUE_KEY, "issue content", focus_areas=FOCUS_AREAS, retrieval_query="  "
        )

    agent.review_agent.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_documentation_parts_are_appended_after_issue_and_attachments(agent, retrieval, retrieved_page):
    attachment = BinaryContent(data=b"png", media_type="image/png", identifier="mock.png")
    retrieval[0].return_value = {"mock.png": attachment}

    await agent._review_with_reference_documentation(
        ISSUE_KEY, "issue content", focus_areas=FOCUS_AREAS, retrieval_query="login flow"
    )

    mock_retrieve = retrieval[1]
    assert mock_retrieve.await_args.args[1] == "login flow"
    parts = agent.review_agent.run.await_args.args[0]
    assert parts[0] == "Review focus area: error handling"
    assert parts[1] == "Jira Issue content:\n```issue content```"
    assert parts[2] == "Attachment: mock.png"
    assert parts[3] is attachment
    assert parts[4] == "DOC-PART"


@pytest.mark.asyncio
async def test_scope_parameters_are_length_capped(agent, retrieval):
    await agent._review_with_reference_documentation(
        ISSUE_KEY,
        "issue content",
        focus_areas=FOCUS_AREAS,
        retrieval_query="q",
        space_key="S" * 500,
        page_id="P" * 500,
        document_name_pattern="D" * 500,
    )

    scope = retrieval[1].await_args.args[2]
    assert scope.space_key == "S" * 200
    assert scope.page_id == "P" * 200
    assert scope.document_name_pattern == "D" * 200


@pytest.fixture
def construct_agent(mock_config):
    """Builds the agent with AgentBase stubbed, returning it with the AgentBase keyword arguments."""

    def _construct(embedding_service_url: str) -> tuple[RequirementsReviewAgent, dict]:
        mock_config.QdrantConfig.EMBEDDING_SERVICE_URL = embedding_service_url
        mock_config.QdrantConfig.METADATA_COLLECTION_NAME = "rag_metadata"
        with (
            patch("agents.requirements_review.main.RequirementsReviewSystemPrompt.get_prompt", return_value="Prompt"),
            patch(
                "agents.requirements_review.main.RequirementsReviewWithAttachmentsPrompt.grounding_suffix",
                return_value="Ground",
            ),
            patch(
                "agents.requirements_review.main.RequirementsReviewWithAttachmentsPrompt.__init__", return_value=None
            ) as mock_sub_prompt_init,
            patch(
                "agents.requirements_review.main.RequirementsReviewWithAttachmentsPrompt.get_prompt", return_value="Sub"
            ),
            patch(
                "agents.requirements_review.main.RequirementsReviewRetrievalInstruction.get_prompt", return_value="Retr"
            ),
            patch("agents.requirements_review.main.VectorDbService") as mock_db_cls,
            patch("agents.requirements_review.main.CustomLlmWrapper.create_agent") as mock_create_agent,
            patch("agents.requirements_review.main.AgentBase.__init__", return_value=None) as mock_base_init,
        ):
            review_agent = RequirementsReviewAgent()
        review_agent.db_class = mock_db_cls
        review_agent.create_agent = mock_create_agent
        review_agent.grounding_instruction = mock_sub_prompt_init.call_args.kwargs["grounding_instruction"]
        return review_agent, mock_base_init.call_args.kwargs

    return _construct


def test_enabled_retrieval_advertises_query_tool_appends_instruction_and_checks_model_identity(construct_agent) -> None:
    review_agent, base_kwargs = construct_agent("http://embeddings")

    assert review_agent.retrieval_enabled
    assert base_kwargs["tools"][0].__name__ == "_review_with_reference_documentation"
    assert base_kwargs["instructions"] == "Prompt\n\nRetr"
    assert review_agent.grounding_instruction == "Ground"
    review_agent.db_class.assert_called_once_with("documents", metadata_collection_name="rag_metadata")


def test_disabled_retrieval_advertises_attachments_only_tool_without_instruction(mock_config, construct_agent) -> None:
    mock_config.DocumentRagConfig.CONFLUENCE_RETRIEVAL_ENABLED = False
    review_agent, base_kwargs = construct_agent("")

    assert not review_agent.retrieval_enabled
    assert review_agent.documents_db is None
    assert base_kwargs["tools"][0].__name__ == "_review_with_attachments"
    assert base_kwargs["instructions"] == "Prompt"
    assert review_agent.grounding_instruction is None
    review_agent.db_class.assert_not_called()


def test_merge_sub_agent_is_metered_as_its_own_operation(construct_agent) -> None:
    review_agent, _ = construct_agent("http://embeddings")

    names = [call.kwargs["name"] for call in review_agent.create_agent.call_args_list]
    assert names == ["review_with_attachments", "merge_reviews"]
    merge_kwargs = review_agent.create_agent.call_args_list[1].kwargs
    assert merge_kwargs["output_type"] is RequirementsReviewFeedback
    assert merge_kwargs["thinking_level"] == "LOW"


@pytest.mark.asyncio
async def test_attachments_only_review_runs_without_retrieval(agent, retrieval) -> None:
    await agent._review_with_attachments(ISSUE_KEY, "issue content", focus_areas=FOCUS_AREAS)

    retrieval[1].assert_not_awaited()
    parts = agent.review_agent.run.await_args.args[0]
    assert parts == ["Review focus area: error handling", "Jira Issue content:\n```issue content```"]


@pytest.mark.asyncio
async def test_retrieval_runtime_failure_fails_the_review(agent, retrieval) -> None:
    retrieval[1].side_effect = ConnectionError("embedding service unreachable")

    with pytest.raises(ConnectionError, match="embedding service unreachable"):
        await agent._review_with_reference_documentation(
            ISSUE_KEY, "issue content", focus_areas=FOCUS_AREAS, retrieval_query="login flow"
        )

    agent.review_agent.run.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("focus_areas", [[], ["a", "b", "c", "d"]], ids=["none", "above-limit"])
async def test_focus_area_count_outside_the_limit_raises_model_retry(agent, retrieval, focus_areas) -> None:
    with pytest.raises(ModelRetry, match="between 1 and 3"):
        await agent._review_with_attachments(ISSUE_KEY, "issue content", focus_areas=focus_areas)

    retrieval[0].assert_not_awaited()
    agent.review_agent.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_blank_focus_area_raises_model_retry(agent, retrieval) -> None:
    with pytest.raises(ModelRetry, match="non-blank"):
        await agent._review_with_reference_documentation(
            ISSUE_KEY, "issue content", focus_areas=["security", " "], retrieval_query="login flow"
        )

    retrieval[1].assert_not_awaited()
    agent.review_agent.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_each_focus_area_gets_its_own_capped_review_on_material_prepared_once(agent, retrieval) -> None:
    await agent._review_with_reference_documentation(
        ISSUE_KEY, "issue content", focus_areas=["security", "F" * 500], retrieval_query="login flow"
    )

    retrieval[0].assert_awaited_once()
    retrieval[1].assert_awaited_once()
    assert _focus_areas_of_review_runs(agent) == ["Review focus area: security", f"Review focus area: {'F' * 200}"]
    for call in agent.review_agent.run.await_args_list:
        assert call.args[0][1:] == ["Jira Issue content:\n```issue content```", "DOC-PART"]
    runs = [*agent.review_agent.run.await_args_list, *agent.merge_agent.run.await_args_list]
    assert len(runs) == 3
    for call in runs:
        assert call.kwargs["usage_limits"].total_tokens_limit == 1000


@pytest.mark.asyncio
async def test_successful_reviews_are_merged_with_their_focus_labels(agent, retrieval) -> None:
    feedback = await agent._review_with_attachments(ISSUE_KEY, "issue content", focus_areas=["security", "usability"])

    merge_input = agent.merge_agent.run.await_args.args[0]
    assert merge_input == (
        "Review focused on 'security':\n```findings on Review focus area: security```\n\n"
        "Review focused on 'usability':\n```findings on Review focus area: usability```"
    )
    assert feedback.suggested_improvements == "merged findings"


@pytest.mark.asyncio
async def test_single_focus_area_skips_the_merge(agent, retrieval) -> None:
    feedback = await agent._review_with_attachments(ISSUE_KEY, "issue content", focus_areas=FOCUS_AREAS)

    agent.merge_agent.run.assert_not_awaited()
    assert feedback.suggested_improvements == "findings on Review focus area: error handling"


@pytest.mark.asyncio
async def test_failed_review_is_logged_skipped_and_named_in_a_note(agent, retrieval, caplog) -> None:
    def fail_on_usability(parts: list, **kwargs) -> MagicMock:
        if parts[0] == "Review focus area: usability":
            raise UsageLimitExceeded("token limit exceeded")
        return _focused_review(parts, **kwargs)

    agent.review_agent.run.side_effect = fail_on_usability

    with caplog.at_level(logging.INFO, logger="reviewer_agent"):
        feedback = await agent._review_with_attachments(
            ISSUE_KEY, "issue content", focus_areas=["security", "usability", "performance"]
        )

    failure_records = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert len(failure_records) == 1
    assert "'usability'" in failure_records[0].getMessage()
    assert isinstance(failure_records[0].exc_info[1], UsageLimitExceeded)
    assert "2 of 3 focused review(s) of issue PROJ-1 succeeded" in caplog.text
    merge_input = agent.merge_agent.run.await_args.args[0]
    assert "'security'" in merge_input and "'performance'" in merge_input and "usability" not in merge_input
    assert feedback.suggested_improvements == (
        "merged findings\n\nNote: the following focus areas were not reviewed because of an error: usability."
    )


@pytest.mark.asyncio
async def test_single_surviving_review_is_returned_with_the_note(agent, retrieval) -> None:
    agent.review_agent.run.side_effect = [ConnectionError("provider down"), _focused_review(["Review focus area: b"])]

    feedback = await agent._review_with_attachments(ISSUE_KEY, "issue content", focus_areas=["a", "b"])

    agent.merge_agent.run.assert_not_awaited()
    assert feedback.suggested_improvements == (
        "findings on Review focus area: b\n\nNote: the following focus areas were not reviewed because of an error: a."
    )


@pytest.mark.asyncio
async def test_all_reviews_failing_reraises_the_first_error(agent, retrieval) -> None:
    first_error = ConnectionError("provider down")
    agent.review_agent.run.side_effect = [first_error, TimeoutError("slow")]

    with pytest.raises(ConnectionError) as raised:
        await agent._review_with_attachments(ISSUE_KEY, "issue content", focus_areas=["a", "b"])

    assert raised.value is first_error
    agent.merge_agent.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_merge_fails_the_review(agent, retrieval) -> None:
    agent.merge_agent.run.side_effect = ConnectionError("provider down")

    with pytest.raises(ConnectionError, match="provider down"):
        await agent._review_with_attachments(ISSUE_KEY, "issue content", focus_areas=["a", "b"])
