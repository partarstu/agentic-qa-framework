# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import asyncio
from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import ModelRetry
from pydantic_ai.messages import BinaryContent, ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RunUsage

from agents.test_case_generation import main as generation_main
from agents.test_case_generation.main import TestCaseGenerationAgent
from common.models import (
    AcceptanceCriteriaList,
    FindingAction,
    FindingSeverity,
    GeneratedTestCases,
    ReviewFinding,
    TestCase,
    TestCaseDesignSession,
    TestCaseDuplicateCheck,
    TestStepsSequenceList,
)
from common.services.test_management_tools import hide_while_designing, upload_test_cases


@pytest.fixture
def mock_config() -> Iterator[MagicMock]:
    with patch("agents.test_case_generation.main.config") as mock_conf:
        mock_conf.TestCaseGenerationAgentConfig.OWN_NAME = "generation_agent"
        mock_conf.AGENT_BASE_URL = "http://localhost"
        mock_conf.TestCaseGenerationAgentConfig.PORT = 8002
        mock_conf.TestCaseGenerationAgentConfig.EXTERNAL_PORT = 8002
        mock_conf.TestCaseGenerationAgentConfig.PROTOCOL = "http"
        mock_conf.TestCaseGenerationAgentConfig.MODEL_NAME = "test"
        mock_conf.TestCaseGenerationAgentConfig.VERSION = "2.5"
        mock_conf.TestCaseGenerationAgentConfig.SKILL_ID = "test-case-generation"
        mock_conf.TestCaseGenerationAgentConfig.SKILL_NAME = "Test Case Generation"
        mock_conf.TestCaseGenerationAgentConfig.SKILL_DESCRIPTION = "Generates test cases"
        mock_conf.TestCaseGenerationAgentConfig.THINKING_LEVEL = "MEDIUM"
        mock_conf.TestCaseGenerationAgentConfig.MAX_REQUESTS_PER_TASK = 10
        mock_conf.TestCaseGenerationAgentConfig.MAX_OUTPUT_TOKENS = None
        mock_conf.TestCaseDesignAgentConfig.FIX_MIN_SEVERITY = "medium"
        mock_conf.ATLASSIAN_MCP_SERVER_URL = "http://jira-mcp"
        mock_conf.MCP_SERVER_TIMEOUT_SECONDS = 30
        yield mock_conf


@pytest.fixture
def agent(mock_config: MagicMock) -> TestCaseGenerationAgent:
    return TestCaseGenerationAgent()


def _test_case(name: str, key: str | None = None) -> TestCase:
    return TestCase(
        key=key, labels=[], name=name, summary=f"Summary of {name}", comment="", preconditions=None, steps=[],
        parent_issue_key="PROJ-1",
    )  # fmt: skip


def _session(*names: str) -> TestCaseDesignSession:
    session = TestCaseDesignSession(story_key="PROJ-1", story_id=10, story_content="Story content", attachments={})
    for name in names:
        session.add_draft(_test_case(name))
    session.changed_test_case_ids.clear()
    return session


def _ctx(session: TestCaseDesignSession) -> SimpleNamespace:
    return SimpleNamespace(deps=session, usage=RunUsage())


def _finding(
    owner: str | None,
    action: FindingAction = FindingAction.MODIFY,
    severity: FindingSeverity = FindingSeverity.HIGH,
    description: str = "A problem",
) -> ReviewFinding:
    return ReviewFinding(
        owner_test_case_id=owner,
        action=action,
        severity=severity,
        category="coverage",
        description=description,
        suggested_fix="A fix",
    )


def _fixer_returning(*test_cases: TestCase) -> AsyncMock:
    return AsyncMock(side_effect=[MagicMock(output=test_case) for test_case in test_cases])


def test_agent_init(agent):
    assert agent.agent_name == "generation_agent"
    assert agent.get_thinking_level() == "MEDIUM"
    assert agent.get_max_requests_per_task() == 10
    assert agent.fix_min_severity is FindingSeverity.MEDIUM


def test_an_unknown_fix_severity_fails_at_start(mock_config):
    mock_config.TestCaseDesignAgentConfig.FIX_MIN_SEVERITY = "urgent"

    with pytest.raises(ValueError, match="urgent"):
        TestCaseGenerationAgent()


def test_upload_is_the_shared_tool_hidden_while_designing(agent):
    upload = agent.agent._function_toolset.tools["upload_test_cases"]

    assert upload.function is upload_test_cases
    assert upload.prepare is hide_while_designing
    assert upload.sequential


def _offering_model(offered: list[set[str]], instructions: list[str]) -> FunctionModel:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        offered.append({tool.name for tool in info.function_tools})
        instructions.append(info.instructions or "")
        return ModelResponse(parts=[TextPart("done")])

    return FunctionModel(respond)


