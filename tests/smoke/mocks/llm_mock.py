# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Scripted OpenAI-compatible model standing in for every LLM of the hermetic smoke stack.

A request is attributed to the operation that sent it by the tools it offers and the shape of its output tool, and is
answered deterministically from the conversation so far: the next tool call of that operation's workflow, or its final
output built from the framework's own models. Every request is recorded at ``GET /__recorded``; one that matches no
operation is answered with HTTP 400 and recorded as unhandled, so a new LLM call fails the suite until it is scripted.
"""

import json
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import config
from common.models import (
    AcceptanceCriteriaItem,
    AcceptanceCriteriaList,
    AgentRoutingDecision,
    DesignedTestCase,
    DuplicateCandidate,
    DuplicateDetectionResult,
    GeneratedTestCases,
    IncidentCreationInput,
    IncidentCreationResult,
    OverlappingTestCase,
    RequirementsReviewFeedback,
    RoutingOutcome,
    SelectedAgents,
    TestCaseDesignResult,
    TestCaseDuplicateJudgement,
    TestCaseReviewFeedback,
    TestCaseReviewFinding,
    TestCaseReviewFindingAction,
    TestCaseReviewFindingSeverity,
    TestCaseType,
    TestExecutionResult,
    TestStep,
    TestStepResult,
    TestStepsSequence,
    TestStepsSequenceList,
    TestSuiteReview,
)

app = FastAPI()

OUTPUT_TOOL_NAME = "final_result"
# pydantic-ai ends every retry prompt with this sentence, so a tool result ending with it is a failed call.
RETRY_PROMPT_SUFFIX = "Fix the errors and try again."
CHARS_PER_TOKEN = 4

# One focus area per entry: as many as REQUIREMENTS_REVIEW_FOCUS_AREA_COUNT in docker-compose.smoke.yml allows.
FOCUS_AREA_FINDINGS = {
    "Reset link request": "The story does not say what the 'Forgot password' form shows for an unregistered email address.",
    "Reset link expiry": "The story does not say whether a reset link becomes invalid once it was used.",
    "Reset request rate limit": (
        "The attached reset policy allows at most 3 reset requests per account per hour, "
        "which no acceptance criterion covers."
    ),
}
RETRIEVAL_QUERY = "password reset link expiry policy"
STORY_FIELDS = ("summary", "description", "issuetype", "attachment")
LINK_TYPE = "Blocks"
CLASSIFICATION_LABELS = [TestCaseType.UI.label, "manual"]
ACCEPTANCE_CRITERIA = [
    AcceptanceCriteriaItem(
        id="AC-1",
        text=(
            "Submitting a registered email address on the 'Forgot password' form sends an email with a single-use "
            "password-reset link that is valid for 60 minutes."
        ),
        additional_info="The attached reset policy allows at most 3 reset requests per account per hour.",
    ),
    AcceptanceCriteriaItem(
        id="AC-2",
        text=(
            "Opening a reset link more than 60 minutes after it was sent shows the message 'This reset link has "
            "expired' and a 'Request a new link' button."
        ),
        additional_info="",
    ),
]
TEST_STEPS = {
    "AC-1": [
        TestStep(
            action="Open the 'Forgot password' form and submit the registered email address",
            expected_results="The form confirms that a password-reset email was sent",
            test_data=["Email: registered.user@example.com"],
        ),
        TestStep(
            action="Open the password-reset email in the mailbox of the registered email address",
            expected_results="The email contains a single-use password-reset link",
            test_data=[],
        ),
    ],
    "AC-2": [
        TestStep(
            action="Request a password-reset link for the registered email address",
            expected_results="A password-reset email with a reset link arrives",
            test_data=["Email: registered.user@example.com"],
        ),
        TestStep(
            action="Open the reset link 61 minutes after it was sent",
            expected_results="The message 'This reset link has expired' and a 'Request a new link' button are shown",
            test_data=["Delay: 61 minutes"],
        ),
    ],
}
TEST_CASE_NAMES = {
    "AC-1": "Reset link is emailed for a registered email address",
    "AC-2": "Expired reset link shows the expiry message",
}

_TASK_DESCRIPTION = re.compile(r'Target task description: "(?P<task>.*)"\.')
_REGISTERED_AGENT = re.compile(
    r"^- ID: (?P<id>[^,]+), Name: (?P<name>[^,]+), (?P<card>.*), Availability: (?P<availability>.+)$", re.MULTILINE
)
_EXECUTION_TASK_TEST_TYPE = re.compile(r"\(type: (?P<type>\w+)\)|following label: (?P<label>\w+)")
_ISSUE_KEY = re.compile(r"\b[A-Z][A-Z0-9_]*-\d+\b")
_CUSTOM_FIELD_ID = re.compile(r"\bcustomfield_\d+\b")
_FOCUS_AREA = re.compile(r"^Review focus area: (?P<focus_area>.+)$", re.MULTILINE)
_LABELLED_REVIEW = re.compile(r"Review focused on '[^']+':\n```(?P<review>.*?)```", re.DOTALL)
_TEST_CASE_UNDER_REVIEW = re.compile(r"Test case under review \(ID (?P<id>[^)]+)\)")
_TEST_CASE_TO_FIX = re.compile(r"Test case to fix \(ID [^)]+\):\n```(?P<test_case>.*?)```", re.DOTALL)
_TEST_STEP_SEQUENCES = re.compile(r"Test Step Sequences:\n(?P<sequences>\{.*\})", re.DOTALL)
_DUPLICATE_CANDIDATE = re.compile(r"^Candidate (?P<key>\S+):$", re.MULTILINE)
_TEST_CASE_KEY_FIELD = re.compile(r'"key":\s*"(?P<key>[^"]+)"')
_REPORT_STEP = re.compile(
    r"^Step \d+: (?P<description>.+?)$(?P<details>.*?)(?=^Step \d+: |\Z)", re.MULTILINE | re.DOTALL
)
_REPORT_LINES = {
    label: re.compile(rf"^\s*{label}:\s*(?P<value>.+)$", re.MULTILINE)
    for label in (
        "Overall status",
        "Execution started",
        "Execution ended",
        "Started",
        "Ended",
        "Expected",
        "Actual",
        "Error",
    )
}

_recorded: dict[str, list[dict]] = {"requests": [], "unhandled": []}


@dataclass(slots=True, frozen=True)
class _ToolResult:
    name: str
    arguments: dict
    content: str

    @property
    def succeeded(self) -> bool:
        return not self.content.endswith(RETRY_PROMPT_SUFFIX)


@dataclass(slots=True)
class _Conversation:
    system: str
    user_texts: list[str]
    tool_schemas: dict[str, dict]
    tool_results: list[_ToolResult] = field(default_factory=list)

    @property
    def prompt(self) -> str:
        """The first user message, which carries the operation's input."""
        return self.user_texts[0] if self.user_texts else ""

    @property
    def output_fields(self) -> set[str]:
        return set(self.tool_schemas.get(OUTPUT_TOOL_NAME, {}).get("properties", {}))

    def result_of(self, tool_name: str) -> str | None:
        """The content of the latest successful call of the tool, if any."""
        calls = self.succeeded_calls_of(tool_name)
        return calls[-1].content if calls else None

    def succeeded_calls_of(self, tool_name: str) -> list[_ToolResult]:
        return [result for result in self.tool_results if result.name == tool_name and result.succeeded]

    def last_succeeded_tool(self) -> str | None:
        succeeded = [result.name for result in self.tool_results if result.succeeded]
        return succeeded[-1] if succeeded else None


