# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import asyncio
import json
from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from a2a.helpers import get_message_text, new_data_part, new_text_part
from a2a.types import Message
from fastapi.testclient import TestClient
from pydantic_ai import ModelRetry
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.usage import RunUsage, UsageLimits

import config
from agents.test_case_design import main as design_main
from agents.test_case_design.main import TestCaseDesignAgent
from agents.test_case_review.main import TestCaseDuplicateCheckError, TestCaseReviewer
from common.models import (
    AgentRuntimeError,
    DeletedTestCase,
    DesignedTestCase,
    DesignStopReason,
    TestCaseDesignResult,
    TestCaseDesignSession,
    TestCaseDuplicateCheck,
    TestCaseKeys,
    TestCaseReviewFinding,
    TestCaseReviewFindingAction,
    TestCaseReviewFindingSeverity,
)
from common.services import test_management_tools as tools
from common.services.test_management_base import TestManagementClientBase

_DESIGN_TOOLS = {"jira_get_issue", "generate_test_cases", "review_test_cases", "fix_test_cases", "publish_test_cases"}
_FETCH = ("jira_get_issue", {"issue_key": "PROJ-1", "comment_limit": 0})


def _test_case(name: str) -> DesignedTestCase:
    return DesignedTestCase(
        key=None, labels=[], name=name, summary="s", comment="", preconditions=None, steps=[], parent_issue_key="PROJ-1",
        ac_ids=["AC-1"],
    )  # fmt: skip


def _finding(
    owner: str, severity: TestCaseReviewFindingSeverity = TestCaseReviewFindingSeverity.HIGH
) -> TestCaseReviewFinding:
    return TestCaseReviewFinding(
        owner_test_case_id=owner,
        action=TestCaseReviewFindingAction.MODIFY,
        severity=severity,
        category="clarity",
        description="A problem",
        suggested_fix="A fix",
    )


def _generate(session: TestCaseDesignSession) -> None:
    session.add_draft(_test_case("First"))


def _fix(session: TestCaseDesignSession) -> None:
    session.drop_blocking_findings(TestCaseReviewFindingSeverity.LOW)
    session.changed_test_case_ids.add("DRAFT-1")


async def _check_duplicates(session: TestCaseDesignSession, usage: RunUsage, usage_limits: UsageLimits) -> None:
    session.duplicate_checks = {test_case_id: TestCaseDuplicateCheck() for test_case_id in session.test_cases}


def _delegate(effect: Callable[[TestCaseDesignSession], None], summary: str = "done") -> MagicMock:
    async def run_delegated(prompt: str, deps: TestCaseDesignSession, usage: RunUsage) -> str:
        effect(deps)
        return summary

    return MagicMock(run_delegated=AsyncMock(side_effect=run_delegated))


def _reviewer(*findings: TestCaseReviewFinding) -> MagicMock:
    async def review_changed(session: TestCaseDesignSession, usage: RunUsage, usage_limits: UsageLimits) -> None:
        for test_case_id in session.changed_test_case_ids:
            session.findings[test_case_id] = [f for f in findings if f.owner_test_case_id == test_case_id]
        session.changed_test_case_ids.clear()

    return MagicMock(
        review_changed=AsyncMock(side_effect=review_changed),
        review_set=AsyncMock(),
        check_duplicates=AsyncMock(side_effect=_check_duplicates),
    )


def _generator(fix: Callable[[TestCaseDesignSession], None] = _fix) -> MagicMock:
    async def generate(session: TestCaseDesignSession, usage: RunUsage, usage_limits: UsageLimits) -> str:
        _generate(session)
        return "Generated DRAFT-1 (AC-1)."

    async def run_fix(session: TestCaseDesignSession, usage: RunUsage, usage_limits: UsageLimits) -> str:
        fix(session)
        return "fixed"

    return MagicMock(generate=AsyncMock(side_effect=generate), fix=AsyncMock(side_effect=run_fix))


