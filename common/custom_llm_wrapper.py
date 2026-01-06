import json
from datetime import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import List, Sequence, Optional

from fastapi import HTTPException
from pydantic_ai.messages import ModelRequest, ToolReturnPart, UserPromptPart, ModelMessage, ModelResponse, \
    ToolCallPart, \
    ThinkingPart, TextPart, SystemPromptPart, RetryPromptPart, BinaryContent
from pydantic_ai.models import (
    Model,
    KnownModelName,
    ModelSettings,
    ModelRequestParameters,
    StreamedResponse,
)
from pydantic_ai.models.wrapper import WrapperModel

import config
from common import utils
from common.models import JsonSerializableModel
from common.prompt_injection.guard import GuardPrompt, PromptGuardFactory

LOG_SEPARATTOR = '-' * 80

logger = utils.get_logger("llm_wrapper")


class CustomLlmWrapper(WrapperModel):
    def __init__(self, wrapped: Model | KnownModelName):
        super().__init__(wrapped)
        self.latest_instructions: str | None = None

    async def request(self, messages: List[ModelMessage], model_settings: ModelSettings | None,
                      model_request_parameters: ModelRequestParameters,
                      ) -> ModelResponse:
        if config.PROMPT_INJECTION_CHECK_ENABLED:
            self._validate_for_prompt_injection(messages)

        if messages and isinstance(messages[-1], ModelRequest):
            self._log_model_request(messages[-1])

        response = await self.wrapped.request(
            messages, model_settings, model_request_parameters
        )
        self._log_model_response(response)
        return response

    @asynccontextmanager
    async def request_stream(
            self,
            messages: List[ModelMessage],
            model_settings: ModelSettings | None,
            model_request_parameters: ModelRequestParameters,
            run_context,
    ) -> AsyncIterator[StreamedResponse]:
        if config.PROMPT_INJECTION_CHECK_ENABLED:
            self._validate_for_prompt_injection(messages)

        async with self.wrapped.request_stream(
                messages, model_settings, model_request_parameters, run_context
        ) as response_stream:
            yield response_stream

    @staticmethod
    def _get_prompt_from_messages(messages: List[ModelMessage]) -> Optional[GuardPrompt]:
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