@dataclass(slots=True, frozen=True)
class _ToolCall:
    name: str
    arguments: dict


type _Answer = list[_ToolCall] | str


@dataclass(slots=True, frozen=True)
class _RegisteredAgent:
    id: str
    name: str
    card: str
    is_available: bool


def _text_of(content: object) -> str:
    """The text of a message content, which is a string or a list of typed parts of which only text ones count."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n\n".join(
            part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


def _parse(body: dict) -> _Conversation:
    calls_by_id: dict[str, tuple[str, dict]] = {}
    system_texts: list[str] = []
    user_texts: list[str] = []
    tool_results: list[_ToolResult] = []
    for message in body.get("messages", []):
        match message.get("role"):
            case "system" | "developer":
                system_texts.append(_text_of(message.get("content")))
            case "user":
                user_texts.append(_text_of(message.get("content")))
            case "assistant":
                for call in message.get("tool_calls") or []:
                    function = call["function"]
                    calls_by_id[call["id"]] = (function["name"], json.loads(function.get("arguments") or "{}"))
            case "tool":
                name, arguments = calls_by_id.get(message.get("tool_call_id", ""), ("", {}))
                tool_results.append(_ToolResult(name, arguments, _text_of(message.get("content"))))
    tool_schemas = {
        tool["function"]["name"]: tool["function"].get("parameters", {}) for tool in body.get("tools") or []
    }
    return _Conversation("\n\n".join(system_texts), user_texts, tool_schemas, tool_results)


def _final(output: BaseModel) -> _Answer:
    return [_ToolCall(OUTPUT_TOOL_NAME, output.model_dump(mode="json"))]


def _first_issue_key(text: str) -> str:
    match = _ISSUE_KEY.search(text)
    if match is None:
        raise ValueError(f"No issue key in {text[:200]!r}")
    return match.group(0)


def _story_fields(conversation: _Conversation) -> str:
    """The standard content fields plus every additional field ID the instructions name."""
    custom_field_ids = _CUSTOM_FIELD_ID.findall("\n".join([conversation.system, *conversation.user_texts]))
    return ",".join(dict.fromkeys([*STORY_FIELDS, *custom_field_ids]))


# --- Orchestrator -------------------------------------------------------------------------------------------------


def _registered_agents(conversation: _Conversation) -> list[_RegisteredAgent]:
    return [
        _RegisteredAgent(match["id"], match["name"], match["card"], match["availability"] == "available")
        for match in _REGISTERED_AGENT.finditer(conversation.prompt)
    ]


def _is_suitable(agent: _RegisteredAgent, task: str) -> bool:
    agent_by_task_prefix = {
        "Review the Jira user story": config.RequirementsReviewAgentConfig.OWN_NAME,
        "Design test cases for Jira user story": config.TestCaseDesignAgentConfig.OWN_NAME,
        "Create incident report for test case": config.IncidentCreationAgentConfig.OWN_NAME,
    }
    for prefix, agent_name in agent_by_task_prefix.items():
        if task.startswith(prefix):
            return agent.name == agent_name
    if match := _EXECUTION_TASK_TEST_TYPE.search(task):
        test_type = match["type"] or match["label"]
        description = f"{agent.name}, {agent.card}"
        return "test execution" in description.casefold() and bool(
            re.search(rf"\b{re.escape(test_type)}\b", description, re.IGNORECASE)
        )
    return False


def _suitable_agents(conversation: _Conversation) -> tuple[str, list[_RegisteredAgent]]:
    match = _TASK_DESCRIPTION.search(conversation.prompt)
    task = match["task"] if match else ""
    return task, [agent for agent in _registered_agents(conversation) if _is_suitable(agent, task)]


def _route(conversation: _Conversation) -> _Answer:
    task, suitable = _suitable_agents(conversation)
    available = [agent for agent in suitable if agent.is_available]
    if available:
        return _final(
            AgentRoutingDecision(
                selected_agent_id=available[0].id,
                outcome=RoutingOutcome.AGENT_SELECTED,
                justification=f"'{available[0].name}' declares the skill the task '{task}' needs and is available.",
            )
        )
    if suitable:
        return _final(
            AgentRoutingDecision(
                outcome=RoutingOutcome.SUITABLE_BUT_BUSY,
                justification=f"Every agent able to handle the task '{task}' is busy.",
            )
        )
    return _final(
        AgentRoutingDecision(
            outcome=RoutingOutcome.NONE_SUITABLE, justification=f"No registered agent declares a skill for '{task}'."
        )
    )


def _route_to_all(conversation: _Conversation) -> _Answer:
    task, suitable = _suitable_agents(conversation)
    available_ids = [agent.id for agent in suitable if agent.is_available]
    justification = "" if available_ids else f"No available agent declares a skill for '{task}'."
    return _final(SelectedAgents(ids=available_ids, justification=justification))


def _report_value(label: str, text: str) -> str:
    match = _REPORT_LINES[label].search(text)
    return match["value"].strip() if match else ""


def _extract_results(conversation: _Conversation) -> _Answer:
    report = conversation.prompt
    step_results = [
        TestStepResult(
            stepDescription=step["description"].strip(),
            testData=[],
            expectedResults=_report_value("Expected", step["details"]),
            actualResults=_report_value("Actual", step["details"]),
            success=not _report_value("Error", step["details"]),
            errorMessage=_report_value("Error", step["details"]),
            executionStartTimestamp=_report_value("Started", step["details"]) or None,
            executionEndTimestamp=_report_value("Ended", step["details"]) or None,
        )
        for step in _REPORT_STEP.finditer(report)
    ]
    is_failed = _report_value("Overall status", report).upper() == "FAILED"
    return _final(
        TestExecutionResult(
            stepResults=step_results,
            testCaseKey="",
            testCaseName="",
            testExecutionStatus="failed" if is_failed else "passed",
            generalErrorMessage="",
            start_timestamp=_report_value("Execution started", report),
            end_timestamp=_report_value("Execution ended", report),
        )
    )


# --- Requirements review ------------------------------------------------------------------------------------------


def _review_requirements(conversation: _Conversation) -> _Answer:
    issue_key = _first_issue_key(conversation.prompt)
    issue = conversation.result_of("jira_get_issue")
    if issue is None:
        return [_ToolCall("jira_get_issue", {"issue_key": issue_key, "fields": _story_fields(conversation)})]
    review_tool = next(name for name in conversation.tool_schemas if name.startswith("_review_with"))
    review = conversation.result_of(review_tool)
    if review is None:
        arguments = {"jira_issue_key": issue_key, "jira_issue_content": issue, "focus_areas": list(FOCUS_AREA_FINDINGS)}
        if "retrieval_query" in conversation.tool_schemas[review_tool].get("properties", {}):
            arguments["retrieval_query"] = RETRIEVAL_QUERY
        return [_ToolCall(review_tool, arguments)]
    feedback = RequirementsReviewFeedback.model_validate_json(review)
    if conversation.result_of("add_jira_comment") is None:
        return [_ToolCall("add_jira_comment", {"issue_key": issue_key, "comment": feedback.suggested_improvements})]
    return _final(feedback)


def _review_focus_area(conversation: _Conversation) -> _Answer:
    focus_area = _FOCUS_AREA.search(conversation.prompt)["focus_area"].strip()
    finding = FOCUS_AREA_FINDINGS.get(focus_area, f"The story leaves the expected behaviour of '{focus_area}' open.")
    return _final(RequirementsReviewFeedback(suggested_improvements=f"**{focus_area}**\n- {finding}"))


def _merge_reviews(conversation: _Conversation) -> _Answer:
    reviews = [match["review"].strip() for match in _LABELLED_REVIEW.finditer(conversation.prompt)]
    return _final(RequirementsReviewFeedback(suggested_improvements="\n\n".join(reviews)))


# --- Test case design ---------------------------------------------------------------------------------------------


def _design_test_cases(conversation: _Conversation) -> _Answer:
    if conversation.result_of("jira_get_issue") is None:
        story_key = _first_issue_key(conversation.prompt)
        return [
            _ToolCall(
                "jira_get_issue", {"issue_key": story_key, "fields": _story_fields(conversation), "comment_limit": 0}
            )
        ]
    if conversation.result_of("generate_test_cases") is None:
        return [_ToolCall("generate_test_cases", {})]
    if "publish_test_cases" in conversation.tool_schemas:
        if conversation.result_of("publish_test_cases") is None:
            return [_ToolCall("publish_test_cases", {})]
        return _final(TestCaseDesignResult())
    if "fix_test_cases" in conversation.tool_schemas and conversation.last_succeeded_tool() == "review_test_cases":
        return [_ToolCall("fix_test_cases", {})]
    return [_ToolCall("review_test_cases", {})]


def _extract_acceptance_criteria(_conversation: _Conversation) -> _Answer:
    return _final(AcceptanceCriteriaList(items=ACCEPTANCE_CRITERIA))


def _generate_test_steps(_conversation: _Conversation) -> _Answer:
    return _final(
        TestStepsSequenceList(
            items=[TestStepsSequence(ac_id=ac_id, steps=steps) for ac_id, steps in TEST_STEPS.items()]
        )
    )


def _create_test_cases(conversation: _Conversation) -> _Answer:
    sequences = TestStepsSequenceList.model_validate_json(_TEST_STEP_SEQUENCES.search(conversation.prompt)["sequences"])
    test_cases = [
        DesignedTestCase(
            key=None,
            labels=[],
            name=TEST_CASE_NAMES.get(sequence.ac_id, f"Verify {sequence.ac_id}"),
            summary=f"Verifies {sequence.ac_id} of the password reset story.",
            comment="",
            preconditions="A user account is registered with the email address registered.user@example.com.",
            steps=sequence.steps,
            parent_issue_key=None,
            ac_ids=[sequence.ac_id],
        )
        for sequence in sequences.items
    ]
    return _final(GeneratedTestCases(test_cases=test_cases))


def _fix_test_case(conversation: _Conversation) -> _Answer:
    test_case = DesignedTestCase.model_validate_json(_TEST_CASE_TO_FIX.search(conversation.prompt)["test_case"])
    first_step, *other_steps = test_case.steps
    precise_step = first_step.model_copy(
        update={"expected_results": f"{first_step.expected_results}, naming the exact screen and message shown"}
    )
    return _final(test_case.model_copy(update={"steps": [precise_step, *other_steps]}))


def _review_test_case(conversation: _Conversation) -> _Answer:
    """Reports one high finding per review, so the design's review loop always runs up to its iteration limit."""
    test_case_id = _TEST_CASE_UNDER_REVIEW.search(conversation.prompt)["id"]
    finding = TestCaseReviewFinding(
        owner_test_case_id=test_case_id,
        action=TestCaseReviewFindingAction.MODIFY,
        severity=TestCaseReviewFindingSeverity.HIGH,
        category="imprecise expected result",
        description="The expected result of the first step names no observable outcome, so a tester could pass it "
        "without the reset email ever being sent.",
        suggested_fix="State the exact confirmation message and that the email arrives in the registered mailbox.",
    )
    return _final(TestCaseReviewFeedback(findings=[finding]))


