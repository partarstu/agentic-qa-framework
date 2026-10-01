# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import asyncio
from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import ModelRetry
from pydantic_ai.messages import BinaryContent, ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RunUsage, UsageLimits

from agents.test_case_generation import main as generation_main
from agents.test_case_generation.main import TestCaseGenerator
from common.models import (
    AcceptanceCriteriaItem,
    AcceptanceCriteriaList,
    DeletedTestCase,
    DesignedTestCase,
    FindingAction,
    FindingSeverity,
    GeneratedTestCases,
    PreviousReview,
    ReviewFinding,
    TestCaseDesignSession,
    TestStepsSequenceList,
)

_USAGE_LIMITS = UsageLimits(request_limit=None, total_tokens_limit=1_000)
_CRITERIA = [AcceptanceCriteriaItem(id=f"AC-{n}", text=f"Criterion {n}", additional_info="") for n in (1, 2)]
_CRITERIA_PART = f"Acceptance criteria:\n```{AcceptanceCriteriaList(items=_CRITERIA).model_dump_json()}```"


@pytest.fixture
def mock_config() -> Iterator[MagicMock]:
    with patch("agents.test_case_generation.main.config") as mock_conf:
        mock_conf.TestCaseGenerationAgentConfig.MODEL_NAME = "test"
        mock_conf.TestCaseGenerationAgentConfig.THINKING_LEVEL = "MEDIUM"
        mock_conf.TestCaseGenerationAgentConfig.MAX_OUTPUT_TOKENS = None
        mock_conf.TestCaseDesignAgentConfig.FIX_MIN_SEVERITY = "medium"
        yield mock_conf


@pytest.fixture
def generator(mock_config: MagicMock) -> TestCaseGenerator:
    return TestCaseGenerator()


def _test_case(name: str, key: str | None = None, ac_ids: tuple[str, ...] = ("AC-1",)) -> DesignedTestCase:
    return DesignedTestCase(
        key=key, labels=[], name=name, summary=f"Summary of {name}", comment="", preconditions=None, steps=[],
        parent_issue_key="PROJ-1", ac_ids=list(ac_ids),
    )  # fmt: skip


def _session(*names: str) -> TestCaseDesignSession:
    session = TestCaseDesignSession(
        story_key="PROJ-1", story_id=10, story_content="Story content", attachments={}, acceptance_criteria=_CRITERIA
    )
    for name in names:
        session.add_draft(_test_case(name))
    session.changed_test_case_ids.clear()
    return session


def _finding(
    owner: str | None,
    action: FindingAction = FindingAction.MODIFY,
    severity: FindingSeverity = FindingSeverity.HIGH,
    description: str = "A problem",
    related: list[str] | None = None,
) -> ReviewFinding:
    return ReviewFinding(
        owner_test_case_id=owner,
        action=action,
        severity=severity,
        category="coverage",
        description=description,
        suggested_fix="A fix",
        related_test_case_ids=related or [],
    )


_ADD = FindingAction.ADD_TEST_CASE
_DELETE = FindingAction.DELETE_TEST_CASE
_REMOVE_STEPS = FindingAction.REMOVE_DUPLICATE_STEPS


def _fixer_returning(*test_cases: DesignedTestCase) -> AsyncMock:
    return AsyncMock(side_effect=[MagicMock(output=test_case) for test_case in test_cases])


def test_an_unknown_fix_severity_fails_at_start(mock_config):
    mock_config.TestCaseDesignAgentConfig.FIX_MIN_SEVERITY = "urgent"

    with pytest.raises(ValueError, match="urgent"):
        TestCaseGenerator()


