# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.messages import BinaryContent
from pydantic_ai.settings import ThinkingLevel

import config
from agents.requirements_review.prompt import (
    RequirementsReviewRetrievalInstruction,
    RequirementsReviewSystemPrompt,
    RequirementsReviewWithAttachmentsPrompt,
)
from common import utils
from common.agent_base import AgentBase
from common.custom_llm_wrapper import CustomLlmWrapper
from common.models import AgentSkillDeclaration, RequirementsReviewFeedback
from common.services.atlassian_mcp import build_atlassian_mcp_server_toolset
from common.services.document_retrieval import (
    RetrievalScope,
    assemble_retrieved_parts,
    retrieve_documents,
)
from common.services.jira_attachments import download_issue_attachments
from common.services.vector_db_service import VectorDbService

logger = utils.get_logger("reviewer_agent")

# The Jira tools this agent actually uses (WS11 per-agent tool filtering): it reads the
# issue through the MCP server and posts the review feedback as a comment.
_JIRA_TOOL_ALLOWLIST = ("jira_get_issue", "jira_add_comment")

_SCOPE_PARAM_LENGTH_CAP = 200


def _capped(value: str | None) -> str | None:
    """Defensive length cap on the tool's free-text scope parameters."""
    if value is None:
        return None
    return value[:_SCOPE_PARAM_LENGTH_CAP]


def _get_issue_message_parts(issue_key: str, jira_issue_content: str) -> list[str | BinaryContent]:
    """The issue content followed by every supported attachment of the issue."""
    attachments_content = download_issue_attachments(issue_key)
    user_message_parts: list[str | BinaryContent] = [f"Jira Issue content:\n```{jira_issue_content}```"]
    for filename, binary_content in attachments_content.items():
        user_message_parts.append(f"Attachment: {filename}")
        user_message_parts.append(binary_content)
    logger.info("Reviewing issue %s with %d attachment(s)", issue_key, len(attachments_content))
    return user_message_parts


class RequirementsReviewAgent(AgentBase):
    def __init__(self):
        retrieval_enabled = bool(config.QdrantConfig.EMBEDDING_SERVICE_URL)
        self.retrieval_enabled = retrieval_enabled
        if retrieval_enabled:
            # The metadata collection makes retrieval refuse to query vectors of a different model (WS6).
            self.documents_db = VectorDbService(
                config.DocumentRagConfig.DOCUMENTS_COLLECTION_NAME,
                metadata_collection_name=config.QdrantConfig.METADATA_COLLECTION_NAME,
            )
        else:
            logger.info(
                "Document retrieval is disabled: EMBEDDING_SERVICE_URL is not configured. "
                "The review proceeds on the issue and its attachments only."
            )
            self.documents_db = None

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
        self, jira_issue_key: str, jira_issue_content: str
    ) -> RequirementsReviewFeedback:
        """
        Reviews a Jira issue, taking into account all its attachments.

        Args:
            jira_issue_key: The key of the Jira issue (e.g. PROJ-123), used to download its attachments.
            jira_issue_content: The complete content of the Jira issue.

        Returns:
            Requirements review feedback with improvement suggestions.
        """
        user_message_parts = _get_issue_message_parts(jira_issue_key, jira_issue_content)
        return await self._run_review(user_message_parts)

    async def _review_with_reference_documentation(
        self,
        jira_issue_key: str,
        jira_issue_content: str,
        retrieval_query: str,
        space_key: str | None = None,
        page_id: str | None = None,
        document_name_pattern: str | None = None,
    ) -> RequirementsReviewFeedback:
        """
        Reviews a Jira issue, taking into account all its attachments and the Confluence
        reference documentation matching the retrieval query.

        Args:
            jira_issue_key: The key of the Jira issue (e.g. PROJ-123), used to download its attachments.
            jira_issue_content: The complete content of the Jira issue.
            retrieval_query: A concise documentation search query (key topics, feature
                names, domain terms).
            space_key: Optional Confluence space key scope.
            page_id: Optional Confluence page ID scope.
            document_name_pattern: Optional regex pattern on document names.

        Returns:
            Requirements review feedback with improvement suggestions.
        """
        if not retrieval_query.strip():
            # No fallback to the issue content: a missing query is an explicit tool error.
            raise ModelRetry(
                "A non-blank retrieval_query is required: distil key topics, feature names "
                "and domain terms from the issue and pass them as retrieval_query."
            )

        user_message_parts = _get_issue_message_parts(jira_issue_key, jira_issue_content)
        scope = RetrievalScope(
            space_key=_capped(space_key),
            page_id=_capped(page_id),
            document_name_pattern=_capped(document_name_pattern),
        )
        pages = await retrieve_documents(self.documents_db, retrieval_query, scope)
        # Reference documentation comes after the issue content and the Jira attachments.
        user_message_parts.extend(assemble_retrieved_parts(pages))
        logger.info("Retrieved %d reference documentation page(s) for issue %s", len(pages), jira_issue_key)
        return await self._run_review(user_message_parts)

    async def _run_review(self, user_message_parts: list[str | BinaryContent]) -> RequirementsReviewFeedback:
        result = await self.review_agent.run(user_message_parts)
        logger.info("Generated improvement suggestions as a feedback")
        return result.output


agent = RequirementsReviewAgent()
app = agent.a2a_server

if __name__ == "__main__":
    agent.start_as_server()