def _review_test_suite(_conversation: _Conversation) -> _Answer:
    return _final(TestSuiteReview(findings=[]))


def _judge_duplicates(conversation: _Conversation) -> _Answer:
    candidate_keys = [match["key"] for match in _DUPLICATE_CANDIDATE.finditer(conversation.prompt)]
    overlapping = [
        OverlappingTestCase(
            test_case_key=key,
            overlap_explanation="Both test cases request a password reset for a registered email address.",
            fully_covers=False,
        )
        for key in candidate_keys[:1]
    ]
    return _final(TestCaseDuplicateJudgement(overlapping_test_cases=overlapping))


def _classify_test_cases(conversation: _Conversation) -> _Answer:
    labelled = {
        result.arguments.get("test_case_key") for result in conversation.succeeded_calls_of("add_labels_to_test_case")
    }
    keys = dict.fromkeys(match["key"] for match in _TEST_CASE_KEY_FIELD.finditer(conversation.prompt))
    pending = [key for key in keys if key not in labelled]
    if not pending:
        return f"Classified {len(keys)} test case(s)."
    return [
        _ToolCall("add_labels_to_test_case", {"test_case_key": key, "labels": CLASSIFICATION_LABELS}) for key in pending
    ]


# --- Incident creation --------------------------------------------------------------------------------------------