async def test_generation_stores_the_criteria_and_adds_the_test_cases_as_drafts(generator):
    generator.ac_extractor_agent.run = AsyncMock(return_value=MagicMock(output=AcceptanceCriteriaList(items=_CRITERIA)))
    generator.steps_generator_agent.run = AsyncMock(return_value=MagicMock(output=TestStepsSequenceList(items=[])))
    generated = GeneratedTestCases(test_cases=[_test_case("First"), _test_case("Second", ac_ids=("AC-2",))])
    generator.test_case_creator_agent.run = AsyncMock(return_value=MagicMock(output=generated))
    policy = BinaryContent(data=b"At most 3 reset requests per hour.", media_type="text/plain", identifier="policy.md")
    session = TestCaseDesignSession(story_key="PROJ-1", story_content="Story content")
    usage = RunUsage()

    with patch("common.services.jira_attachments.download_issue_attachments", return_value={"policy.md": policy}):
        await generator.generate(session, usage, _USAGE_LIMITS)

    assert session.acceptance_criteria == _CRITERIA
    assert {key: test_case.name for key, test_case in session.test_cases.items()} == {
        "DRAFT-1": "First",
        "DRAFT-2": "Second",
    }
    assert session.test_cases["DRAFT-2"].ac_ids == ["AC-2"]
    assert session.changed_test_case_ids == {"DRAFT-1", "DRAFT-2"}
    extraction = generator.ac_extractor_agent.run.await_args
    assert extraction.args[0] == ["Jira Issue content:\nStory content", "Attachment: policy.md", policy]
    assert "toolsets" not in extraction.kwargs
    story_context = ["Jira Issue content:\n```Story content```", _CRITERIA_PART, "Attachment: policy.md", policy]
    assert generator.steps_generator_agent.run.await_args.args[0] == story_context
    creation = generator.test_case_creator_agent.run.await_args
    assert creation.args[0][:-1] == story_context
    assert creation.args[0][-1].startswith("Test Step Sequences:\n")
    assert creation.kwargs["deps"] is session
    for run in (
        generator.ac_extractor_agent.run,
        generator.steps_generator_agent.run,
        generator.test_case_creator_agent.run,
    ):
        assert run.await_args.kwargs["usage"] is usage
        assert run.await_args.kwargs["usage_limits"] is _USAGE_LIMITS


def test_test_cases_tracing_to_unknown_criteria_are_rejected():
    ctx = SimpleNamespace(deps=_session())
    known = GeneratedTestCases(test_cases=[_test_case("First"), _test_case("Second", ac_ids=("AC-1", "AC-2"))])

    assert generation_main._require_known_ac_ids(ctx, known) is known
    with pytest.raises(ModelRetry, match=r"Unknown acceptance criteria IDs \['AC-9'\]; use only \['AC-1', 'AC-2'\]"):
        generation_main._require_known_ac_ids(ctx, GeneratedTestCases(test_cases=[_test_case("X", ac_ids=("AC-9",))]))
    with pytest.raises(ModelRetry, match="AC-7"):
        generation_main._require_known_ac_ids(ctx, _test_case("X", ac_ids=("AC-1", "AC-7")))


async def test_the_fixer_is_asked_again_when_its_test_case_traces_to_an_unknown_criterion(generator):
    answers = [_test_case("Fixed", ac_ids=("AC-9",)), _test_case("Fixed", ac_ids=("AC-2",))]

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, answers.pop(0).model_dump())])

    with generator.test_case_fixer_agent.override(model=FunctionModel(respond)):
        result = await generator.test_case_fixer_agent.run("Fix", deps=_session())

    assert result.output.ac_ids == ["AC-2"]
    assert answers == []


async def test_nothing_is_fixed_without_a_finding_at_or_above_the_threshold(generator):
    session = _session("First")
    session.findings = {"DRAFT-1": [_finding("DRAFT-1", severity=FindingSeverity.LOW)]}
    generator.test_case_fixer_agent.run = AsyncMock()

    result = await generator.fix(session, RunUsage(), _USAGE_LIMITS)

    assert "nothing to fix" in result
    generator.test_case_fixer_agent.run.assert_not_awaited()
    assert session.changed_test_case_ids == set()


