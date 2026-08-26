# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Per-request Jira MCP sessions with self-healing.

Every agent run gets its own MCP session instead of sharing one process-wide connection, so a
session that goes stale between requests cannot break the next one. Within a run, a recoverable
transport failure is repaired by re-establishing the session and retrying the failed operation
exactly once.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import anyio
import httpx
from mcp.shared.exceptions import McpError
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.mcp import MCPServerSSE
from pydantic_ai.tools import AgentDepsT, RunContext
from pydantic_ai.toolsets import AbstractToolset, ToolsetTool, WrapperToolset

import config
from common import utils

logger = utils.get_logger("jira_mcp")

# Failures which mean the session itself is gone or unusable, not that the request was wrong.
_RECOVERABLE_EXCEPTION_TYPES = (
    anyio.ClosedResourceError,
    anyio.BrokenResourceError,
    anyio.EndOfStream,
    TimeoutError,
    EOFError,
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
)


# Verbs which mark a tool as a pure read when the MCP server declares no tool annotations.
_READ_ONLY_TOOL_NAME_VERBS = ("get", "search", "list", "read", "fetch", "download")


def _mentions_timeout(message: str) -> bool:
    lowered = message.lower()
    return "timed out" in lowered or "timeout" in lowered


def _is_recoverable(exc: BaseException) -> bool:
    """Whether re-establishing the MCP session can plausibly fix the given failure."""
    if isinstance(exc, ExceptionGroup):
        return any(_is_recoverable(member) for member in exc.exceptions)
    if isinstance(exc, _RECOVERABLE_EXCEPTION_TYPES):
        return True
    if isinstance(exc, McpError):
        return _mentions_timeout(exc.error.message)
    if isinstance(exc, ModelRetry):
        return _mentions_timeout(exc.message)
    return False


def _is_safe_to_repeat(tool: ToolsetTool[Any]) -> bool:
    """Whether re-issuing the tool after a reconnect cannot duplicate a server-side change.

    A broken transport says nothing about whether Jira already applied the write, so repeating the
    call could create a second issue or a second comment. Only tools the server annotates as
    read-only or idempotent are repeated; when it annotates nothing, the tool name has to start
    with a read verb.
    """
    annotations = (tool.tool_def.metadata or {}).get("annotations")
    if annotations:
        return bool(annotations.get("readOnlyHint") or annotations.get("idempotentHint"))
    return tool.tool_def.name.removeprefix("jira_").startswith(_READ_ONLY_TOOL_NAME_VERBS)


@dataclass
class SelfHealingJiraToolset(WrapperToolset[AgentDepsT]):
    """A Jira MCP toolset which re-establishes its session once on a recoverable failure.

    Re-entering the wrapped ``MCPServerSSE`` re-runs the full handshake, so the next operation sees
    an initialised session with the negotiated log level. The budget is one reconnect per
    operation; anything that is not recoverable propagates untouched. The failed operation itself
    is repeated only when repeating it cannot duplicate a Jira write.
    """

    wrapped: MCPServerSSE

    async def get_tools(self, ctx: RunContext[AgentDepsT]) -> dict[str, ToolsetTool[AgentDepsT]]:
        return await self._healing("tool discovery", lambda: self.wrapped.get_tools(ctx), repeatable=True)

    async def call_tool(
        self, name: str, tool_args: dict[str, Any], ctx: RunContext[AgentDepsT], tool: ToolsetTool[AgentDepsT]
    ) -> Any:
        return await self._healing(
            f"the '{name}' tool",
            lambda: self.wrapped.call_tool(name, tool_args, ctx, tool),
            repeatable=_is_safe_to_repeat(tool),
        )

    async def __aexit__(self, *args: Any) -> bool | None:
        if not self.wrapped.is_running:
            # A reconnect which failed to re-open the session left nothing to close, and delegating
            # would raise over the failure which is already propagating.
            return None
        return await self.wrapped.__aexit__(*args)

    async def _healing(self, operation: str, run: Callable[[], Awaitable[Any]], repeatable: bool) -> Any:
        """Run an MCP operation, repairing the session and repeating the operation if it is safe to."""
        try:
            return await run()
        except Exception as e:
            if not _is_recoverable(e):
                raise
            await self._reconnect(operation)
            if not repeatable:
                logger.warning(f"Not repeating {operation}: Jira may already have applied it.")
                raise
            return await run()

    async def _reconnect(self, operation: str) -> None:
        logger.warning(f"Jira MCP session broke while serving {operation}; re-establishing it.")
        try:
            await self.wrapped.__aexit__(None, None, None)
        except Exception as teardown_error:
            # The session is already broken, so tearing it down is expected to fail; the fresh
            # session below is what matters.
            logger.debug(f"Ignoring the error of tearing down the broken Jira MCP session: {teardown_error}")
        await self.wrapped.__aenter__()


def build_jira_mcp_server() -> MCPServerSSE:
    """Create a fresh, not yet connected Jira MCP server client."""
    return MCPServerSSE(url=config.JIRA_MCP_SERVER_URL, timeout=config.MCP_SERVER_TIMEOUT_SECONDS)


def build_jira_mcp_server_toolset() -> AbstractToolset:
    """Create a fresh, self-healing Jira MCP toolset for a single agent run."""
    return SelfHealingJiraToolset(build_jira_mcp_server())