@pytest.fixture
def agent() -> TestCaseDesignAgent:
    design_agent = TestCaseDesignAgent()
    design_agent.generator = _generator()
    design_agent.reviewer = _reviewer()
    design_agent.classification_agent = _delegate(lambda session: None, "labelled")
    return design_agent


@pytest.fixture
def client() -> Iterator[MagicMock]:
    mock_client = MagicMock(spec=TestManagementClientBase)
    mock_client.create_test_cases.return_value = ["PROJ-T1"]
    with patch("common.services.test_management_tools.get_test_management_client", return_value=mock_client):
        yield mock_client


@pytest.fixture
def jira() -> Iterator[list[dict[str, Any]]]:
    fetches: list[dict[str, Any]] = []

    def jira_get_issue(issue_key: str, fields: str = "", comment_limit: int = 10) -> dict[str, Any]:
        fetches.append({"issue_key": issue_key, "fields": fields, "comment_limit": comment_limit})
        return {"id": "10", "key": issue_key, "fields": {}}

    with patch.object(
        design_main, "build_atlassian_mcp_server_toolset", return_value=FunctionToolset([jira_get_issue])
    ) as build_toolset:
        yield fetches
    build_toolset.assert_called_with(("jira_get_issue",))


@pytest.fixture
def vector_db() -> MagicMock:
    return MagicMock(hybrid_search=AsyncMock(return_value=[]), upsert_batch=AsyncMock())


def _ctx(session: TestCaseDesignSession) -> SimpleNamespace:
    return SimpleNamespace(deps=session, usage=RunUsage())


def _generated() -> TestCaseDesignSession:
    session = TestCaseDesignSession(story_key="PROJ-1", story_content="{}")
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


async def test_a_converging_design_fetches_the_story_then_is_checked_for_duplicates_saved_classified_and_published(
    agent, client, jira, vector_db
):
    duplicate_checker = TestCaseReviewer()
    duplicate_checker.vector_db_service = vector_db
    agent.reviewer.check_duplicates = duplicate_checker.check_duplicates
    offered: list[set[str]] = []
    calls = [_FETCH, ("generate_test_cases", {}), ("review_test_cases", {}), ("publish_test_cases", {})]

    with agent.agent.override(model=_scripted_model(calls, offered)):
        response = await agent.run(_design_request())

    result = TestCaseDesignResult.model_validate_json(get_message_text(response))
    assert result.test_case_keys == ["PROJ-T1"]
    assert (result.iterations, result.stop_reason) == (1, DesignStopReason.CONVERGED)
    assert jira == [{"issue_key": "PROJ-1", "fields": "", "comment_limit": 0}]
    assert offered[0] - {"report_activity"} == {"jira_get_issue", "generate_test_cases", "review_test_cases"}
    assert offered[3] - {"report_activity"} == _DESIGN_TOOLS - {"fix_test_cases"}
    client.create_test_cases.assert_called_once()
    assert client.create_test_cases.call_args.args[1:] == ("PROJ", 10)
    comment = client.add_test_case_review_comment.call_args.args[1]
    assert "No duplicate test cases found." in comment
    client.change_test_case_status.assert_called_once_with("PROJ", "PROJ-T1", "Review Complete")
    vector_db.hybrid_search.assert_awaited_once()
    vector_db.upsert_batch.assert_not_awaited()
    classified, classification_deps, _ = agent.classification_agent.run_delegated.await_args.args
    assert classified.startswith("Test cases:\n```[{") and classified.endswith("}]```")
    assert '"key":"PROJ-T1"' in classified
    assert classification_deps == TestCaseKeys(issue_keys=["PROJ-T1"])


async def test_a_failure_before_the_writes_fails_the_design_and_writes_nothing(agent, client, jira):
    agent.generator.generate.side_effect = RuntimeError("model unavailable")

    with (
        agent.agent.override(model=_scripted_model([_FETCH, ("generate_test_cases", {})], [])),
        pytest.raises(AgentRuntimeError, match="model unavailable"),
    ):
        await agent.run(_design_request())

    client.create_test_cases.assert_not_called()


