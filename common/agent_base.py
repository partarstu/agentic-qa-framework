# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

import base64
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import Type, List, Sequence, Optional
from urllib.parse import urlparse

import uvicorn
from a2a.server.apps import A2AFastAPIApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCard, AgentCapabilities, Message, FilePart, FileWithBytes
from a2a.utils import get_message_text, new_agent_text_message
from fastapi import FastAPI
from pydantic import BaseModel
from pydantic_ai import Agent, Tool
from pydantic_ai.agent import AgentRunResult
from pydantic_ai.mcp import MCPServerSSE
from pydantic_ai.messages import BinaryContent, UserContent
from pydantic_ai.models.google import GoogleModelSettings
from pydantic_ai.models.groq import GroqModelSettings
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import AgentDepsT, ToolFuncEither
from pydantic_ai.usage import UsageLimits

import config
from common import utils
from common.agent_executor import DefaultAgentExecutor
from common.custom_llm_wrapper import CustomLlmWrapper
from common.models import JsonSerializableModel
from common.services.vector_db_service import VectorDbService

MAX_RETRIES = 3
REGISTRATION_PATH = f"{config.ORCHESTRATOR_URL}/register"
MCP_SERVER_ATTACHMENTS_FOLDER_PATH = config.MCP_SERVER_ATTACHMENTS_FOLDER_PATH
ATTACHMENTS_DESTINATION_FOLDER_PATH = config.ATTACHMENTS_DESTINATION_FOLDER_PATH

logger = utils.get_logger("agent_base")