async def test_a_delegated_run_gets_the_designing_tasks_and_no_upload(agent):
    offered: list[set[str]] = []
    instructions: list[str] = []
    agent.designing_instructions, agent.standalone_instructions = "DESIGNING TASKS", "STANDALONE TASKS"
    agent.mcp_toolset_factories = []

    with agent.agent.override(model=_offering_model(offered, instructions)):
        assert await agent.run_delegated("Generate", _session(), RunUsage()) == "done"

    assert "upload_test_cases" not in offered[0]
    assert {"_generate_test_cases", "fix_test_cases"} <= offered[0]
    assert "DESIGNING TASKS" in instructions[0]


async def test_a_standalone_run_gets_the_standalone_tasks_and_the_upload(agent):
    offered: list[set[str]] = []
    instructions: list[str] = []
    agent.designing_instructions, agent.standalone_instructions = "DESIGNING TASKS", "STANDALONE TASKS"

    with agent.agent.override(model=_offering_model(offered, instructions)):
        await agent.agent.run("Generate", deps=_session(), output_type=str)

    assert "upload_test_cases" in offered[0]
    assert "STANDALONE TASKS" in instructions[0]


async def test_generation_adds_the_generated_test_cases_to_the_design_as_drafts(agent):
    agent.ac_extractor_agent.run = AsyncMock(return_value=MagicMock(output=AcceptanceCriteriaList(items=[])))
    agent.steps_generator_agent.run = AsyncMock(return_value=MagicMock(output=TestStepsSequenceList(items=[])))
    generated = GeneratedTestCases(test_cases=[_test_case("First"), _test_case("Second")])
    agent.test_case_creator_agent.run = AsyncMock(return_value=MagicMock(output=generated))
    policy = BinaryContent(data=b"At most 3 reset requests per hour.", media_type="text/plain", identifier="policy.md")
    session = TestCaseDesignSession(story_key="PROJ-1")
    ctx = _ctx(session)
    jira_toolset = MagicMock()
    jira_toolset.__aenter__ = AsyncMock(return_value=jira_toolset)
    jira_toolset.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("common.services.jira_attachments.download_issue_attachments", return_value={"policy.md": policy}),
        patch("agents.test_case_generation.main.build_atlassian_mcp_server_toolset", return_value=jira_toolset),
    ):
        result = await agent._generate_test_cases(ctx, 10, "Jira Content")

    assert (session.story_id, session.story_content) == (10, "Jira Content")
    assert session.attachments == {"policy.md": policy}
    assert {key: test_case.name for key, test_case in session.test_cases.items()} == {
        "DRAFT-1": "First",
        "DRAFT-2": "Second",
    }
    assert session.changed_test_case_ids == {"DRAFT-1", "DRAFT-2"}
    assert [test_case.key for test_case in result.test_cases] == ["DRAFT-1", "DRAFT-2"]
    assert agent.ac_extractor_agent.run.await_args.kwargs["toolsets"] == [jira_toolset]
    jira_toolset.__aexit__.assert_awaited_once()
    for run in (agent.ac_extractor_agent.run, agent.steps_generator_agent.run):
        assert run.await_args.args[0][-2:] == ["Attachment: policy.md", policy]
    assert agent.steps_generator_agent.run.await_args.args[0][0].startswith("Acceptance Criteria Items:\n")
    for run in (agent.ac_extractor_agent.run, agent.steps_generator_agent.run, agent.test_case_creator_agent.run):
        assert run.await_args.kwargs["usage"] is ctx.usage
        assert run.await_args.kwargs["usage_limits"] == agent.get_sub_agent_usage_limits()


async def test_test_cases_are_generated_only_once(agent):
    agent.ac_extractor_agent.run = AsyncMock()

    with pytest.raises(ModelRetry, match="already generated"):
        await agent._generate_test_cases(_ctx(_session("First")), 10, "Jira Content")

    agent.ac_extractor_agent.run.assert_not_awaited()


async def test_nothing_is_fixed_without_a_finding_at_or_above_the_threshold(agent):
    session = _session("First")
    session.findings = {"DRAFT-1": [_finding("DRAFT-1", severity=FindingSeverity.LOW)]}
    agent.test_case_fixer_agent.run = AsyncMock()

    result = await agent.fix_test_cases(_ctx(session))

    assert "nothing to fix" in result
    agent.test_case_fixer_agent.run.assert_not_awaited()
    assert session.changed_test_case_ids == set()