async def test_an_early_result_with_a_comment_aborts_the_design_without_further_requests(agent, client, jira):
    offered: list[set[str]] = []
    calls = [("generate_test_cases", {}), (None, {"llm_comments": "The Jira story PROJ-1 does not exist."})]

    with (
        agent.agent.override(model=_scripted_model(calls, offered)),
        pytest.raises(AgentRuntimeError, match=r"aborted \(The Jira story PROJ-1 does not exist\.\)") as failure,
    ):
        await agent.run(_design_request())

    assert "steps not done: finish the review loop; publish the test cases." in str(failure.value)
    assert len(offered) == 2, "The abort must end the run without another model request"
    client.create_test_cases.assert_not_called()


async def test_a_request_carrying_design_state_fails_before_any_step(agent, client):
    state = {"story_key": "PROJ-1", "stop_reason": "converged", "saved_test_case_keys": ["PROJ-T1"]}
    message = Message(message_id="m-1", parts=[new_text_part("Design PROJ-1"), new_data_part(state)])

    with (
        agent.agent.override(model=_scripted_model([("publish_test_cases", {})], [])),
        pytest.raises(AgentRuntimeError, match="Extra inputs are not permitted"),
    ):
        await agent.run(message)

    client.create_test_cases.assert_not_called()


def test_a_design_session_starts_empty_from_the_story_key_of_the_request(agent):
    assert agent._build_deps({"story_key": "PROJ-1"}) == TestCaseDesignSession(story_key="PROJ-1")


async def test_a_design_without_a_session_fails_with_a_clear_error(agent, jira):
    message = Message(message_id="m-1", parts=[new_text_part("Design PROJ-1")])

    with (
        agent.agent.override(model=_scripted_model([], [])),
        pytest.raises(AgentRuntimeError, match="structured data part"),
    ):
        await agent.run(message)


@pytest.mark.parametrize(
    ("issue", "content"),
    [
        ({"id": "10", "key": "PROJ-1"}, '{"id": "10", "key": "PROJ-1"}'),
        ('{\n  "id": 10,\n  "key": "PROJ-1"\n}', '{\n  "id": 10,\n  "key": "PROJ-1"\n}'),
    ],
    ids=["parsed by the client", "returned as text"],
)
async def test_the_fetched_story_is_stored_in_the_session_and_kept_out_of_the_model_context(issue, content):
    wrapped = MagicMock(call_tool=AsyncMock(return_value=issue))
    session = TestCaseDesignSession(story_key="PROJ-1")
    ctx = _ctx(session)
    args = {"issue_key": "PROJ-1", "comment_limit": 0}

    result = await design_main._StoryFetchingToolset(wrapped).call_tool("jira_get_issue", args, ctx, MagicMock())

    assert result == "Fetched the user story PROJ-1."
    assert (session.story_id, session.story_content) == (10, content)
    wrapped.call_tool.assert_awaited_once()


@pytest.mark.parametrize(
    ("issue_key", "story_content", "message"),
    [("PROJ-2", None, "Fetch only the user story PROJ-1"), ("PROJ-1", "{}", "already fetched")],
    ids=["another issue", "fetched twice"],
)
async def test_a_fetch_of_another_issue_or_a_second_fetch_is_refused(issue_key, story_content, message):
    wrapped = MagicMock(call_tool=AsyncMock())
    session = TestCaseDesignSession(story_key="PROJ-1", story_content=story_content)

    with pytest.raises(ModelRetry, match=message):
        await design_main._StoryFetchingToolset(wrapped).call_tool(
            "jira_get_issue", {"issue_key": issue_key}, _ctx(session), MagicMock()
        )

    wrapped.call_tool.assert_not_awaited()
    assert session.story_content == story_content