async def test_a_fixer_gets_only_the_related_test_cases_and_its_previous_review_is_recorded(generator):
    session = _session("First", "Second", "Third")
    individual = [
        _finding("DRAFT-1", description="missing expected result"),
        _finding("DRAFT-1", severity=FindingSeverity.LOW, description="imprecise name"),
    ]
    session.findings = {"DRAFT-1": individual}
    session.suite_findings = [
        _finding("DRAFT-1", _REMOVE_STEPS, FindingSeverity.MEDIUM, "repeats DRAFT-2", related=["DRAFT-2"])
    ]
    before = session.test_cases["DRAFT-1"]
    generator.test_case_fixer_agent.run = _fixer_returning(_test_case("First fixed", key="stale"))
    usage = RunUsage()

    result = await generator.fix(session, usage, _USAGE_LIMITS)

    fixer_run = generator.test_case_fixer_agent.run.await_args
    message = fixer_run.args[0]
    assert message[:2] == ["Jira Issue content:\n```Story content```", _CRITERIA_PART]
    assert "Test case to fix (ID DRAFT-1)" in message[2]
    assert "missing expected result" in message[3]
    assert "repeats DRAFT-2" in message[3]
    assert "imprecise name" not in message[3]
    assert message[4] == (
        "Related test cases of the findings (context only):\n```ID DRAFT-2:\n"
        "Name: Second\nObjective: Summary of Second\nPreconditions: \nAcceptance criteria: AC-1```"
    )
    assert fixer_run.kwargs["deps"] is session
    assert fixer_run.kwargs["usage"] is usage
    assert fixer_run.kwargs["usage_limits"] is _USAGE_LIMITS
    assert session.test_cases["DRAFT-1"].name == "First fixed"
    assert session.test_cases["DRAFT-1"].key is None
    assert session.previous_reviews == {"DRAFT-1": PreviousReview(test_case=before, findings=individual)}
    assert session.changed_test_case_ids == {"DRAFT-1"}
    assert result == "Modified test cases: DRAFT-1; added: none; deleted: none; restored: none."


async def test_a_fixer_without_related_test_cases_gets_no_other_test_case(generator):
    session = _session("First", "Second")
    session.findings = {"DRAFT-1": [_finding("DRAFT-1")]}
    generator.test_case_fixer_agent.run = _fixer_returning(_test_case("First fixed"))

    await generator.fix(session, RunUsage(), _USAGE_LIMITS)

    message = generator.test_case_fixer_agent.run.await_args.args[0]
    assert len(message) == 4
    assert not any("DRAFT-2" in part for part in message)


async def test_a_deleted_test_case_is_kept_and_given_to_the_fixer_which_merges_it(generator):
    session = _session("First", "Second")
    deleted_findings = [_finding("DRAFT-2", description="also wrong")]
    session.findings = {"DRAFT-2": deleted_findings}
    deletion = _finding("DRAFT-2", _DELETE, related=["DRAFT-1"])
    session.suite_findings = [deletion, _finding("DRAFT-1", description="take over DRAFT-2", related=["DRAFT-2"])]
    second = session.test_cases["DRAFT-2"]
    generator.test_case_fixer_agent.run = _fixer_returning(_test_case("First merged"))

    result = await generator.fix(session, RunUsage(), _USAGE_LIMITS)

    message = generator.test_case_fixer_agent.run.await_args.args[0]
    assert message[4].startswith(
        "Related test cases of the findings (context only):\n```ID DRAFT-2 (deleted):\nName: Second\n"
    )
    assert set(session.test_cases) == {"DRAFT-1"}
    assert session.deleted_test_cases == {
        "DRAFT-2": DeletedTestCase(test_case=second, findings=deleted_findings, deleted_by=deletion)
    }
    assert "DRAFT-2" not in session.findings
    assert result == "Modified test cases: DRAFT-1; added: none; deleted: DRAFT-2; restored: none."


async def test_a_gap_naming_an_earlier_deleted_test_case_restores_it_without_a_fixer_run(generator):
    session = _session("First")
    old = _test_case("Old")
    session.deleted_test_cases = {
        "DRAFT-9": DeletedTestCase(test_case=old, findings=[], deleted_by=_finding("DRAFT-9", _DELETE))
    }
    session.suite_findings = [_finding(None, _ADD, description="AC-2 lost its coverage", related=["DRAFT-9"])]
    generator.test_case_fixer_agent.run = AsyncMock()

    result = await generator.fix(session, RunUsage(), _USAGE_LIMITS)

    generator.test_case_fixer_agent.run.assert_not_awaited()
    assert session.test_cases["DRAFT-9"] is old
    assert session.deleted_test_cases == {}
    assert session.changed_test_case_ids == {"DRAFT-9"}
    assert result == "Modified test cases: none; added: none; deleted: none; restored: DRAFT-9."


async def test_a_gap_never_undoes_a_deletion_of_the_same_review(generator):
    session = _session("First", "Second")
    session.suite_findings = [
        _finding("DRAFT-2", _DELETE),
        _finding(None, _ADD, description="AC-3 is not covered", related=["DRAFT-2"]),
    ]
    generator.test_case_fixer_agent.run = _fixer_returning(_test_case("Covers AC-3"))

    result = await generator.fix(session, RunUsage(), _USAGE_LIMITS)

    assert set(session.test_cases) == {"DRAFT-1", "DRAFT-3"}
    assert set(session.deleted_test_cases) == {"DRAFT-2"}
    assert result == "Modified test cases: none; added: DRAFT-3; deleted: DRAFT-2; restored: none."


