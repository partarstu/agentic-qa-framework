# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import json
from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from a2a.helpers import get_message_text, new_data_part, new_text_part
from a2a.types import Message
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RunUsage

from agents.test_case_design import main as design_main
from agents.test_case_design.main import TestCaseDesignAgent
from agents.test_case_review import main as review_main
from common.models import (
    AgentRuntimeError,
    DesignStopReason,
    FindingAction,
    FindingSeverity,
    ReviewFinding,
    TestCase,
    TestCaseDesignResult,
    TestCaseDesignSession,
    TestCaseDuplicateCheck,
)
from common.services.test_management_base import TestManagementClientBase

_WRITE_TOOLS = {
    "upload_test_cases",
    "classify_test_cases",
    "add_review_feedback",
    "set_test_case_status_to_review_complete",
}


def _test_case(name: str) -> TestCase:
    return TestCase(
        key=None, labels=[], name=name, summary="s", comment="", preconditions=None, steps=[], parent_issue_key="PROJ-1"
    )


def _finding(owner: str, severity: FindingSeverity = FindingSeverity.HIGH) -> ReviewFinding:
    return ReviewFinding(
        owner_test_case_id=owner,
        action=FindingAction.MODIFY,
        severity=severity,
        category="clarity",
        description="A problem",
        suggested_fix="A fix",
    )


def _generate(session: TestCaseDesignSession) -> None:
    session.story_id = 10
    session.story_content = "Story content"
    session.add_draft(_test_case("First"))


def _review(*findings: ReviewFinding) -> Callable[[TestCaseDesignSession], None]:
    def review(session: TestCaseDesignSession) -> None:
        for test_case_id in session.changed_test_case_ids:
            session.findings[test_case_id] = [f for f in findings if f.owner_test_case_id == test_case_id]
        session.changed_test_case_ids.clear()
        session.suite_reviewed = True

    return review


async def _check_duplicates(ctx: RunContext[TestCaseDesignSession]) -> str:
    ctx.deps.duplicate_checks = {test_case_id: TestCaseDuplicateCheck() for test_case_id in ctx.deps.test_cases}
    return "DRAFT-1: no duplicates"


def _delegate(effect: Callable[[TestCaseDesignSession], None], summary: str = "done") -> MagicMock:
    async def run_delegated(prompt: str, deps: TestCaseDesignSession, usage: RunUsage) -> str:
        effect(deps)
        return summary

    return MagicMock(run_delegated=AsyncMock(side_effect=run_delegated))


def _reviewer(*findings: ReviewFinding) -> MagicMock:
    reviewer = _delegate(_review(*findings))
    reviewer.check_duplicates = AsyncMock(side_effect=_check_duplicates)
    return reviewer


@pytest.fixture
def agent() -> TestCaseDesignAgent:
    design_agent = TestCaseDesignAgent()
    design_agent.generation_agent = _delegate(_generate)
    design_agent.review_agent = _reviewer()
    design_agent.classification_agent = _delegate(lambda session: None, "labelled")
    return design_agent


@pytest.fixture
def client() -> Iterator[MagicMock]:
    mock_client = MagicMock(spec=TestManagementClientBase)
    mock_client.create_test_cases.return_value = ["PROJ-T1"]
    with patch("common.services.test_management_tools.get_test_management_client", return_value=mock_client):
        yield mock_client


@pytest.fixture
def vector_db() -> Iterator[MagicMock]:
    service = MagicMock(hybrid_search=AsyncMock(return_value=[]), upsert_batch=AsyncMock())
    with patch.object(review_main.agent, "vector_db_service", service):
        yield service


def _ctx(session: TestCaseDesignSession) -> SimpleNamespace:
    return SimpleNamespace(deps=session, usage=RunUsage())


def _generated() -> TestCaseDesignSession:
    session = TestCaseDesignSession(story_key="PROJ-1")
    _generate(session)
    return session


def _scripted_model(calls: list[tuple[str | None, dict[str, Any]]], offered: list[set[str]]) -> FunctionModel:
    """Calls the scripted tools in order, where None stands for the final result, then returns the final result."""

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        offered.append({tool.name for tool in info.function_tools})
        step = sum(isinstance(message, ModelResponse) for message in messages)
        name, args = calls[step] if step < len(calls) else (None, {})
        return ModelResponse(parts=[ToolCallPart(name or info.output_tools[0].name, args)])

    return FunctionModel(respond)


def _design_request() -> Message:
    return Message(message_id="m-1", parts=[new_text_part("Design PROJ-1"), new_data_part({"story_key": "PROJ-1"})])