async def test_generation_needs_the_fetched_story_and_returns_its_summary(agent):
    session = TestCaseDesignSession(story_key="PROJ-1")
    ctx = _ctx(session)

    with pytest.raises(ModelRetry, match="Fetch the user story PROJ-1 first"):
        await agent.generate_test_cases(ctx)
    session.story_content = "{}"
    assert await agent.generate_test_cases(ctx) == "Generated DRAFT-1 (AC-1)."
    with pytest.raises(ModelRetry, match="already generated"):
        await agent.generate_test_cases(ctx)

    agent.generator.generate.assert_awaited_once_with(session, ctx.usage, agent.get_sub_agent_usage_limits())


def test_the_instructions_name_the_story_and_the_configured_additional_fields(monkeypatch):
    ctx = SimpleNamespace(deps=TestCaseDesignSession(story_key="PROJ-1"))
    monkeypatch.setattr(config, "JIRA_ADDITIONAL_FIELD_IDS", ())
    without_fields = design_main._story_instructions(ctx)
    monkeypatch.setattr(config, "JIRA_ADDITIONAL_FIELD_IDS", ("customfield_1",))
    with_fields = design_main._story_instructions(ctx)

    assert without_fields == "The key of the Jira user story of this design is PROJ-1."
    assert with_fields.startswith(f"{without_fields}\n\n")
    assert "customfield_1" in with_fields


async def test_review_without_blocking_findings_converges_without_a_duplicate_check(agent):
    session = _generated()
    agent.reviewer = _reviewer(_finding("DRAFT-1", TestCaseReviewFindingSeverity.LOW))
    ctx = _ctx(session)

    result = await agent.review_test_cases(ctx)

    assert (session.iteration, session.stop_reason) == (1, DesignStopReason.CONVERGED)
    assert result == "Finished (converged); publish next.", "Findings never go back to the model"
    assert session.duplicate_checks == {}
    limits = agent.get_sub_agent_usage_limits()
    for step in (agent.reviewer.review_changed, agent.reviewer.review_set):
        step.assert_awaited_once_with(session, ctx.usage, limits)
    agent.reviewer.check_duplicates.assert_not_awaited()


async def test_review_with_blocking_findings_continues_until_the_iteration_limit(agent):
    session = _generated()
    agent.max_iterations = 2
    agent.reviewer = _reviewer(_finding("DRAFT-1"))
    fix_ctx = _ctx(session)

    first = await agent.review_test_cases(_ctx(session))
    assert await agent.fix_test_cases(fix_ctx) == "fixed"
    second = await agent.review_test_cases(_ctx(session))

    assert first == "Review iteration 1: 1 blocking finding(s); fix next."
    assert second == "Finished (iteration_limit); publish next.", (
        "The iteration limit takes precedence over no progress"
    )
    assert (session.iteration, session.fixes, session.stop_reason) == (2, 1, DesignStopReason.ITERATION_LIMIT)
    agent.generator.fix.assert_awaited_once_with(session, fix_ctx.usage, agent.get_sub_agent_usage_limits())


@pytest.mark.parametrize(
    ("blocking_counts", "stop_reasons"),
    [
        ((2, 2), (None, DesignStopReason.NO_PROGRESS)),
        ((1, 2), (None, DesignStopReason.NO_PROGRESS)),
        ((2, 1, 1), (None, None, DesignStopReason.NO_PROGRESS)),
        ((2, 0), (None, DesignStopReason.CONVERGED)),
    ],
    ids=["same count", "more findings", "progress then none", "converged"],
)
async def test_the_loop_stops_without_progress_when_the_blocking_findings_do_not_fall(
    agent, blocking_counts, stop_reasons
):
    session = _generated()
    agent.max_iterations = 5
    counts = iter(blocking_counts)

    async def review_changed(design: TestCaseDesignSession, usage: RunUsage, usage_limits: UsageLimits) -> None:
        design.findings["DRAFT-1"] = [_finding("DRAFT-1") for _ in range(next(counts))]
        design.changed_test_case_ids.clear()

    agent.reviewer.review_changed.side_effect = review_changed
    reasons = []
    for _ in blocking_counts:
        await agent.review_test_cases(_ctx(session))
        reasons.append(session.stop_reason)
        if session.stop_reason is None:
            await agent.fix_test_cases(_ctx(session))

    assert tuple(reasons) == stop_reasons
    assert session.previous_blocking_count == blocking_counts[-1]


