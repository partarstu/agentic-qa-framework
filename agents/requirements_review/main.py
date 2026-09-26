# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import asyncio

from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.messages import BinaryContent
from pydantic_ai.settings import ThinkingLevel
from pydantic_ai.usage import UsageLimits

import config
from agents.requirements_review.prompt import (
    MergeReviewsPrompt,
    RequirementsReviewRetrievalInstruction,
    RequirementsReviewSystemPrompt,
    RequirementsReviewWithAttachmentsPrompt,
)
from common import utils
from common.agent_base import AgentBase
from common.custom_llm_wrapper import CustomLlmWrapper
from common.models import AgentSkillDeclaration, RequirementsReviewFeedback
from common.services.atlassian_mcp import build_atlassian_mcp_server_toolset
from common.services.atlassian_tools import JIRA_ADD_COMMENT, JIRA_GET_ISSUE
from common.services.document_retrieval import (
    RetrievalScope,
    assemble_retrieved_parts,
    retrieve_documents,
)
from common.services.jira_attachments import fetch_issue_attachments
from common.services.vector_db_service import VectorDbService

logger = utils.get_logger("reviewer_agent")

_JIRA_TOOL_ALLOWLIST = (JIRA_GET_ISSUE, JIRA_ADD_COMMENT)

_SCOPE_PARAM_LENGTH_CAP = 200


def _capped(value: str | None) -> str | None:
    """Defensive length cap on the tool's free-text scope parameters."""
    if value is None:
        return None
    return value[:_SCOPE_PARAM_LENGTH_CAP]


def _validated_focus_areas(focus_areas: list[str]) -> list[str]:
    """Checks the focus areas chosen by the model and caps the length of each."""
    max_count = config.RequirementsReviewAgentConfig.FOCUS_AREA_COUNT
    if not 1 <= len(focus_areas) <= max_count:
        raise ModelRetry(f"focus_areas must hold between 1 and {max_count} review focus areas; got {len(focus_areas)}.")
    if any(not focus_area.strip() for focus_area in focus_areas):
        raise ModelRetry("Every item of focus_areas must be a non-blank review focus area.")
    return [_capped(focus_area) for focus_area in focus_areas]


async def _get_issue_message_parts(issue_key: str, jira_issue_content: str) -> list[str | BinaryContent]:
    """The issue content followed by every supported attachment of the issue."""
    attachments_content = await fetch_issue_attachments(issue_key)
    user_message_parts: list[str | BinaryContent] = [f"Jira Issue content:\n```{jira_issue_content}```"]
    for filename, binary_content in attachments_content.items():
        user_message_parts.append(f"Attachment: {filename}")
        user_message_parts.append(binary_content)
    logger.info("Reviewing issue %s with %d attachment(s)", issue_key, len(attachments_content))
    return user_message_parts