async def test_a_converging_design_is_checked_for_duplicates_then_saved_classified_and_published(
    agent, client, vector_db
):
    agent.review_agent.check_duplicates = review_main.agent.check_duplicates
    offered: list[set[str]] = []
    calls = [
        ("generate_test_cases", {}),
        ("review_test_cases", {}),
        ("upload_test_cases", {}),
        ("classify_test_cases", {}),
        ("add_review_feedback", {"test_case_key": "PROJ-T1"}),
        ("set_test_case_status_to_review_complete", {"test_case_key": "PROJ-T1"}),
    ]

    with agent.agent.override(model=_scripted_model(calls, offered)):
        response = await agent.run(_design_request())

    result = TestCaseDesignResult.model_validate_json(get_message_text(response))
    assert result.test_case_keys == ["PROJ-T1"]
    assert (result.iterations, result.stop_reason) == (1, DesignStopReason.CONVERGED)
    assert not offered[0] & _WRITE_TOOLS, "Nothing may be written before the review loop stops"
    assert offered[2] >= _WRITE_TOOLS
    assert "fix_test_cases" not in offered[2]
    client.create_test_cases.assert_called_once()
    comment = client.add_test_case_review_comment.call_args.args[1]
    assert "No duplicate test cases found." in comment
    client.change_test_case_status.assert_called_once_with("PROJ", "PROJ-T1", "Review Complete")
    vector_db.hybrid_search.assert_awaited_once()
    vector_db.upsert_batch.assert_not_awaited()
    classified = agent.classification_agent.run_delegated.await_args.args[0]
    assert classified.startswith("Test cases:\n")
    assert '"key": "PROJ-T1"' in classified


async def test_a_failure_before_the_writes_fails_the_design_and_writes_nothing(agent, client):
    agent.generation_agent.run_delegated.side_effect = RuntimeError("model unavailable")

    with (
        agent.agent.override(model=_scripted_model([("generate_test_cases", {})], [])),
        pytest.raises(AgentRuntimeError, match="model unavailable"),
    ):
        await agent.run(_design_request())

    client.create_test_cases.assert_not_called()


async def test_an_early_result_with_a_comment_aborts_the_design_without_further_requests(agent, client):
    offered: list[set[str]] = []
    calls = [("generate_test_cases", {}), (None, {"llm_comments": "The Jira story PROJ-1 does not exist."})]

    with (
        agent.agent.override(model=_scripted_model(calls, offered)),
        pytest.raises(AgentRuntimeError, match=r"aborted \(The Jira story PROJ-1 does not exist\.\)") as failure,
    ):
        await agent.run(_design_request())

    assert "steps not done: finish the review loop; save the test cases" in str(failure.value)
    assert len(offered) == 2, "The abort must end the run without another model request"
    client.create_test_cases.assert_not_called()


async def test_a_design_without_a_session_fails_with_a_clear_error(agent):
    message = Message(message_id="m-1", parts=[new_text_part("Design PROJ-1")])

    with (
        agent.agent.override(model=_scripted_model([], [])),
        pytest.raises(AgentRuntimeError, match="structured data part"),
    ):
        await agent.run(message)


async def test_generation_delegates_with_the_story_key_and_the_additional_fields_instruction(agent):
    session = TestCaseDesignSession(story_key="PROJ-1")

    with patch.object(design_main, "build_additional_fields_instruction", return_value="FETCH customfield_1"):
        assert await agent.generate_test_cases(_ctx(session)) == "done"
    with pytest.raises(ModelRetry, match="already generated"):
        await agent.generate_test_cases(_ctx(session))

    prompt = agent.generation_agent.run_delegated.await_args.args[0]
    assert prompt == "Generate the test cases of the Jira user story PROJ-1.\n\nFETCH customfield_1"
    assert agent.generation_agent.run_delegated.await_count == 1


async def test_review_without_blocking_findings_converges(agent):
    session = _generated()
    agent.review_agent = _reviewer(_finding("DRAFT-1", FindingSeverity.LOW))

    result = await agent.review_test_cases(_ctx(session))

    assert (session.iteration, session.stop_reason) == (1, DesignStopReason.CONVERGED)
    assert "0 blocking finding(s). The design is finished (converged); save the test cases next." in result
    assert result.endswith("Duplicates of the final test cases among the existing ones:\nDRAFT-1: no duplicates")
    assert session.duplicate_checks == {"DRAFT-1": TestCaseDuplicateCheck()}


async def test_review_with_blocking_findings_continues_until_the_iteration_limit(agent):
    session = _generated()
    agent.max_iterations = 2
    agent.review_agent = _reviewer(_finding("DRAFT-1"))
    agent.generation_agent = _delegate(lambda design: design.changed_test_case_ids.add("DRAFT-1"), "fixed")

    first = await agent.review_test_cases(_ctx(session))
    agent.review_agent.check_duplicates.assert_not_awaited()
    await agent.fix_test_cases(_ctx(session))
    second = await agent.review_test_cases(_ctx(session))

    assert "1 blocking finding(s). The design continues: fix the test cases next." in first
    assert "The design is finished (iteration_limit); save the test cases next." in second
    agent.review_agent.check_duplicates.assert_awaited_once()
    assert (session.iteration, session.fixes, session.stop_reason) == (2, 1, DesignStopReason.ITERATION_LIMIT)
    assert (
        agent.generation_agent.run_delegated.await_args.args[0] == "Fix the test cases of the Jira user story PROJ-1."
    )