async def test_after_the_final_review_deleted_test_cases_named_by_open_gaps_are_restored(agent):
    session = _generated()
    agent.max_iterations = 1
    kept = DeletedTestCase(test_case=_test_case("Old"), findings=[_finding("DRAFT-9")], deleted_by=_finding("DRAFT-9"))
    session.deleted_test_cases = {"DRAFT-9": kept}
    gap = _finding(None).model_copy(
        update={"action": TestCaseReviewFindingAction.ADD_TEST_CASE, "related_test_case_ids": ["DRAFT-9"]}
    )
    other_gap = gap.model_copy(update={"related_test_case_ids": []})

    async def review_set(design: TestCaseDesignSession, usage: RunUsage, usage_limits: UsageLimits) -> None:
        design.suite_findings = [gap, other_gap]

    agent.reviewer.review_set.side_effect = review_set

    result = await agent.review_test_cases(_ctx(session))

    assert result == "Finished (iteration_limit); publish next."
    assert session.test_cases["DRAFT-9"] is kept.test_case
    assert session.findings["DRAFT-9"] == kept.findings
    assert session.deleted_test_cases == {}
    assert session.suite_findings == [other_gap]


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

    agent.reviewer.review_changed.assert_not_awaited()


async def test_fixing_twice_without_a_review_is_refused(agent):
    session = _generated()
    session.iteration, session.fixes = 1, 1

    with pytest.raises(ModelRetry, match="already fixed"):
        await agent.fix_test_cases(_ctx(session))

    agent.generator.fix.assert_not_awaited()


def _stopped() -> TestCaseDesignSession:
    session = _generated()
    session.story_id, session.iteration, session.stop_reason = 10, 1, DesignStopReason.CONVERGED
    session.add_draft(_test_case("Second"))
    session.duplicate_checks = {test_case_id: TestCaseDuplicateCheck() for test_case_id in session.test_cases}
    return session


def _recording(client: MagicMock, agent: TestCaseDesignAgent) -> list[str]:
    calls: list[str] = []
    keys = iter(["PROJ-T1", "PROJ-T2"])
    client.create_test_cases.side_effect = lambda test_cases, *_: (
        calls.append(f"upload {test_cases[0].name}") or [next(keys)]
    )
    client.add_test_case_review_comment.side_effect = lambda key, _: calls.append(f"feedback {key}")
    client.change_test_case_status.side_effect = lambda _, key, __: calls.append(f"status {key}")

    async def check_duplicates(session: TestCaseDesignSession, usage: RunUsage, usage_limits: UsageLimits) -> None:
        calls.append(f"duplicate check {sorted(set(session.test_cases) - set(session.duplicate_checks))}")
        await _check_duplicates(session, usage, usage_limits)

    async def classify(prompt: str, deps: TestCaseKeys, usage: RunUsage) -> str:
        calls.append(f"classify {deps.issue_keys}")
        return "labelled"

    agent.reviewer.check_duplicates.side_effect = check_duplicates
    agent.classification_agent.run_delegated.side_effect = classify
    return calls