def _incident_input(conversation: _Conversation) -> IncidentCreationInput:
    text = conversation.prompt
    return IncidentCreationInput.model_validate_json(text[text.index("{") : text.rindex("}") + 1])


def _duplicate_candidates(search_result: str) -> list[DuplicateCandidate]:
    # pydantic-ai hands an empty list back as an empty tool result.
    if not search_result.strip():
        return []
    return [
        DuplicateCandidate(
            issue_id=str(issue["id"]), key=issue["key"], content=f"{issue['summary']}\n{issue['description']}"
        )
        for issue in json.loads(search_result)
    ]


def _bug_description(incident: IncidentCreationInput) -> str:
    failed_steps = [step for step in incident.test_step_results if not step.success]
    failed_step = failed_steps[0] if failed_steps else None
    reproduction = [f"{number}. {step.action}" for number, step in enumerate(incident.test_case.steps, start=1)]
    return "\n".join(
        [
            f"Description: the automated test case {incident.test_case.key} failed: {incident.test_execution_result}",
            f"Environment details: {incident.system_description}",
            "Steps to reproduce:",
            *reproduction,
            f"Expected result: {failed_step.expectedResults if failed_step else 'every step passes'}",
            f"Actual result: {failed_step.actualResults if failed_step else incident.test_execution_result}",
        ]
    )