class AgentBase(ABC):
    def __init__(
            self,
            agent_name: str,
            base_url: str,
            protocol: str,
            port: int,
            external_port: int,
            model_name: str,
            output_type: Type[BaseModel],
            instructions: str,
            mcp_servers: List[MCPServerSSE],
            model_settings: ModelSettings = None,
            deps_type: Type[BaseModel] = None,
            description: str = "",
            tools: Sequence[Tool[AgentDepsT] | ToolFuncEither[AgentDepsT, ...]] = (),
            vector_db_collection_name: Optional[str] = None
    ):
        self.agent_name = agent_name
        self.base_url = base_url
        self.port = port
        self.external_port = external_port
        self.protocol = protocol
        self.url = f"{self.base_url}:{self.external_port}"
        self.model_name = model_name
        self.output_type = output_type
        self.instructions = instructions
        self.deps_type = deps_type
        self.description = description
        self.model_settings = model_settings if model_settings else self.get_default_model_settings(model_name)
        self.mcp_servers = mcp_servers or []
        self.tools = tools
        self.agent = self._create_agent()
        self.a2a_server = self._get_server()

        self.vector_db_service = None
        if vector_db_collection_name:
            self.vector_db_service = VectorDbService(vector_db_collection_name)
        self.latest_received_message: Message | None = None

    @abstractmethod
    def get_thinking_budget(self) -> int:
        pass

    @abstractmethod
    def get_max_requests_per_task(self) -> int:
        pass

    def get_default_model_settings(self, model_name: str) -> ModelSettings:
        if model_name.startswith("google"):
            return GoogleModelSettings(top_p=config.TOP_P, temperature=config.TEMPERATURE,
                                       google_thinking_config={'include_thoughts': True,
                                                               'thinking_budget': self.get_thinking_budget()})
        elif model_name.startswith("groq"):
            return GroqModelSettings(top_p=config.TOP_P, temperature=config.TEMPERATURE)
        else:
            return ModelSettings(top_p=config.TOP_P, temperature=config.TEMPERATURE)

    def _create_agent(self) -> Agent:
        logger.info(f"""Creating agent '{self.agent_name}' with the following configuration:
        - Model: {self.model_name}
        - Output Type: {self.output_type.__name__}
        - Model Settings: {self.model_settings}
        - MCP Servers: {[server.url for server in self.mcp_servers]}
        - Tools: {[tool.__name__ for tool in self.tools]}""")

        return Agent(
            model=CustomLlmWrapper(wrapped=self.model_name),
            deps_type=self.deps_type,
            output_type=self.output_type,
            instructions=self.instructions,
            name=self.agent_name,
            model_settings=self.model_settings,
            toolsets=self.mcp_servers,
            tools=self.tools,
            retries=MAX_RETRIES,
            output_retries=MAX_RETRIES
        )

    async def _get_agent_execution_result(self, received_request: List[UserContent]) -> AgentRunResult:
        usage_limits = UsageLimits(tool_calls_limit=self.get_max_requests_per_task())
        async with self.agent:
            return await self.agent.run(received_request, usage_limits=usage_limits)

    async def run(self, received_message: Message) -> Message:
        self.latest_received_message = received_message
        received_request = self._get_all_received_contents(received_message)
        logger.info("Got a task to execute, starting execution.")
        try:
            result = await self._get_agent_execution_result(received_request)
            logger.info("Completed execution of the task.")
            return self._get_text_message_from_results(result)
        except Exception as e:
            logger.exception(f"Error during agent execution: {e}")
            raise

    # noinspection PyUnusedLocal
    @asynccontextmanager
    async def _lifespan(self, app: FastAPI):
        logger.info(f"{self.agent_name} started.")
        logger.info(f"Using following MCP server URLs: {[server.url for server in self.mcp_servers]}")

        yield

        logger.info("Shutting down.")

    @staticmethod
    def _get_media_file_content(file_path: str) -> BinaryContent:
        """Fetches the content of a media file from the local file system or the cloud storage.

            Args:
                file_path: The path to the media file.

            Returns:
                A BinaryContent object containing the file's data.
            """
        if config.USE_GOOGLE_CLOUD_STORAGE:
            return utils.fetch_media_file_content_from_gcs(file_path, config.GOOGLE_CLOUD_STORAGE_BUCKET_NAME,
                                                           config.JIRA_ATTACHMENTS_CLOUD_STORAGE_FOLDER)
        else:
            return utils.fetch_media_file_content_from_local(file_path, ATTACHMENTS_DESTINATION_FOLDER_PATH)

    def _get_server(self) -> FastAPI:
        request_handler = DefaultRequestHandler(
            agent_executor=DefaultAgentExecutor(self),
            task_store=InMemoryTaskStore(),
        )
        agent_card = AgentCard(
            name=self.agent_name,
            description=self.description,
            url=self.url,
            version='1.0.0',
            default_input_modes=['text'],
            default_output_modes=['text', 'image'],
            capabilities=AgentCapabilities(streaming=False),
            skills=[],
        )
        server = A2AFastAPIApplication(
            agent_card=agent_card, http_handler=request_handler
        )
        a2a_app: FastAPI = server.build()
        original_lifespan = a2a_app.router.lifespan_context

        @asynccontextmanager
        async def combined_lifespan(app: FastAPI):
            # `self` is captured from the outer scope
            if original_lifespan:
                async with original_lifespan(app):
                    async with self._lifespan(app):
                        yield
            else:
                async with self._lifespan(app):
                    yield

        a2a_app.router.lifespan_context = combined_lifespan
        return a2a_app

    def start_as_server(self):
        parsed_url = urlparse(self.base_url)
        host = parsed_url.hostname
        uvicorn.run(self.a2a_server, host=host, port=self.port)

    @staticmethod
    def _get_all_received_contents(received_message) -> List[UserContent]:
        text_content: str = get_message_text(received_message)
        files_content: List[BinaryContent] = []
        for part in received_message.parts:
            if isinstance(part, FilePart):
                file = part.file
                if isinstance(file, FileWithBytes):
                    mime_type = file.mime_type
                    content = base64.b64decode(file.bytes)
                    files_content.append(BinaryContent(data=content, media_type=mime_type))
        all_contents: List[UserContent] = [text_content, *files_content]
        return all_contents

    @staticmethod
    def _get_text_message_from_results(result: AgentRunResult, context_id: str = None, task_id: str = None) -> Message:
        output = result.output
        if isinstance(output, JsonSerializableModel):
            return new_agent_text_message(text=output.model_dump_json(), context_id=context_id, task_id=task_id)
        if isinstance(output, dict):
            text_parts = []
            for part in output.get('parts', []):
                if part.get('type', "") == 'text':
                    text_parts.append(part)
            return new_agent_text_message(text="\n".join(text_parts), context_id=context_id, task_id=task_id)
        else:
            return new_agent_text_message(text=str(output), context_id=context_id, task_id=task_id)