async def test_publishing_checks_duplicates_saves_classifies_then_comments_and_sets_the_status_of_each_test_case(
    agent, client
):
    session = _stopped()
    session.duplicate_checks = {}
    calls = _recording(client, agent)

    assert await agent.publish_test_cases(_ctx(session)) == "Published 2 test case(s)."

    assert calls == [
        "duplicate check ['DRAFT-1', 'DRAFT-2']",
        "upload First",
        "upload Second",
        "classify ['PROJ-T1', 'PROJ-T2']",
        "feedback PROJ-T1",
        "status PROJ-T1",
        "feedback PROJ-T2",
        "status PROJ-T2",
    ]
    assert set(session.duplicate_checks) == session.saved_test_case_keys == {"PROJ-T1", "PROJ-T2"}
    assert (session.classified, session.published) == (True, True)


async def test_a_failed_duplicate_check_asks_to_publish_again_and_writes_nothing(agent, client):
    session = _stopped()
    agent.reviewer.check_duplicates.side_effect = TestCaseDuplicateCheckError("The duplicate check failed")

    with pytest.raises(ModelRetry, match=r"The duplicate check failed\. Publish the test cases again"):
        await agent.publish_test_cases(_ctx(session))

    client.create_test_cases.assert_not_called()
    assert not session.published


async def test_a_publish_interrupted_by_a_failed_write_resumes_after_the_last_completed_write(agent, client):
    session = _stopped()
    calls = _recording(client, agent)
    client.change_test_case_status.side_effect = RuntimeError("Zephyr is down")

    with pytest.raises(ModelRetry, match=r"Publishing failed: Zephyr is down\. Publish the test cases again to resume"):
        await agent.publish_test_cases(_ctx(session))
    assert not session.published
    calls.clear()
    client.change_test_case_status.side_effect = lambda _, key, __: calls.append(f"status {key}")
    await agent.publish_test_cases(_ctx(session))

    assert calls == ["duplicate check []", "status PROJ-T1", "feedback PROJ-T2", "status PROJ-T2"]
    assert [call.args[0] for call in client.add_test_case_review_comment.call_args_list] == ["PROJ-T1", "PROJ-T2"]
    assert session.published


async def test_a_publish_interrupted_by_a_failed_upload_resumes_without_saving_a_test_case_twice(agent, client):
    session = _stopped()
    calls = _recording(client, agent)
    keys = iter([["PROJ-T1"], RuntimeError("Zephyr is down"), ["PROJ-T2"]])

    def create(test_cases: list[DesignedTestCase], *_: object) -> list[str]:
        calls.append(f"upload {test_cases[0].name}")
        outcome = next(keys)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    client.create_test_cases.side_effect = create

    with pytest.raises(ModelRetry, match="Publishing failed: Zephyr is down"):
        await agent.publish_test_cases(_ctx(session))
    await agent.publish_test_cases(_ctx(session))

    assert [call for call in calls if call.startswith("upload")] == ["upload First", "upload Second", "upload Second"]
    assert session.saved_test_case_keys == {"PROJ-T1", "PROJ-T2"}
    assert session.published


async def test_a_failed_classification_is_not_turned_into_a_retry_of_the_publish(agent, client):
    session = _stopped()
    _recording(client, agent)
    agent.classification_agent.run_delegated.side_effect = RuntimeError("provider down")

    with pytest.raises(RuntimeError, match="provider down"):
        await agent.publish_test_cases(_ctx(session))

    client.add_test_case_review_comment.assert_not_called()


async def test_a_rerun_publish_resumes_without_a_second_upload_or_classification(agent, client):
    session = _stopped()
    calls = _recording(client, agent)
    await tools.upload_test_cases(session)
    session.classified = True
    calls.clear()

    await agent.publish_test_cases(_ctx(session))

    assert calls == ["duplicate check []", "feedback PROJ-T1", "status PROJ-T1", "feedback PROJ-T2", "status PROJ-T2"]


async def test_publishing_twice_is_refused_without_writing(agent, client):
    session = _stopped()
    session.published = True

    with pytest.raises(ModelRetry, match="already published"):
        await agent.publish_test_cases(_ctx(session))

    client.create_test_cases.assert_not_called()


