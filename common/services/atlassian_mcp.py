# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Per-request Atlassian MCP sessions with self-healing.

Every agent run gets its own MCP session instead of sharing one process-wide connection, so a
session that goes stale between requests cannot break the next one. Within a run, a recoverable
transport failure is repaired by retrying the failed operation once on a fresh, isolated session
owned by the retrying task: the shared session is left untouched, so a retry can never destroy
(or fail to recreate) a session a concurrent tool call still owns (WS21).

Each agent passes the allowlist of tool names it actually uses (WS11): the combined server
advertises Jira and Confluence tools alike, but no agent receives Confluence (or Jira) tools it
wasn't built for.
"""

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any

import anyio
import httpx
from mcp.shared.exceptions import McpError
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.mcp import MCPServerStreamableHTTP
from pydantic_ai.tools import AgentDepsT, RunContext
from pydantic_ai.toolsets import AbstractToolset, ToolsetTool, WrapperToolset

import config
from common import utils

logger = utils.get_logger("atlassian_mcp")

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

# Tool-name prefixes of the combined server; a read verb is checked after stripping either one.
_TOOL_NAME_PREFIXES = ("jira_", "confluence_")


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


def _strip_tool_prefix(name: str) -> str:
    for prefix in _TOOL_NAME_PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix) :]
    return name


def _is_safe_to_repeat(tool: ToolsetTool[Any]) -> bool:
    """Whether re-issuing the tool after a reconnect cannot duplicate a server-side change.

    A broken transport says nothing about whether Jira or Confluence already applied the write,
    so repeating the call could create a second issue or a second comment. Only tools the server
    annotates as read-only or idempotent are repeated; when it annotates nothing, the tool name
    has to start with a read verb after its ``jira_``/``confluence_`` prefix.
    """
    annotations = (tool.tool_def.metadata or {}).get("annotations")
    if annotations:
        return bool(annotations.get("readOnlyHint") or annotations.get("idempotentHint"))
    return _strip_tool_prefix(tool.tool_def.name).startswith(_READ_ONLY_TOOL_NAME_VERBS)


@dataclass
class SelfHealingAtlassianToolset(WrapperToolset[AgentDepsT]):
    """An Atlassian MCP toolset which retries a recoverable failure on a fresh, isolated session.

    The budget is one retry per operation, and the failed operation itself is retried only when
    repeating it cannot duplicate a server-side write; anything that is not recoverable propagates
    untouched. The retry owns a session of its own, so the session shared with concurrent tool
    calls is never torn down or re-entered in place. Set-up and tear-down of the isolated session
    run inside a bounded, cancellation-shielded scope: an interrupted set-up cannot hang, and a
    slow tear-down is logged instead of masking the operation's result or error (WS21).

    When ``allowed_tools`` is set, tool discovery is filtered down to that allowlist, so each
    agent only ever sees the tools it was built to use.
    """

    wrapped: MCPServerStreamableHTTP
    allowed_tools: frozenset[str] | None = None

    async def get_tools(self, ctx: RunContext[AgentDepsT]) -> dict[str, ToolsetTool[AgentDepsT]]:
        tools = await self._healing("tool discovery", lambda session: session.get_tools(ctx), repeatable=True)
        if self.allowed_tools is not None:
            tools = {name: tool for name, tool in tools.items() if name in self.allowed_tools}
        return tools

    async def call_tool(
        self, name: str, tool_args: dict[str, Any], ctx: RunContext[AgentDepsT], tool: ToolsetTool[AgentDepsT]
    ) -> Any:
        return await self._healing(
            f"the '{name}' tool",
            lambda session: session.call_tool(name, tool_args, ctx, tool),
            repeatable=_is_safe_to_repeat(tool),
        )

    async def __aexit__(self, *args: Any) -> bool | None:
        if not self.wrapped.is_running:
            # An isolated-session retry which replaced this run's failed operation leaves the
            # shared session untouched; a session that never started has nothing to close.
            return None
        return await self.wrapped.__aexit__(*args)

    async def _healing(
        self, operation: str, run: Callable[[MCPServerStreamableHTTP], Awaitable[Any]], repeatable: bool
    ) -> Any:
        """Run an MCP operation, retrying it once on an isolated session if it is safe to."""
        try:
            return await run(self.wrapped)
        except Exception as e:
            if not _is_recoverable(e):
                raise
            if not repeatable:
                logger.warning(f"Not repeating {operation}: the server may already have applied it.")
                raise
            return await self._retry_on_isolated_session(operation, run)

    async def _retry_on_isolated_session(
        self, operation: str, run: Callable[[MCPServerStreamableHTTP], Awaitable[Any]]
    ) -> Any:
        """Retry ``run`` against a fresh session owned by this task (WS21)."""
        # A cancelled task stops here instead of firing another request.
        await anyio.lowlevel.checkpoint()
        logger.warning(f"Atlassian MCP session broke while serving {operation}; retrying on a fresh session.")
        fresh = build_atlassian_mcp_server()
        timeout_seconds = config.MCP_SESSION_LIFECYCLE_TIMEOUT_SECONDS
        try:
            try:
                with anyio.fail_after(timeout_seconds, shield=True):
                    await fresh.__aenter__()
            except TimeoutError:
                raise TimeoutError(
                    f"Atlassian MCP session set-up for {operation} did not complete within "
                    f"{timeout_seconds}s."
                )
            return await run(fresh)
        finally:
            try:
                with anyio.fail_after(timeout_seconds, shield=True):
                    await fresh.__aexit__(None, None, None)
            except Exception as teardown_error:
                logger.warning(f"Atlassian MCP session tear-down after {operation} failed: {teardown_error}")


def build_atlassian_mcp_server() -> MCPServerStreamableHTTP:
    """Create a fresh, not yet connected Atlassian MCP server client."""
    return MCPServerStreamableHTTP(url=config.ATLASSIAN_MCP_SERVER_URL, timeout=config.MCP_SERVER_TIMEOUT_SECONDS)


def build_atlassian_mcp_server_toolset(allowed_tools: Iterable[str] | None = None) -> AbstractToolset:
    """Create a fresh, self-healing Atlassian MCP toolset for a single agent run.

    Args:
        allowed_tools: Optional tool names the agent may use; every other advertised
            tool is filtered out of its tool discovery. None keeps every tool.
    """
    return SelfHealingAtlassianToolset(
        build_atlassian_mcp_server(),
        allowed_tools=frozenset(allowed_tools) if allowed_tools is not None else None,
    )
