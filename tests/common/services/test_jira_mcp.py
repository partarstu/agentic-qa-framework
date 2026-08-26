# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for the self-healing, per-request Jira MCP toolset."""

from unittest.mock import AsyncMock, MagicMock

import anyio
import httpx
import pytest
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData
from pydantic_ai.exceptions import ModelRetry

from common.services.jira_mcp import (
    SelfHealingJiraToolset,
    _is_recoverable,
    build_jira_mcp_server,
    build_jira_mcp_server_toolset,
)

RECOVERABLE_ERRORS = [
    anyio.ClosedResourceError(),
    anyio.BrokenResourceError(),
    anyio.EndOfStream(),
    TimeoutError("timed out"),
    EOFError("stream closed"),
    httpx.ReadTimeout("timed out"),
    httpx.ConnectError("connection refused"),
    httpx.RemoteProtocolError("peer closed connection"),
    McpError(ErrorData(code=-32001, message="Request timed out")),
    ModelRetry("The tool response timed out, please try again"),
]


def _wrapped_server(*side_effects) -> MagicMock:
    """A stub MCP server whose get_tools/call_tool replay the given results (exceptions are raised)."""
    server = MagicMock()
    server.get_tools = AsyncMock(side_effect=list(side_effects))
    server.call_tool = AsyncMock(side_effect=list(side_effects))
    server.__aenter__ = AsyncMock()
    server.__aexit__ = AsyncMock()
    server.is_running = True
    return server


def _tool(name: str, annotations: dict | None = None) -> MagicMock:
    """A stub MCP tool carrying the name and the annotations the server advertised for it."""
    tool = MagicMock()
    tool.tool_def.name = name
    tool.tool_def.metadata = {"annotations": annotations}
    return tool


@pytest.mark.parametrize("error", RECOVERABLE_ERRORS, ids=lambda e: type(e).__name__)
def test_recoverable_errors_are_recognised(error):
    assert _is_recoverable(error) is True


@pytest.mark.parametrize(
    "error",
    [
        ValueError("bad arguments"),
        McpError(ErrorData(code=-32602, message="Invalid params")),
        ModelRetry("The issue key you passed does not exist"),
    ],
    ids=["ValueError", "McpError", "ModelRetry"],
)
def test_non_recoverable_errors_are_recognised(error):
    assert _is_recoverable(error) is False


def test_exception_groups_are_matched_member_wise():
    assert _is_recoverable(ExceptionGroup("g", [ValueError("x"), anyio.EndOfStream()])) is True
    assert _is_recoverable(ExceptionGroup("g", [ValueError("x"), KeyError("y")])) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("error", RECOVERABLE_ERRORS, ids=lambda e: type(e).__name__)
async def test_call_tool_reconnects_once_and_retries(error):
    server = _wrapped_server(error, "tool result")
    toolset = SelfHealingJiraToolset(server)

    result = await toolset.call_tool("jira_get_issue", {}, MagicMock(), _tool("jira_get_issue"))

    assert result == "tool result"
    assert server.call_tool.await_count == 2
    server.__aexit__.assert_awaited_once()
    server.__aenter__.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_tools_reconnects_once_and_retries():
    """Tool discovery must self-heal too, not only tool invocation."""
    server = _wrapped_server(anyio.ClosedResourceError(), {"jira_get_issue": MagicMock()})
    toolset = SelfHealingJiraToolset(server)

    tools = await toolset.get_tools(MagicMock())

    assert list(tools) == ["jira_get_issue"]
    assert server.get_tools.await_count == 2
    server.__aenter__.assert_awaited_once()


@pytest.mark.asyncio
async def test_non_recoverable_error_propagates_without_reconnect():
    server = _wrapped_server(ValueError("bad arguments"))
    toolset = SelfHealingJiraToolset(server)

    with pytest.raises(ValueError, match="bad arguments"):
        await toolset.call_tool("jira_get_issue", {}, MagicMock(), _tool("jira_get_issue"))

    assert server.call_tool.await_count == 1
    server.__aenter__.assert_not_awaited()
    server.__aexit__.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_second_failure_after_the_reconnect_propagates():
    """The budget is exactly one reconnect per operation."""
    server = _wrapped_server(anyio.ClosedResourceError(), anyio.ClosedResourceError())
    toolset = SelfHealingJiraToolset(server)

    with pytest.raises(anyio.ClosedResourceError):
        await toolset.call_tool("jira_get_issue", {}, MagicMock(), _tool("jira_get_issue"))

    assert server.call_tool.await_count == 2
    server.__aenter__.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool",
    [
        _tool("jira_add_comment"),
        _tool("jira_create_issue"),
        _tool("jira_get_issue", {"readOnlyHint": False}),
    ],
    ids=["unannotated_write", "unannotated_create", "annotated_as_a_write"],
)
async def test_a_write_is_not_repeated_after_the_reconnect(tool):
    """Jira may already have applied the write, so repeating it would duplicate it."""
    server = _wrapped_server(anyio.ClosedResourceError(), "second call result")
    toolset = SelfHealingJiraToolset(server)

    with pytest.raises(anyio.ClosedResourceError):
        await toolset.call_tool(tool.tool_def.name, {}, MagicMock(), tool)

    assert server.call_tool.await_count == 1
    # The session is still repaired, so the operations which follow in the same run can succeed.
    server.__aenter__.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool",
    [
        _tool("jira_search"),
        _tool("jira_download_attachments"),
        _tool("issue_lookup", {"readOnlyHint": True}),
        _tool("jira_transition_issue", {"idempotentHint": True}),
    ],
    ids=["read_verb", "download_verb", "annotated_read_only", "annotated_idempotent"],
)
async def test_a_read_or_idempotent_tool_is_repeated_after_the_reconnect(tool):
    server = _wrapped_server(anyio.ClosedResourceError(), "tool result")
    toolset = SelfHealingJiraToolset(server)

    assert await toolset.call_tool(tool.tool_def.name, {}, MagicMock(), tool) == "tool result"
    assert server.call_tool.await_count == 2


@pytest.mark.asyncio
async def test_closing_after_a_failed_reconnect_does_not_mask_the_failure():
    """A reconnect which cannot re-open the session must not turn into a bogus close error."""
    server = _wrapped_server(anyio.ClosedResourceError())
    server.__aenter__ = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
    server.__aexit__ = AsyncMock(side_effect=lambda *_: setattr(server, "is_running", False))
    toolset = SelfHealingJiraToolset(server)

    with pytest.raises(httpx.ConnectError):
        await toolset.call_tool("jira_get_issue", {}, MagicMock(), _tool("jira_get_issue"))

    assert await toolset.__aexit__(None, None, None) is None
    server.__aexit__.assert_awaited_once()


def test_each_factory_call_builds_a_separate_session():
    first, second = build_jira_mcp_server_toolset(), build_jira_mcp_server_toolset()

    assert first is not second
    assert first.wrapped is not second.wrapped
    assert isinstance(build_jira_mcp_server(), type(first.wrapped))