@pytest.mark.parametrize(
    ("prepare", "message"),
    [
        (lambda session: session.test_cases.clear(), "generate them first"),
        (lambda session: setattr(session, "stop_reason", DesignStopReason.CONVERGED), "design is finished"),
        (lambda session: setattr(session, "iteration", 1), "fix them next"),
    ],
    ids=["nothing generated", "stopped", "not fixed since the last review"],
)
async def test_review_is_refused_out_of_order(agent, prepare, message):
    session = _generated()
    prepare(session)

    with pytest.raises(ModelRetry, match=message):
        await agent.review_test_cases(_ctx(session))

    agent.review_agent.run_delegated.assert_not_awaited()


async def test_an_incomplete_review_does_not_count_as_an_iteration(agent):
    session = _generated()
    agent.review_agent = _delegate(lambda design: None)

    with pytest.raises(ModelRetry, match="unreviewed"):
        await agent.review_test_cases(_ctx(session))

    assert session.iteration == 0


async def test_a_review_without_the_whole_set_review_does_not_count_as_an_iteration(agent):
    session = _generated()
    session.suite_reviewed = True

    def per_test_case_review_only(design: TestCaseDesignSession) -> None:
        design.findings["DRAFT-1"] = []
        design.changed_test_case_ids.clear()

    agent.review_agent = _delegate(per_test_case_review_only)

    with pytest.raises(ModelRetry, match="skipped the whole set"):
        await agent.review_test_cases(_ctx(session))

    assert (session.iteration, session.stop_reason) == (0, None)


async def test_fixing_twice_without_a_review_is_refused(agent):
    session = _generated()
    session.iteration, session.fixes = 1, 1

    with pytest.raises(ModelRetry, match="already fixed"):
        await agent.fix_test_cases(_ctx(session))

    agent.generation_agent.run_delegated.assert_not_awaited()


async def test_classification_needs_saved_test_cases_and_runs_once(agent):
    session = _generated()

    with pytest.raises(ModelRetry, match="Save the test cases first"):
        await agent.classify_test_cases(_ctx(session))
    session.uploaded = True
    assert await agent.classify_test_cases(_ctx(session)) == "labelled"
    with pytest.raises(ModelRetry, match="already classified"):
        await agent.classify_test_cases(_ctx(session))

    assert agent.classification_agent.run_delegated.await_count == 1
    assert session.classified


@pytest.mark.parametrize(
    ("deps", "fix_tool_offered", "write_tool_offered"),
    [
        (None, False, False),
        (TestCaseDesignSession(story_key="PROJ-1"), False, False),
        (TestCaseDesignSession(story_key="PROJ-1", iteration=1), True, False),
        (TestCaseDesignSession(story_key="PROJ-1", iteration=1, stop_reason=DesignStopReason.CONVERGED), False, True),
    ],
    ids=["no session", "before the first review", "looping", "stopped"],
)
async def test_fixes_are_offered_only_during_the_loop_and_writes_only_after_it(
    deps, fix_tool_offered, write_tool_offered
):
    tool_def = MagicMock()
    ctx = SimpleNamespace(deps=deps)

    assert (await design_main._hide_outside_fix_loop(ctx, tool_def) is tool_def) is fix_tool_offered
    assert (await design_main._hide_until_stopped(ctx, tool_def) is tool_def) is write_tool_offered


def test_the_result_is_refused_until_every_step_is_done_and_then_filled_from_the_session():
    session = _generated()
    ctx = SimpleNamespace(deps=session)

    with pytest.raises(ModelRetry) as refusal:
        design_main._complete_result(ctx, TestCaseDesignResult())
    session.test_cases = {"PROJ-T1": _test_case("First")}
    session.stop_reason, session.iteration = DesignStopReason.ITERATION_LIMIT, 4
    session.uploaded = session.classified = True
    session.feedback_added_ids = session.review_completed_ids = {"PROJ-T1"}
    result = design_main._complete_result(ctx, TestCaseDesignResult(llm_comments=None))

    assert str(refusal.value) == (
        "The design is not complete yet: finish the review loop; save the test cases; classify the saved test cases; "
        "add the review feedback of ['DRAFT-1']; set the status of ['DRAFT-1']."
    )
    assert json.loads(result.model_dump_json()) == {
        "llm_comments": None,
        "test_case_keys": ["PROJ-T1"],
        "iterations": 4,
        "stop_reason": "iteration_limit",
    }


def test_the_design_budget_covers_the_delegated_runs(agent):
    assert agent.get_total_tokens_limit() == 4_000_000
    assert agent.get_max_requests_per_task() == 150