def _create_incident(conversation: _Conversation) -> _Answer:
    incident = _incident_input(conversation)
    search_result = conversation.result_of("_search_duplicate_candidates_in_rag")
    if search_result is None:
        return [
            _ToolCall("_get_linked_issues", {"test_case_key": incident.test_case.key}),
            _ToolCall(
                "_search_duplicate_candidates_in_rag",
                {"incident_description": _bug_description(incident), "project_key": incident.project_key},
            ),
        ]
    if conversation.result_of("_check_all_duplicates") is None:
        candidates = [candidate.model_dump(mode="json") for candidate in _duplicate_candidates(search_result)]
        return [
            _ToolCall(
                "_check_all_duplicates", {"input_data": incident.model_dump(mode="json"), "candidates": candidates}
            )
        ]
    created = conversation.result_of("jira_create_issue")
    if created is None:
        return [
            _ToolCall(
                "jira_create_issue",
                {
                    "project_key": incident.project_key,
                    "summary": f"[Password reset] - {incident.test_case.name} fails",
                    "issue_type": "Bug",
                    "description": _bug_description(incident),
                    "additional_fields": json.dumps({incident.issue_priority_field_id: {"name": "High"}}),
                },
            )
        ]
    issue = json.loads(created)
    if conversation.result_of("_link_issue_to_test_case") is None:
        return [
            _ToolCall(
                "_link_issue_to_test_case",
                {"test_case_key": incident.test_case.key, "issue_id": int(issue["id"]), "link_type": LINK_TYPE},
            ),
            _ToolCall("_save_artifacts", {}),
        ]
    return _final(IncidentCreationResult(incident_id=int(issue["id"]), incident_key=issue["key"], duplicates=[]))


