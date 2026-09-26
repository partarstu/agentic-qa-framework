# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import json
import time
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
    ModelRequestParameters,
    ModelSettings,
    StreamedResponse,
)
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ThinkingLevel, merge_model_settings
from pydantic_ai.usage import RunUsage

import config
from common import utils
from common.model_factory import build_claude_5_settings, build_model, is_claude_5
from common.models import JsonSerializableModel
from common.prompt_injection.guard import GuardPrompt, PromptGuardFactory
from common.token_usage import operation_meter

LOG_SEPARATOR = "-" * 80

logger = utils.get_logger("llm_wrapper")


class CustomLlmWrapper(WrapperModel):
    def __init__(
        self,
        model_name: str,
        thinking_level: ThinkingLevel | None = None,
        max_output_tokens: int | None = None,
        operation_name: str | None = None,
    ):
        super().__init__(build_model(model_name, thinking_level))
        self.wrapped_model_name: str = model_name
        self.latest_instructions: str | None = None
        self.thinking_level = thinking_level
        self.max_output_tokens = max_output_tokens if max_output_tokens is not None else config.MAX_OUTPUT_TOKENS
        # Name under which this model's calls are metered per operation: "main" for the
        # agent created by AgentBase, the sub-agent's own name otherwise.
        self.operation_name = operation_name or "main"

    @classmethod
    def create_agent(
        cls,
        model_name: str,
        output_type: type,
        instructions: str | None = None,
        system_prompt: str | None = None,
        name: str = "",
        thinking_level: ThinkingLevel | None = None,
        tools: Sequence = (),
        toolsets: Sequence = (),
        deps_type: type | None = None,
        retries: int = 3,
        output_retries: int = 3,
        max_output_tokens: int | None = None,
        operation_name: str | None = None,
    ) -> Agent:
        """Creates a pydantic_ai Agent backed by a CustomLlmWrapper model."""
        return Agent(
            model=cls(
                model_name=model_name,
                thinking_level=thinking_level,
                max_output_tokens=max_output_tokens,
                operation_name=operation_name or name or "main",
            ),
            output_type=output_type,
            instructions=instructions,
            system_prompt=system_prompt or (),
            name=name,
            tools=list(tools),
            toolsets=list(toolsets),
            deps_type=deps_type,
            retries={"tools": retries, "output": output_retries},
            # pydantic-ai 2 defaults to "graceful", which also runs the tools requested alongside the final output.
            end_strategy="early",
        )

    def _get_model_settings(self, provided_settings: ModelSettings | None) -> ModelSettings:
        """Return the defaults overridden key by key by the provided settings, which carry the model's own."""
        return merge_model_settings(self._default_model_settings(), provided_settings) or ModelSettings()

    def _default_model_settings(self) -> ModelSettings:
        if is_claude_5(self.wrapped_model_name):
            return build_claude_5_settings(self.thinking_level, self.max_output_tokens, self.wrapped_model_name)
        settings = ModelSettings(top_p=config.TOP_P, temperature=config.TEMPERATURE)
        if self.thinking_level is not None:
            settings["thinking"] = self.thinking_level
        if self.max_output_tokens is not None:
            settings["max_tokens"] = self.max_output_tokens
        return settings

    def _record_usage(self, response: ModelResponse) -> None:
        """Add one completed LLM call's usage to the per-task operation meter.

        A model outside an agent task (e.g. the orchestrator's routing calls) has no meter and is
        not metered as an operation.
        """
        meter = operation_meter.get()
        if meter is None:
            return
        tool_calls = sum(1 for part in response.parts if isinstance(part, ToolCallPart))
        usage = response.usage
        meter.add(
            self.operation_name,
            self.wrapped_model_name,
            RunUsage(
                requests=1,
                tool_calls=tool_calls,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=usage.cache_read_tokens,
                cache_write_tokens=usage.cache_write_tokens,
            ),
        )

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        if config.PROMPT_INJECTION_CHECK_ENABLED:
            self._validate_for_prompt_injection(messages)

        if messages and isinstance(messages[-1], ModelRequest):
            self._log_model_request(messages[-1])

        actual_settings = self._get_model_settings(model_settings)
        start_time = time.monotonic()
        response = await self.wrapped.request(messages, actual_settings, model_request_parameters)
        duration = time.monotonic() - start_time
        logger.info(f"LLM request to '{self.wrapped_model_name}' completed in {duration:.3f}s")
        self._record_usage(response)
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
        start_time = time.monotonic()
        async with self.wrapped.request_stream(
            messages, actual_settings, model_request_parameters, run_context
        ) as response_stream:
            yield response_stream
        duration = time.monotonic() - start_time
        logger.info(f"LLM streaming request to '{self.wrapped_model_name}' completed in {duration:.3f}s")
        # Streaming usage is only final once the stream is closed, which the context exit above ensures.
        self._record_usage(response_stream.response)

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
                        prompt=prompt_content,
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
            return (
                f"<BinaryContent: media_type={obj.media_type}, identifier={obj.identifier}, size={len(obj.data)} bytes>"
            )
        if isinstance(obj, bytes):
            return f"<bytes: {len(obj)}>"
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

    @staticmethod
    def _serialize_content(content) -> str:
        """Serialize content to JSON, handling JsonSerializableModel and BinaryContent instances."""
        return json.dumps(content, indent=2, default=CustomLlmWrapper._json_serializer)

    def _log_model_request(self, message):
        if message.instructions and self.latest_instructions != message.instructions:
            self.latest_instructions = message.instructions
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logger.debug(
                f"[{timestamp}] Agent is using following instructions: "
                f"\n{LOG_SEPARATOR}\n{self.latest_instructions}\n{LOG_SEPARATOR}"
            )
        for part in message.parts:
            if isinstance(part, ToolReturnPart):
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                payload = self._serialize_content(part.content)
                logger.debug(
                    f"[{timestamp}] Agent is responding with the execution result of tool: "
                    f"'{part.tool_name}' with result: \n{LOG_SEPARATOR}\n{payload}\n{LOG_SEPARATOR}"
                )
            elif isinstance(part, UserPromptPart):
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if isinstance(part.content, str):
                    content_to_log = part.content
                elif isinstance(part.content, Sequence):
                    contents = []
                    for c in part.content:
                        if isinstance(c, str):
                            contents.append(c)
                        else:
                            contents.append(f"<{type(c).__name__}>")
                    content_to_log = "\n".join(contents)
                else:
                    content_to_log = f"<{type(part.content).__name__}>"
                logger.debug(
                    f"[{timestamp}] Agent is prompting the model with user input: "
                    f"\n{LOG_SEPARATOR}\n{content_to_log}\n{LOG_SEPARATOR}"
                )
            elif isinstance(part, SystemPromptPart):
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                logger.debug(
                    f"[{timestamp}] Agent is using system prompt: \n{LOG_SEPARATOR}\n{part.content}\n{LOG_SEPARATOR}"
                )
            elif isinstance(part, RetryPromptPart):
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                logger.debug(f"[{timestamp}] Agent is retrying prompting the model, the root cause: {part.content}")

    @staticmethod
    def _log_model_response(message):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        separator = "-" * 80
        for part in message.parts:
            if isinstance(part, ToolCallPart):
                logger.debug(
                    f"[{timestamp}] Model is calling the tool: '{part.tool_name}' with arguments: "
                    f"\n{separator}\n{json.dumps(part.args, indent=2)}\n{separator}"
                )
            elif isinstance(part, ThinkingPart) and part.content:
                logger.debug(
                    f"[{timestamp}] Model is thinking the following:\n{separator}\n{part.content}\n{separator}"
                )
            elif isinstance(part, TextPart) and part.content:
                logger.debug(
                    f"[{timestamp}] Model is responding with the plain text:\n{separator}\n{part.content}\n{separator}"
                )
