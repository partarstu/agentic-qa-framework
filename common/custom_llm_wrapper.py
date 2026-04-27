import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import HTTPException
from pydantic_ai import Agent
from pydantic_ai.messages import (
    BinaryContent,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    SystemPromptPart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import (
    KnownModelName,
    Model,
    ModelRequestParameters,
    ModelSettings,
    StreamedResponse,
)
from pydantic_ai.models.gemini import GeminiModelSettings
from pydantic_ai.models.groq import GroqModelSettings
from pydantic_ai.models.wrapper import WrapperModel

import config
from common import utils
from common.models import JsonSerializableModel
from common.prompt_injection.guard import GuardPrompt, PromptGuardFactory

LOG_SEPARATTOR = '-' * 80

logger = utils.get_logger("llm_wrapper")


class CustomLlmWrapper(WrapperModel):
    def __init__(self, wrapped: Model | KnownModelName, thinking_level: str | None = None):
        super().__init__(wrapped)
        self.latest_instructions: str | None = None
        self.thinking_level = thinking_level or "MINIMAL"

    @classmethod
    def create_agent(
        cls,
        model_name: Model | KnownModelName,
        output_type: type,
        instructions: str | None = None,
        system_prompt: str | None = None,
        name: str = "",
        thinking_level: str | None = None,
        tools: Sequence = (),
        toolsets: Sequence = (),
        deps_type: type | None = None,
        retries: int = 3,
        output_retries: int = 3,
    ) -> Agent:
        """Creates a pydantic_ai Agent backed by a CustomLlmWrapper model."""
        return Agent(
            model=cls(wrapped=model_name, thinking_level=thinking_level),
            output_type=output_type,
            instructions=instructions,
            system_prompt=system_prompt or (),
            name=name,
            tools=list(tools),
            toolsets=list(toolsets),
            deps_type=deps_type,
            retries=retries,
            output_retries=output_retries,
        )

    def _get_model_settings(self, provided_settings: ModelSettings | None) -> ModelSettings:
        if provided_settings is not None:
            return provided_settings

        model_name = self.wrapped.name() if hasattr(self.wrapped, "name") else ""

        if model_name.startswith("google"):
            gemini_thinking_config = None
            if self.thinking_level != "MINIMAL":
                gemini_thinking_config = {'include_thoughts': True, 'thinking_level': self.thinking_level}
            return GeminiModelSettings(
                top_p=config.TOP_P,
                temperature=config.TEMPERATURE,
                gemini_thinking_config=gemini_thinking_config)
        elif model_name.startswith("groq"):
            return GroqModelSettings(top_p=config.TOP_P, temperature=config.TEMPERATURE)
        else:
            return ModelSettings(top_p=config.TOP_P, temperature=config.TEMPERATURE)

    async def request(self, messages: list[ModelMessage], model_settings: ModelSettings | None,
                      model_request_parameters: ModelRequestParameters,
                      ) -> ModelResponse:
        if config.PROMPT_INJECTION_CHECK_ENABLED:
            self._validate_for_prompt_injection(messages)

        if messages and isinstance(messages[-1], ModelRequest):
            self._log_model_request(messages[-1])

        actual_settings = self._get_model_settings(model_settings)
        response = await self.wrapped.request(
            messages, actual_settings, model_request_parameters
        )
        self._log_model_response(response)
        return response

    @asynccontextmanager
    async def request_stream(
            self,
            messages: list[ModelMessage],
            model_settings: ModelSettings | None,
            model_request_parameters: ModelRequestParameters,
            run_context,
    ) -> AsyncIterator[StreamedResponse]:
        if config.PROMPT_INJECTION_CHECK_ENABLED:
            self._validate_for_prompt_injection(messages)

        actual_settings = self._get_model_settings(model_settings)
        async with self.wrapped.request_stream(
                messages, actual_settings, model_request_parameters, run_context
        ) as response_stream:
            yield response_stream

    @staticmethod
    def _get_prompt_from_messages(messages: list[ModelMessage]) -> GuardPrompt | None:
        for message in reversed(messages):
            if not isinstance(message, ModelRequest):
                continue
            for part in message.parts:
                if isinstance(part, ToolReturnPart):
                    if isinstance(part.content, str):
                        prompt_content = part.content
                    else:
                        prompt_content = CustomLlmWrapper._serialize_content(part.content)
                    return GuardPrompt(
                        prompt_description=f"Result of the execution of the tool '{part.tool_name}' : ",
                        prompt=prompt_content
                    )
                if isinstance(part, UserPromptPart):
                    prompt_content = ""
                    if isinstance(part.content, str):
                        prompt_content = part.content
                    elif isinstance(part.content, Sequence):
                        prompt_content = "".join([c for c in part.content if isinstance(c, str)])
                    return GuardPrompt(prompt_description="", prompt=prompt_content)
        return None

    def _validate_for_prompt_injection(self, messages):
        guard_prompt = self._get_prompt_from_messages(messages)
        prompt_guard = PromptGuardFactory.get_prompt_guard(config.PROMPT_GUARD_PROVIDER)
        if guard_prompt and prompt_guard.is_injection(guard_prompt, config.PROMPT_INJECTION_MIN_SCORE):
            logger.error(f"Prompt injection attack detected for the following prompt: \n{guard_prompt.prompt}")
            raise HTTPException(status_code=400, detail="Prompt injection attack detected.")

    @staticmethod
    def _json_serializer(obj):
        """Custom JSON serializer for objects not handled by default json encoder."""
        if isinstance(obj, JsonSerializableModel):
            return obj.model_dump()
        if isinstance(obj, BinaryContent):
            return f"<BinaryContent: media_type={obj.media_type}, identifier={obj.identifier}, size={len(obj.data)} bytes>"
        if isinstance(obj, bytes):
            return f"<bytes: {len(obj)}>"
        if hasattr(obj, 'model_dump'):
            return obj.model_dump()
        raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

    @staticmethod
    def _serialize_content(content) -> str:
        """Serialize content to JSON, handling JsonSerializableModel and BinaryContent instances."""
        return json.dumps(content, indent=2, default=CustomLlmWrapper._json_serializer)

    def _log_model_request(self, message):
        if message.instructions and self.latest_instructions != message.instructions:
            self.latest_instructions = message.instructions
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            logger.debug(f"[{timestamp}] Agent is using following instructions: "
                         f"\n{LOG_SEPARATTOR}\n{self.latest_instructions}\n{LOG_SEPARATTOR}")
        for part in message.parts:
            if isinstance(part, ToolReturnPart):
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                payload = self._serialize_content(part.content)
                logger.debug(f"[{timestamp}] Agent is responding with the execution result of tool: "
                             f"'{part.tool_name}' with result: \n{LOG_SEPARATTOR}\n{payload}\n{LOG_SEPARATTOR}")
            elif isinstance(part, UserPromptPart):
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                if isinstance(part.content, str):
                    content_to_log = part.content
                elif isinstance(part.content, Sequence):
                    contents = []
                    for c in part.content:
                        if isinstance(c, str):
                            contents.append(c)
                        else:
                            contents.append(f'<{type(c).__name__}>')
                    content_to_log = "\n".join(contents)
                else:
                    content_to_log = f'<{type(part.content).__name__}>'
                logger.debug(f"[{timestamp}] Agent is prompting the model with user input: "
                             f"\n{LOG_SEPARATTOR}\n{content_to_log}\n{LOG_SEPARATTOR}")
            elif isinstance(part, SystemPromptPart):
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                logger.debug(f"[{timestamp}] Agent is using system prompt: \n{LOG_SEPARATTOR}\n{part.content}\n{LOG_SEPARATTOR}")
            elif isinstance(part, RetryPromptPart):
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                logger.debug(f"[{timestamp}] Agent is retrying prompting the model, the root "
                             f"cause: {part.content}")

    @staticmethod
    def _log_model_response(message):
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        separator = '-' * 80
        for part in message.parts:
            if isinstance(part, ToolCallPart):
                logger.debug(f"[{timestamp}] Model is calling the tool: '{part.tool_name}' with arguments: "
                             f"\n{separator}\n{json.dumps(part.args, indent=2)}\n{separator}")
            elif isinstance(part, ThinkingPart) and part.content:
                logger.debug(
                    f"[{timestamp}] Model is thinking the "
                    f"following:\n{separator}\n{part.content}\n{separator}")
            elif isinstance(part, TextPart) and part.content:
                logger.debug(f"[{timestamp}] Model is responding with the plain "
                             f"text:\n{separator}\n{part.content}\n{separator}")