def _detect_duplicates(_conversation: _Conversation) -> _Answer:
    return _final(
        DuplicateDetectionResult(duplicates=[], message="The new incident duplicates none of the candidates.")
    )


# --- Dispatch -----------------------------------------------------------------------------------------------------

_OPERATION_BY_TOOL = {
    "add_jira_comment": "requirements_review",
    "generate_test_cases": "test_case_design",
    "add_labels_to_test_case": "test_case_classification",
    "_search_duplicate_candidates_in_rag": "incident_creation",
}
_OPERATION_BY_OUTPUT_FIELD = {
    "selected_agent_id": "routing",
    "ids": "multi_routing",
    "stepResults": "results_extraction",
    "overlapping_test_cases": "test_case_duplicate_judgement",
    "ac_ids": "test_case_fixing",
    "test_cases": "test_case_creation",
    "duplicates": "duplicate_detection",
}
_HANDLERS: dict[str, Callable[[_Conversation], _Answer]] = {
    "routing": _route,
    "multi_routing": _route_to_all,
    "results_extraction": _extract_results,
    "requirements_review": _review_requirements,
    "focused_requirements_review": _review_focus_area,
    "requirements_review_merge": _merge_reviews,
    "test_case_design": _design_test_cases,
    "acceptance_criteria_extraction": _extract_acceptance_criteria,
    "test_steps_generation": _generate_test_steps,
    "test_case_creation": _create_test_cases,
    "test_case_fixing": _fix_test_case,
    "test_case_review": _review_test_case,
    "test_suite_review": _review_test_suite,
    "test_case_duplicate_judgement": _judge_duplicates,
    "test_case_classification": _classify_test_cases,
    "incident_creation": _create_incident,
    "duplicate_detection": _detect_duplicates,
}


