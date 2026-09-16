# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

from typing import TYPE_CHECKING

from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.settings import ThinkingLevel
from pydantic_ai.tools import RunContext

import config
from agents.requirements_review.prompt import (
    RequirementsReviewRetrievalInstruction,
    RequirementsReviewSystemPrompt,
    RequirementsReviewWithAttachmentsPrompt,
)
from common import utils
from common.agent_base import AgentBase
from common.custom_llm_wrapper import CustomLlmWrapper
from common.models import AgentSkillDeclaration, JiraUserStory, RequirementsReviewFeedback
from common.services.document_retrieval import (
    RetrievalScope,
    assemble_retrieved_parts,
    retrieve_documents,
)
from common.services.jira_attachments import download_issue_attachments
from common.services.jira_mcp import build_jira_mcp_server_toolset
from common.services.vector_db_service import VectorDbService

if TYPE_CHECKING:
    from pydantic_ai.messages import BinaryContent

logger = utils.get_logger("reviewer_agent")

_SCOPE_PARAM_LENGTH_CAP = 200


def _capped(value: str | None) -> str | None:
    """Defensive length cap on the tool's free-text scope parameters."""
    if value is None:
        return None
    return value[:_SCOPE_PARAM_LENGTH_CAP]


class RequirementsReviewAgent(AgentBase):
    def __init__(self):
        retrieval_enabled = bool(config.QdrantConfig.EMBEDDING_SERVICE_URL)
        self.retrieval_enabled = retrieval_enabled
        if retrieval_enabled:
            self.documents_db = VectorDbService(config.DocumentRagConfig.DOCUMENTS_COLLECTION_NAME)
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
            mcp_toolset_factories=[build_jira_mcp_server_toolset],
            deps_type=JiraUserStory,
            skill=AgentSkillDeclaration(
                id=config.RequirementsReviewAgentConfig.SKILL_ID,
                name=config.RequirementsReviewAgentConfig.SKILL_NAME,
                description=config.RequirementsReviewAgentConfig.SKILL_DESCRIPTION,
            ),
            tools=[self._review_with_reference_documentation, self.add_jira_comment],
        )

    def get_thinking_level(self) -> ThinkingLevel:
        return config.RequirementsReviewAgentConfig.THINKING_LEVEL

    def get_max_requests_per_task(self) -> int:
        return config.RequirementsReviewAgentConfig.MAX_REQUESTS_PER_TASK

    async def _review_with_reference_documentation(
        self,
        ctx: RunContext[JiraUserStory],
        jira_issue_content: str,
        retrieval_query: str = "",
        space_key: str | None = None,
        page_id: str | None = None,
        document_name_pattern: str | None = None,
    ) -> RequirementsReviewFeedback:
        """
        Reviews a Jira issue, taking into account all its attachments and, when a
        retrieval query is given, the matching Confluence reference documentation.

        Args:
            jira_issue_content: The complete content of the Jira issue.
            retrieval_query: A concise documentation search query (key topics, feature
                names, domain terms). Required when reference documentation is enabled.
            space_key: Optional Confluence space key scope.
            page_id: Optional Confluence page ID scope.
            document_name_pattern: Optional regex pattern on document names.

        Returns:
            Requirements review feedback with improvement suggestions.
        """
        attachments_content = download_issue_attachments(ctx.deps.key)
        user_message_parts: list[str | BinaryContent] = [f"Jira Issue content:\n```{jira_issue_content}```"]
        if attachments_content:
            for filename, binary_content in attachments_content.items():
                user_message_parts.append(f"Attachment: {filename}")
                user_message_parts.append(binary_content)

        if not self.retrieval_enabled:
            logger.info("Starting requirements review with %d attachments", len(attachments_content))
            result = await self.review_agent.run(user_message_parts)
            feedback: RequirementsReviewFeedback = result.output
            logger.info("Generated improvement suggestions as a feedback")
            return feedback

        if not retrieval_query or not retrieval_query.strip():
            # No fallback to the issue content: a missing query is an explicit tool error.
            raise ModelRetry(
                "A non-blank retrieval_query is required: distil key topics, feature names "
                "and domain terms from the issue and pass them as retrieval_query."
            )

        scope = RetrievalScope(
            space_key=_capped(space_key),
            page_id=_capped(page_id),
            document_name_pattern=_capped(document_name_pattern),
        )
        pages = await retrieve_documents(self.documents_db, retrieval_query, scope)
        documentation_parts = assemble_retrieved_parts(pages)
        # Reference documentation comes after the issue content and the Jira attachments.
        user_message_parts.extend(documentation_parts)
        logger.info(
            "Starting requirements review with %d attachment(s) and %d retrieved documentation page(s)",
            len(attachments_content),
            len(pages),
        )
        result = await self.review_agent.run(user_message_parts)
        feedback = result.output
        logger.info("Generated improvement suggestions as a feedback")
        return feedback


agent = RequirementsReviewAgent()
app = agent.a2a_server

if __name__ == "__main__":
    agent.start_as_server()