async def test_publish_runs_alone_so_a_second_call_of_the_same_response_cannot_upload_again(agent, client, jira):
    responses = [
        [ToolCallPart(*_FETCH)],
        [ToolCallPart("generate_test_cases", {})],
        [ToolCallPart("review_test_cases", {})],
        [ToolCallPart("publish_test_cases", {}), ToolCallPart("publish_test_cases", {})],
    ]
    publish_sequential: list[bool] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        publish_sequential.extend(tool.sequential for tool in info.function_tools if tool.name == "publish_test_cases")
        step = sum(isinstance(message, ModelResponse) for message in messages)
        if step < len(responses):
            return ModelResponse(parts=responses[step])
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {})])

    with agent.agent.override(model=FunctionModel(respond)):
        await agent.run(_design_request())

    assert publish_sequential and all(publish_sequential)
    client.create_test_cases.assert_called_once()


async def test_the_design_tools_run_alone_so_a_second_review_of_the_same_response_finds_it_done(agent, client, jira):
    async def review_set(session: TestCaseDesignSession, usage: RunUsage, usage_limits: UsageLimits) -> None:
        # Suspends like a real model call, where two overlapping reviews would interleave.
        await asyncio.sleep(0)

    agent.reviewer = _reviewer(_finding("DRAFT-1"))
    agent.reviewer.review_set.side_effect = review_set
    responses = [
        [ToolCallPart(*_FETCH)],
        [ToolCallPart("generate_test_cases", {})],
        [ToolCallPart("review_test_cases", {}), ToolCallPart("review_test_cases", {})],
        [ToolCallPart("fix_test_cases", {})],
        [ToolCallPart("review_test_cases", {})],
        [ToolCallPart("publish_test_cases", {})],
    ]
    sequential: dict[str, bool] = {}

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        sequential.update({tool.name: tool.sequential for tool in info.function_tools})
        step = sum(isinstance(message, ModelResponse) for message in messages)
        if step < len(responses):
            return ModelResponse(parts=responses[step])
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {})])

    with agent.agent.override(model=FunctionModel(respond)):
        response = await agent.run(_design_request())

    result = TestCaseDesignResult.model_validate_json(get_message_text(response))
    assert (result.iterations, result.stop_reason) == (2, DesignStopReason.NO_PROGRESS)
    agent.generator.fix.assert_awaited_once()
    assert {name: sequential[name] for name in _DESIGN_TOOLS - {"jira_get_issue"}} == dict.fromkeys(
        _DESIGN_TOOLS - {"jira_get_issue"}, True
    )


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
    session.stop_reason, session.iteration = DesignStopReason.ITERATION_LIMIT, 4
    with pytest.raises(ModelRetry) as unpublished:
        design_main._complete_result(ctx, TestCaseDesignResult())
    session.test_cases = {"PROJ-T1": _test_case("First")}
    session.published = True
    result = design_main._complete_result(ctx, TestCaseDesignResult(llm_comments=None))

    assert str(refusal.value) == "The design is not complete yet: finish the review loop; publish the test cases."
    assert str(unpublished.value) == "The design is not complete yet: publish the test cases."
    assert json.loads(result.model_dump_json()) == {
        "llm_comments": None,
        "test_case_keys": ["PROJ-T1"],
        "iterations": 4,
        "stop_reason": "iteration_limit",
    }


def test_the_design_budget_covers_the_delegated_runs(agent):
    assert agent.get_total_tokens_limit() == 4_000_000
    assert agent.get_max_requests_per_task() == 150
    assert agent._get_usage_limits().request_limit is None


def test_shutting_the_design_agent_down_closes_the_reviewer(agent):
    agent.reviewer = MagicMock(close=AsyncMock())

    with TestClient(agent.a2a_server):
        agent.reviewer.close.assert_not_awaited()

    agent.reviewer.close.assert_awaited_once()