def _operation_of(conversation: _Conversation) -> str | None:
    """The operation that sent the request: by a tool only it offers, else by the fields of its output."""
    for tool_name, operation in _OPERATION_BY_TOOL.items():
        if tool_name in conversation.tool_schemas:
            return operation
    fields = conversation.output_fields
    for output_field, operation in _OPERATION_BY_OUTPUT_FIELD.items():
        if output_field in fields:
            return operation
    if "suggested_improvements" in fields:
        is_focused = _FOCUS_AREA.search(conversation.prompt) is not None
        return "focused_requirements_review" if is_focused else "requirements_review_merge"
    if "findings" in fields:
        return "test_case_review" if _TEST_CASE_UNDER_REVIEW.search(conversation.prompt) else "test_suite_review"
    if "items" in fields:
        item_schema = conversation.tool_schemas[OUTPUT_TOOL_NAME]["properties"]["items"].get("items", {})
        return (
            "test_steps_generation"
            if "ac_id" in item_schema.get("properties", {})
            else "acceptance_criteria_extraction"
        )
    return None


def _completion(body: dict, answer: _Answer) -> dict:
    if isinstance(answer, str):
        message: dict = {"role": "assistant", "content": answer}
        finish_reason = "stop"
    else:
        tool_calls = [
            {
                "id": f"call_{uuid.uuid4().hex}",
                "type": "function",
                "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
            }
            for call in answer
        ]
        message = {"role": "assistant", "content": None, "tool_calls": tool_calls}
        finish_reason = "tool_calls"
    prompt_tokens = len(json.dumps(body.get("messages", []))) // CHARS_PER_TOKEN
    completion_tokens = len(json.dumps(message)) // CHARS_PER_TOKEN
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.get("model", ""),
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> JSONResponse:
    body = await request.json()
    conversation = _parse(body)
    operation = _operation_of(conversation)
    _recorded["requests"].append(
        {
            "operation": operation,
            "system": conversation.system,
            "user": conversation.user_texts,
            "tools": sorted(conversation.tool_schemas),
        }
    )
    if operation is None:
        signature = {"tools": sorted(conversation.tool_schemas), "output_fields": sorted(conversation.output_fields)}
        _recorded["unhandled"].append(signature)
        return JSONResponse(
            status_code=400,
            content={"error": {"message": f"No scripted answer for {signature}", "type": "invalid_request_error"}},
        )
    return JSONResponse(_completion(body, _HANDLERS[operation](conversation)))


@app.get("/__recorded")
async def recorded() -> dict:
    return _recorded