class RequirementsReviewAgent(AgentBase):
    def __init__(self):
        # Startup validation is per source: a source whose retrieval switch is on
        # without a configured embedding service fails fast, naming that source.
        for source in ("Confluence", "SharePoint"):
            enabled = getattr(config.DocumentRagConfig, f"{source.upper()}_RETRIEVAL_ENABLED")
            if enabled and not config.QdrantConfig.EMBEDDING_SERVICE_URL:
                raise ValueError(
                    f"{source} retrieval is enabled but EMBEDDING_SERVICE_URL is not configured. "
                    f"Disable {source.upper()}_RETRIEVAL_ENABLED or configure the embedding service."
                )
        self.confluence_retrieval_enabled = config.DocumentRagConfig.CONFLUENCE_RETRIEVAL_ENABLED
        self.sharepoint_retrieval_enabled = config.DocumentRagConfig.SHAREPOINT_RETRIEVAL_ENABLED
        retrieval_enabled = self.confluence_retrieval_enabled or self.sharepoint_retrieval_enabled
        self.retrieval_enabled = retrieval_enabled
        self.documents_db = None
        self.sharepoint_db = None
        if self.confluence_retrieval_enabled:
            # The metadata collection makes retrieval refuse to query vectors of a different model.
            self.documents_db = VectorDbService(
                config.DocumentRagConfig.DOCUMENTS_COLLECTION_NAME,
                metadata_collection_name=config.QdrantConfig.METADATA_COLLECTION_NAME,
            )
        if self.sharepoint_retrieval_enabled:
            self.sharepoint_db = VectorDbService(
                config.QdrantConfig.SHAREPOINT_COLLECTION_NAME,
                metadata_collection_name=config.QdrantConfig.METADATA_COLLECTION_NAME,
            )
        if not retrieval_enabled:
            logger.info(
                "Document retrieval is disabled: no source has retrieval enabled. "
                "The review proceeds on the issue and its attachments only."
            )

        # Create a sub-agent for reviewing with attachments
        self.review_agent = CustomLlmWrapper.create_agent(
            model_name=config.RequirementsReviewAgentConfig.MODEL_NAME,
            output_type=RequirementsReviewFeedback,
            system_prompt=RequirementsReviewWithAttachmentsPrompt(
                grounding_instruction=RequirementsReviewWithAttachmentsPrompt.grounding_suffix()
                if retrieval_enabled
                else None
            ).get_prompt(),
            name="review_with_attachments",
            thinking_level=config.RequirementsReviewAgentConfig.THINKING_LEVEL,
            max_output_tokens=config.RequirementsReviewAgentConfig.MAX_OUTPUT_TOKENS,
        )
        self.merge_agent = CustomLlmWrapper.create_agent(
            model_name=config.RequirementsReviewAgentConfig.MODEL_NAME,
            output_type=RequirementsReviewFeedback,
            system_prompt=MergeReviewsPrompt().get_prompt(),
            name="merge_reviews",
            thinking_level=config.RequirementsReviewAgentConfig.THINKING_LEVEL,
            max_output_tokens=config.RequirementsReviewAgentConfig.MAX_OUTPUT_TOKENS,
        )

        instruction_prompt = RequirementsReviewSystemPrompt()
        instructions = instruction_prompt.get_prompt()
        if retrieval_enabled:
            instructions += "\n\n" + RequirementsReviewRetrievalInstruction().get_prompt()
        review_tool = self._review_with_reference_documentation if retrieval_enabled else self._review_with_attachments
        super().__init__(
            agent_name=config.RequirementsReviewAgentConfig.OWN_NAME,
            base_url=config.AGENT_BASE_URL,
            port=config.RequirementsReviewAgentConfig.PORT,
            external_port=config.RequirementsReviewAgentConfig.EXTERNAL_PORT,
            protocol=config.RequirementsReviewAgentConfig.PROTOCOL,
            model_name=config.RequirementsReviewAgentConfig.MODEL_NAME,
            version=config.RequirementsReviewAgentConfig.VERSION,
            max_output_tokens=config.RequirementsReviewAgentConfig.MAX_OUTPUT_TOKENS,
            output_type=RequirementsReviewFeedback,
            instructions=instructions,
            mcp_toolset_factories=[lambda: build_atlassian_mcp_server_toolset(_JIRA_TOOL_ALLOWLIST)],
            skill=AgentSkillDeclaration(
                id=config.RequirementsReviewAgentConfig.SKILL_ID,
                name=config.RequirementsReviewAgentConfig.SKILL_NAME,
                description=config.RequirementsReviewAgentConfig.SKILL_DESCRIPTION,
            ),
            # The advertised review tool reflects enablement: only with retrieval does it take a query and scope.
            tools=[review_tool, self.add_jira_comment],
        )

    def get_thinking_level(self) -> ThinkingLevel:
        return config.RequirementsReviewAgentConfig.THINKING_LEVEL

    def get_max_requests_per_task(self) -> int:
        return config.RequirementsReviewAgentConfig.MAX_REQUESTS_PER_TASK

    async def _review_with_attachments(
        self, jira_issue_key: str, jira_issue_content: str, focus_areas: list[str]
    ) -> RequirementsReviewFeedback:
        """
        Reviews a Jira issue, taking into account all its attachments, with one focused review per focus area.

        Args:
            jira_issue_key: The key of the Jira issue (e.g. PROJ-123), used to download its attachments.
            jira_issue_content: The complete content of the Jira issue.
            focus_areas: The most important review focus areas for this issue, each a short phrase (e.g.
                "acceptance criteria testability", "error handling"); at least one, at most the number the
                instructions allow.

        Returns:
            Requirements review feedback with improvement suggestions, merged across all focus areas.
        """
        focus_areas = _validated_focus_areas(focus_areas)
        user_message_parts = await _get_issue_message_parts(jira_issue_key, jira_issue_content)
        return await self._run_review(jira_issue_key, user_message_parts, focus_areas)

    async def _review_with_reference_documentation(
        self,
        jira_issue_key: str,
        jira_issue_content: str,
        focus_areas: list[str],
        retrieval_query: str,
        space_key: str | None = None,
        page_id: str | None = None,
        document_name_pattern: str | None = None,
        drive_id: str | None = None,
        folder_path: str | None = None,
    ) -> RequirementsReviewFeedback:
        """
        Reviews a Jira issue, taking into account all its attachments and the reference
        documentation matching the retrieval query across every enabled source, with one
        focused review per focus area.

        Args:
            jira_issue_key: The key of the Jira issue (e.g. PROJ-123), used to download its attachments.
            jira_issue_content: The complete content of the Jira issue.
            focus_areas: The most important review focus areas for this issue, each a short phrase (e.g.
                "acceptance criteria testability", "error handling"); at least one, at most the number the
                instructions allow.
            retrieval_query: A concise documentation search query (key topics, feature
                names, domain terms).
            space_key: Optional Confluence space key scope.
            page_id: Optional Confluence page ID scope.
            document_name_pattern: Optional regex pattern on document names, applied to every source.
            drive_id: Optional SharePoint drive ID scope.
            folder_path: Optional SharePoint folder path scope, relative to the drive root.

        Returns:
            Requirements review feedback with improvement suggestions, merged across all focus areas.
        """
        if not retrieval_query.strip():
            # No fallback to the issue content: a missing query is an explicit tool error.
            raise ModelRetry(
                "A non-blank retrieval_query is required: distil key topics, feature names "
                "and domain terms from the issue and pass them as retrieval_query."
            )
        focus_areas = _validated_focus_areas(focus_areas)

        user_message_parts = await _get_issue_message_parts(jira_issue_key, jira_issue_content)
        scope = RetrievalScope(
            space_key=_capped(space_key),
            page_id=_capped(page_id),
            document_name_pattern=_capped(document_name_pattern),
            drive_id=_capped(drive_id),
            folder_path=_capped(folder_path),
        )
        result = await retrieve_documents(self.documents_db, retrieval_query, scope, sharepoint_db=self.sharepoint_db)
        for source in result.unavailable_sources:
            # The review must say that a source could not be consulted, so nobody mistakes a
            # partial result for the full knowledge base.
            user_message_parts.append(
                f"Note: the {source} knowledge base was unavailable during this review; "
                f"its documents could not be consulted."
            )
        # Reference documentation comes after the issue content and the Jira attachments.
        user_message_parts.extend(assemble_retrieved_parts(result.pages))
        logger.info(
            "Retrieved %d reference documentation page(s) for issue %s (unavailable sources: %s)",
            len(result.pages),
            jira_issue_key,
            result.unavailable_sources or "none",
        )
        return await self._run_review(jira_issue_key, user_message_parts, focus_areas)

    async def _run_review(
        self, jira_issue_key: str, user_message_parts: list[str | BinaryContent], focus_areas: list[str]
    ) -> RequirementsReviewFeedback:
        """Runs one reviewer per focus area in parallel and merges the reviews that succeeded."""
        # Each run gets its own token cap; a shared RunUsage would let one reviewer starve the others.
        usage_limits = UsageLimits(total_tokens_limit=config.BudgetConfig.TOTAL_TOKENS_LIMIT_PER_TASK)
        results = await asyncio.gather(
            *[
                self.review_agent.run(
                    [f"Review focus area: {focus_area}", *user_message_parts], usage_limits=usage_limits
                )
                for focus_area in focus_areas
            ],
            return_exceptions=True,
        )

        reviews: list[tuple[str, RequirementsReviewFeedback]] = []
        failures: list[BaseException] = []
        failed_focus_areas: list[str] = []
        for focus_area, result in zip(focus_areas, results, strict=True):
            if isinstance(result, BaseException):
                # gather(return_exceptions=True) returns the exception instead of raising it, so
                # there is no active exception for logger.exception to read a traceback from.
                logger.error(
                    "Review of focus area %r for issue %s failed; continuing without it.",
                    focus_area,
                    jira_issue_key,
                    exc_info=result,
                )
                failures.append(result)
                failed_focus_areas.append(focus_area)
            else:
                reviews.append((focus_area, result.output))
        logger.info("%d of %d focused review(s) of issue %s succeeded", len(reviews), len(focus_areas), jira_issue_key)
        if not reviews:
            # The first error keeps the provider-retry handling of AgentBase working for the whole task.
            raise failures[0]

        feedback = reviews[0][1] if len(reviews) == 1 else await self._merge_reviews(reviews, usage_limits)
        if failed_focus_areas:
            feedback.suggested_improvements += (
                "\n\nNote: the following focus areas were not reviewed because of an error: "
                f"{', '.join(failed_focus_areas)}."
            )
        return feedback

    async def _merge_reviews(
        self, reviews: list[tuple[str, RequirementsReviewFeedback]], usage_limits: UsageLimits
    ) -> RequirementsReviewFeedback:
        labelled_reviews = [
            f"Review focused on '{focus_area}':\n```{review.suggested_improvements}```"
            for focus_area, review in reviews
        ]
        result = await self.merge_agent.run("\n\n".join(labelled_reviews), usage_limits=usage_limits)
        logger.info("Merged %d focused review(s) into one feedback", len(reviews))
        return result.output


agent = RequirementsReviewAgent()
app = agent.a2a_server

if __name__ == "__main__":
    agent.start_as_server()