async def test_each_adder_gets_all_test_cases_and_its_sibling_gaps(generator):
    session = _session("First", "Second")
    session.suite_findings = [
        _finding(None, _ADD, description="AC-3 is not covered"),
        _finding(None, _ADD, description="AC-4 is not covered"),
    ]
    generator.test_case_fixer_agent.run = _fixer_returning(_test_case("Covers AC-3"), _test_case("Covers AC-4"))

    result = await generator.fix(session, RunUsage(), _USAGE_LIMITS)

    first, second = (call.args[0] for call in generator.test_case_fixer_agent.run.await_args_list)
    assert "AC-3 is not covered" in first[2] and "AC-4 is not covered" in second[2]
    for message in (first, second):
        assert "ID DRAFT-1:\nName: First\n" in message[3] and "ID DRAFT-2:\nName: Second\n" in message[3]
        assert '"labels"' not in message[3], "Context test cases are compact text, not JSON"
    assert first[4].startswith("Other missing test cases, each created separately (never cover them):\n")
    assert "AC-4 is not covered" in first[4] and "AC-3 is not covered" not in first[4]
    assert "AC-3 is not covered" in second[4] and "AC-4 is not covered" not in second[4]
    assert result == "Modified test cases: none; added: DRAFT-3, DRAFT-4; deleted: none; restored: none."


async def test_a_single_gap_has_no_sibling_part(generator):
    session = _session("First")
    session.suite_findings = [_finding(None, _ADD, description="AC-3 is not covered")]
    generator.test_case_fixer_agent.run = _fixer_returning(_test_case("Covers AC-3"))

    await generator.fix(session, RunUsage(), _USAGE_LIMITS)

    assert len(generator.test_case_fixer_agent.run.await_args.args[0]) == 4


async def test_a_repeated_fix_finds_nothing_left_to_fix(generator):
    session = _session("First")
    low = _finding("DRAFT-1", severity=FindingSeverity.LOW, description="imprecise name")
    session.findings = {"DRAFT-1": [_finding("DRAFT-1"), low]}
    session.suite_findings = [_finding(None, FindingAction.ADD_TEST_CASE, description="AC-3 is not covered")]
    generator.test_case_fixer_agent.run = _fixer_returning(_test_case("First fixed"), _test_case("Covers AC-3"))

    await generator.fix(session, RunUsage(), _USAGE_LIMITS)
    repeated = await generator.fix(session, RunUsage(), _USAGE_LIMITS)

    assert "nothing to fix" in repeated
    assert generator.test_case_fixer_agent.run.await_count == 2
    assert set(session.test_cases) == {"DRAFT-1", "DRAFT-2"}
    assert session.findings == {"DRAFT-1": [low]}
    assert session.suite_findings == []


async def test_the_first_fix_runs_alone_and_the_others_concurrently(generator):
    session = _session("First", "Second", "Third")
    session.findings = {f"DRAFT-{n}": [_finding(f"DRAFT-{n}")] for n in (1, 2, 3)}
    events: list[str] = []
    others_started = asyncio.Event()

    async def fix(message: list, **kwargs) -> MagicMock:
        test_case_id = message[2].split("(ID ")[1].split(")")[0]
        events.append(f"start {test_case_id}")
        if test_case_id != "DRAFT-1":
            if events.count("start DRAFT-2") + events.count("start DRAFT-3") == 2:
                others_started.set()
            await asyncio.wait_for(others_started.wait(), timeout=1)
        events.append(f"end {test_case_id}")
        return MagicMock(output=_test_case(f"Fixed {test_case_id}"))

    generator.test_case_fixer_agent.run = fix

    await generator.fix(session, RunUsage(), _USAGE_LIMITS)

    assert events[:2] == ["start DRAFT-1", "end DRAFT-1"]
    assert set(events[2:4]) == {"start DRAFT-2", "start DRAFT-3"}
    assert {key: test_case.name for key, test_case in session.test_cases.items()} == {
        "DRAFT-1": "Fixed DRAFT-1",
        "DRAFT-2": "Fixed DRAFT-2",
        "DRAFT-3": "Fixed DRAFT-3",
    }
