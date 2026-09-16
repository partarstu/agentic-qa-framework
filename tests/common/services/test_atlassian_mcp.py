# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for the self-healing, per-request Atlassian MCP toolset."""

from unittest.mock import AsyncMock, MagicMock
from urllib.parse import urlparse

import anyio
import httpx
import pytest
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData
from pydantic_ai.exceptions import ModelRetry

import config
from common.services.atlassian_mcp import (
    SelfHealingAtlassianToolset,
    _is_recoverable,
    build_atlassian_mcp_server,
    build_atlassian_mcp_server_toolset,
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
    toolset = SelfHealingAtlassianToolset(server)

    result = await toolset.call_tool("jira_get_issue", {}, MagicMock(), _tool("jira_get_issue"))

    assert result == "tool result"
    assert server.call_tool.await_count == 2
    server.__aexit__.assert_awaited_once()
    server.__aenter__.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_tools_reconnects_once_and_retries():
    """Tool discovery must self-heal too, not only tool invocation."""
    server = _wrapped_server(anyio.ClosedResourceError(), {"jira_get_issue": MagicMock()})
    toolset = SelfHealingAtlassianToolset(server)

    tools = await toolset.get_tools(MagicMock())

    assert list(tools) == ["jira_get_issue"]
    assert server.get_tools.await_count == 2
    server.__aenter__.assert_awaited_once()


@pytest.mark.asyncio
async def test_non_recoverable_error_propagates_without_reconnect():
    server = _wrapped_server(ValueError("bad arguments"))
    toolset = SelfHealingAtlassianToolset(server)

    with pytest.raises(ValueError, match="bad arguments"):
        await toolset.call_tool("jira_get_issue", {}, MagicMock(), _tool("jira_get_issue"))

    assert server.call_tool.await_count == 1
    server.__aenter__.assert_not_awaited()
    server.__aexit__.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_second_failure_after_the_reconnect_propagates():
    """The budget is exactly one reconnect per operation."""
    server = _wrapped_server(anyio.ClosedResourceError(), anyio.ClosedResourceError())
    toolset = SelfHealingAtlassianToolset(server)

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
    toolset = SelfHealingAtlassianToolset(server)

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
        _tool("confluence_search"),
        _tool("issue_lookup", {"readOnlyHint": True}),
        _tool("jira_transition_issue", {"idempotentHint": True}),
    ],
    ids=["read_verb", "download_verb", "confluence_read_verb", "annotated_read_only", "annotated_idempotent"],
)
async def test_a_read_or_idempotent_tool_is_repeated_after_the_reconnect(tool):
    server = _wrapped_server(anyio.ClosedResourceError(), "tool result")
    toolset = SelfHealingAtlassianToolset(server)

    assert await toolset.call_tool(tool.tool_def.name, {}, MagicMock(), tool) == "tool result"
    assert server.call_tool.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_name",
    ["confluence_create_page", "confluence_update_page"],
    ids=["confluence_create", "confluence_update"],
)
async def test_a_confluence_write_is_not_repeated_after_the_reconnect(tool_name):
    """The read-only detection strips the confluence_ prefix too, so Confluence writes stay unrepeatable."""
    server = _wrapped_server(anyio.ClosedResourceError(), "second call result")
    toolset = SelfHealingAtlassianToolset(server)

    with pytest.raises(anyio.ClosedResourceError):
        await toolset.call_tool(tool_name, {}, MagicMock(), _tool(tool_name))

    assert server.call_tool.await_count == 1


@pytest.mark.asyncio
async def test_closing_after_a_failed_reconnect_does_not_mask_the_failure():
    """A reconnect which cannot re-open the session must not turn into a bogus close error."""
    server = _wrapped_server(anyio.ClosedResourceError())
    server.__aenter__ = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
    server.__aexit__ = AsyncMock(side_effect=lambda *_: setattr(server, "is_running", False))
    toolset = SelfHealingAtlassianToolset(server)

    with pytest.raises(httpx.ConnectError):
        await toolset.call_tool("jira_get_issue", {}, MagicMock(), _tool("jira_get_issue"))

    assert await toolset.__aexit__(None, None, None) is None
    server.__aexit__.assert_awaited_once()


def test_each_factory_call_builds_a_separate_session():
    first, second = build_atlassian_mcp_server_toolset(), build_atlassian_mcp_server_toolset()

    assert first is not second
    assert first.wrapped is not second.wrapped
    assert isinstance(build_atlassian_mcp_server(), type(first.wrapped))


@pytest.mark.asyncio
async def test_allowed_tools_filters_tool_discovery():
    """Each agent only ever sees the Atlassian tools it was built to use (WS11)."""
    advertised = {
        "jira_get_issue": MagicMock(),
        "jira_create_issue": MagicMock(),
        "jira_add_comment": MagicMock(),
        "confluence_search": MagicMock(),
        "confluence_create_page": MagicMock(),
    }
    server = _wrapped_server(advertised)
    toolset = SelfHealingAtlassianToolset(server, allowed_tools=frozenset({"jira_get_issue"}))

    tools = await toolset.get_tools(MagicMock())

    assert list(tools) == ["jira_get_issue"]


@pytest.mark.asyncio
async def test_empty_allowlist_hides_every_tool():
    server = _wrapped_server({"jira_get_issue": MagicMock()})
    toolset = SelfHealingAtlassianToolset(server, allowed_tools=frozenset())

    assert await toolset.get_tools(MagicMock()) == {}


@pytest.mark.asyncio
async def test_no_allowlist_keeps_every_advertised_tool():
    server = _wrapped_server({"jira_get_issue": MagicMock(), "confluence_search": MagicMock()})
    toolset = SelfHealingAtlassianToolset(server)

    assert len(await toolset.get_tools(MagicMock())) == 2


def test_factory_reads_the_atlassian_server_url(monkeypatch):
    monkeypatch.setattr(config, "ATLASSIAN_MCP_SERVER_URL", "http://atlassian-mcp:9000/sse")
    server = build_atlassian_mcp_server()
    assert urlparse(server.url).netloc == "atlassian-mcp:9000"