async def test_fixing_resolves_the_blocking_findings_of_each_owner_in_one_run(agent):
    session = _session("First", "Second")
    session.findings = {
        "DRAFT-1": [
            _finding("DRAFT-1", description="missing expected result"),
            _finding("DRAFT-1", severity=FindingSeverity.LOW, description="imprecise name"),
        ]
    }
    session.suite_findings = [
        _finding("DRAFT-1", FindingAction.REMOVE_DUPLICATE_STEPS, FindingSeverity.MEDIUM, "repeats DRAFT-2")
    ]
    agent.test_case_fixer_agent.run = _fixer_returning(_test_case("First fixed", key="stale"))
    ctx = _ctx(session)

    result = await agent.fix_test_cases(ctx)

    message = agent.test_case_fixer_agent.run.await_args.args[0]
    assert "Test case to fix (ID DRAFT-1)" in message[0]
    assert "missing expected result" in message[1]
    assert "repeats DRAFT-2" in message[1]
    assert "imprecise name" not in message[1]
    assert "ID DRAFT-2" in message[2]
    assert message[3] == "Jira Issue content:\n```Story content```"
    assert agent.test_case_fixer_agent.run.await_args.kwargs["usage"] is ctx.usage
    assert agent.test_case_fixer_agent.run.await_args.kwargs["usage_limits"] == agent.get_sub_agent_usage_limits()
    assert session.test_cases["DRAFT-1"].name == "First fixed"
    assert session.test_cases["DRAFT-1"].key is None
    assert session.changed_test_case_ids == {"DRAFT-1"}
    assert "Modified test cases: DRAFT-1" in result


async def test_fixing_deletes_redundant_test_cases_and_adds_missing_ones(agent):
    session = _session("First", "Second")
    session.findings = {"DRAFT-2": [_finding("DRAFT-2", description="also wrong")]}
    session.duplicate_checks = {"DRAFT-1": TestCaseDuplicateCheck(), "DRAFT-2": TestCaseDuplicateCheck()}
    session.suite_findings = [
        _finding("DRAFT-2", FindingAction.DELETE_TEST_CASE),
        _finding(None, FindingAction.ADD_TEST_CASE, description="AC-3 is not covered"),
    ]
    agent.test_case_fixer_agent.run = _fixer_returning(_test_case("Covers AC-3"))

    result = await agent.fix_test_cases(_ctx(session))

    assert agent.test_case_fixer_agent.run.await_count == 1
    message = agent.test_case_fixer_agent.run.await_args.args[0]
    assert "AC-3 is not covered" in message[0]
    assert "ID DRAFT-1" in message[1]
    assert set(session.test_cases) == {"DRAFT-1", "DRAFT-3"}
    assert session.test_cases["DRAFT-3"].name == "Covers AC-3"
    assert "DRAFT-2" not in session.findings
    assert set(session.duplicate_checks) == {"DRAFT-1"}
    assert session.changed_test_case_ids == {"DRAFT-3"}
    assert result == "Modified test cases: none; added: DRAFT-3; deleted: DRAFT-2."


async def test_a_repeated_fix_finds_nothing_left_to_fix(agent):
    session = _session("First")
    low = _finding("DRAFT-1", severity=FindingSeverity.LOW, description="imprecise name")
    session.findings = {"DRAFT-1": [_finding("DRAFT-1"), low]}
    session.suite_findings = [_finding(None, FindingAction.ADD_TEST_CASE, description="AC-3 is not covered")]
    agent.test_case_fixer_agent.run = _fixer_returning(_test_case("First fixed"), _test_case("Covers AC-3"))

    await agent.fix_test_cases(_ctx(session))
    repeated = await agent.fix_test_cases(_ctx(session))

    assert "nothing to fix" in repeated
    assert agent.test_case_fixer_agent.run.await_count == 2
    assert set(session.test_cases) == {"DRAFT-1", "DRAFT-2"}
    assert session.findings == {"DRAFT-1": [low]}
    assert session.suite_findings == []


async def test_the_fixes_of_different_test_cases_run_concurrently(agent):
    session = _session("First", "Second")
    session.findings = {"DRAFT-1": [_finding("DRAFT-1")], "DRAFT-2": [_finding("DRAFT-2")]}
    started: list[str] = []
    both_started = asyncio.Event()

    async def fix(message: list, **kwargs) -> MagicMock:
        started.append(message[0])
        if len(started) == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=1)
        return MagicMock(output=_test_case(f"Fixed {len(started)}"))

    agent.test_case_fixer_agent.run = fix

    await agent.fix_test_cases(_ctx(session))

    assert len(started) == 2
    assert session.changed_test_case_ids == {"DRAFT-1", "DRAFT-2"}


def test_other_test_cases_exclude_the_one_being_fixed():
    session = _session("First", "Second")

    assert "ID DRAFT-1" not in generation_main._other_test_cases(session, "DRAFT-1")
    assert "ID DRAFT-2" in generation_main._other_test_cases(session, "DRAFT-1")
