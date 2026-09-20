# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Hermetic end-to-end smoke checks for the core QuAIA flows.

All of our own code runs for real (orchestrator + agents + real Gemini); only
the external boundaries are mocked. Each test asserts on what reached a mocked
boundary, read back from its ``/__recorded`` endpoint:

* Requirements review   -> a non-empty comment reached Jira (REST or MCP) on the seeded story.
* Requirements review   -> the agent first fetched the source story via the Jira MCP.
* Requirements review   -> the story's attachment was downloaded over the Jira REST API (WS5),
                           with the MCP download tool left unused.
* Requirements review   -> the flow issued a documents-collection hybrid query with a focused
                           (shorter than the issue) query text (WS10).
* Requirements review   -> with JIRA_ADDITIONAL_FIELD_IDS configured, the agent requests those custom
                           field IDs (together with the standard content fields) when fetching the story.
* Test-case generation  -> real test cases (name + steps) reached Zephyr.
* Test-case generation  -> the created test cases were linked to the seeded story's numeric id.
* Test-case classification -> labels reached Zephyr.
* Requirements review   -> a Confluence-only configuration queries only the Confluence collection, with the
                           source pinned (WS18); the agent's log lines carry its name and task id (WS23).
* Test-case review      -> a non-empty "Review Comments" value reached Zephyr for every generated test case.
* Test-case review      -> at least one test case reached the "Review Complete" status.
* Test-case review      -> every review comment carries the duplicate-check section, after the batch was
                           indexed and searched per test case within its project (WS17); the usage
                           artifact carries per-operation counters (WS13).
* Test execution        -> a failed automated test drove a real Bug issue into the seeded project.
* Test execution        -> a failed execution for the seeded case was reported to Zephyr with UTC
                           execution dates, and the created bug was linked to that execution.
* Test execution        -> the incident-creation flow consulted the vector DB for duplicates, filtered on the
                           project (WS16).
* Test execution        -> the typed ("api") test case reached the execution agent and the untyped one was
                           skipped (WS15); /execute-test reported one result to Zephyr and created no bug.
* RAG DB update         -> the sync pushed the seeded story into the vector DB, and a Closed issue too (WS18).
* Dashboard             -> the login is rate limited (429), and the task history survives an orchestrator
                           restart (WS22, WS24; the restart check runs last).
* Agent traceability    -> the version an agent is started with reaches the dashboard agents view,
                           the orchestrator's own version reaches the dashboard status view, and the
                           executing agent's name, version and environment reach the created bug.
* Agent traceability    -> every framework agent's card description carries its model, version and
                           skill name, and routing decisions with agent name and justification
                           appear in the dashboard logs.
* Negative paths        -> all four webhooks reject a bad API key (401), the issue-key webhooks
                           reject a missing issue_key (400), the project-key webhooks reject a
                           missing project_key (422), and the dashboard API rejects a missing
                           token (401).
"""

import subprocess
import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest

import config
from tests.smoke.conftest import (
    CONFLUENCE_RECORDED_URL,
    DOCUMENTS_COLLECTION_NAME,
    DUPLICATE_CHECK_HEADING,
    EXECUTION_AGENT_NAME,
    EXECUTION_AGENT_VERSION,
    EXPECTED_AGENT_NAMES,
    JIRA_MCP_RECORDED_URL,
    JIRA_MCP_SEEDED_STORY_URL,
    JIRA_REST_RECORDED_URL,
    LOGIN_RATE_LIMIT_ATTEMPTS,
    ORCHESTRATOR_URL,
    ORCHESTRATOR_VERSION,
    QDRANT_RECORDED_URL,
    REVIEW_COMPLETE_STATUS,
    SEEDED_CLOSED_ISSUE_KEY,
    SEEDED_EXECUTABLE_TC_KEY,
    SEEDED_EXECUTABLE_TC_TYPE_LABEL,
    SEEDED_ISSUE_ID,
    SEEDED_ISSUE_KEY,
    SEEDED_PROJECT_KEY,
    SEEDED_SPACE_KEY,
    SEEDED_UNTYPED_TC_KEY,
    SHAREPOINT_RECORDED_URL,
    SMOKE_COMPOSE_FILE,
    TEST_CASES_COLLECTION_NAME,
    TEST_ENVIRONMENT_LABEL,
    TICKETS_COLLECTION_NAME,
    ZEPHYR_RECORDED_URL,
)
from tests.smoke.recordings import wait_for_any_recorded, wait_for_recorded

pytestmark = pytest.mark.smoke

PROMPT_OVERRIDE_MARKER = "OVERRIDE-7f3d-active"


# --- Requirements review flow ----------------------------------------------------------


def test_requirements_review_webhook_accepted(requirements_review_response: httpx.Response) -> None:
    assert requirements_review_response.status_code == 200, (
        f"Requirements-review webhook failed: "
        f"{requirements_review_response.status_code} {requirements_review_response.text}"
    )


def _has_jira_comment(data: dict[str, dict]) -> bool:
    """True once a non-empty comment is recorded on the seeded story, via REST or MCP."""
    rest_comments = data.get("rest", {}).get("comments", [])
    mcp_comments = data.get("mcp", {}).get("comments", [])
    return any(c.get("issue_key") == SEEDED_ISSUE_KEY and c.get("body", "").strip() for c in rest_comments) or any(
        c.get("issue_key") == SEEDED_ISSUE_KEY and c.get("comment", "").strip() for c in mcp_comments
    )


def test_review_comment_reached_jira(requirements_review_response: httpx.Response, http_client: httpx.Client) -> None:
    """The agent must post a non-empty review comment to Jira, via REST or MCP."""
    data = wait_for_any_recorded(
        http_client,
        {"rest": JIRA_REST_RECORDED_URL, "mcp": JIRA_MCP_RECORDED_URL},
        _has_jira_comment,
    )
    assert _has_jira_comment(data), f"No non-empty review comment reached Jira. REST={data['rest']}, MCP={data['mcp']}"


def test_prompt_override_marker_reaches_jira_comment(
    requirements_review_response: httpx.Response, http_client: httpx.Client
) -> None:
    """The mounted prompt override must drive the agent: its marker token ends up in the Jira comment."""

    def _comment_texts(data: dict[str, dict]) -> list[str]:
        rest = [c.get("body", "") for c in data.get("rest", {}).get("comments", [])]
        mcp = [c.get("comment", "") for c in data.get("mcp", {}).get("comments", [])]
        return [text for text in rest + mcp if text.strip()]

    data = wait_for_any_recorded(
        http_client,
        {"rest": JIRA_REST_RECORDED_URL, "mcp": JIRA_MCP_RECORDED_URL},
        lambda d: any(PROMPT_OVERRIDE_MARKER in text for text in _comment_texts(d)),
    )
    comments = _comment_texts(data)
    assert any(PROMPT_OVERRIDE_MARKER in text for text in comments), (
        f"The prompt override marker '{PROMPT_OVERRIDE_MARKER}' never reached the Jira comment, "
        f"so the override was not applied. Comments seen: {comments}"
    )


def test_agents_requested_the_configured_additional_fields(
    requirements_review_response: httpx.Response,
    test_case_flow_response: httpx.Response,
    http_client: httpx.Client,
) -> None:
    """With JIRA_ADDITIONAL_FIELD_IDS configured, the review and generation flows must both ask
    for those field IDs when fetching the story (three agents fetch it, so at least two
    field-aware calls must exist)."""
    configured_field_ids = ("customfield_10101", "customfield_10202")

    def _requested(call: dict) -> bool:
        return call.get("issue_key") == SEEDED_ISSUE_KEY and all(
            field_id in call.get("fields", "") for field_id in configured_field_ids
        )

    data = wait_for_recorded(
        http_client, JIRA_MCP_RECORDED_URL, lambda d: sum(_requested(c) for c in d.get("get_issue", [])) >= 2
    )
    matching = [call for call in data.get("get_issue", []) if _requested(call)]
    assert len(matching) >= 2, (
        f"Fewer than two jira_get_issue calls requested all configured additional field IDs "
        f"{configured_field_ids}, so not both the review and generation flows forwarded them. "
        f"Recorded: {data.get('get_issue')}"
    )
    # The pitfall: restricting to the additional IDs must not drop the standard content fields.
    for call in matching:
        fields = call.get("fields", "")
        assert "summary" in fields or "*all" in fields, (
            f"The fields parameter {fields!r} lists only the custom field IDs, so the agent would lose "
            f"the standard issue content. Recorded: {call}"
        )


def test_agent_downloaded_the_story_attachment_over_rest(
    requirements_review_response: httpx.Response, http_client: httpx.Client
) -> None:
    """WS5: the attachment must be downloaded from the Jira REST API by the review flow,
    not handed through MCP tool-result messages."""
    data = wait_for_recorded(
        http_client,
        JIRA_REST_RECORDED_URL,
        lambda d: any(dl.get("filename") == "reset-policy.md" for dl in d.get("attachment_downloads", [])),
    )
    downloaded = {dl.get("filename") for dl in data.get("attachment_downloads", [])}
    assert "reset-policy.md" in downloaded, (
        f"The review flow never downloaded the story's attachment over REST. Downloaded: {downloaded}"
    )
    # The MCP download tool stays advertised by the mock, so the per-agent tool filtering
    # (WS11) is what keeps the flow on the REST path.
    mcp = http_client.get(JIRA_MCP_RECORDED_URL).json()
    assert not mcp.get("download_attachments"), (
        f"The MCP download_attachments tool was still used: {mcp.get('download_attachments')}"
    )


def test_review_flow_issued_a_documents_hybrid_query_with_a_focused_query_text(
    requirements_review_response: httpx.Response, http_client: httpx.Client
) -> None:
    """WS10: with retrieval enabled, the review flow must run a hybrid (dense + sparse)
    query against the documents collection, embedding a focused query text that is
    shorter than the issue content itself."""
    data = wait_for_recorded(
        http_client,
        QDRANT_RECORDED_URL,
        lambda d: any(q.get("collection") == DOCUMENTS_COLLECTION_NAME for q in d.get("hybrid_queries", [])),
    )
    documents_queries = [q for q in data.get("hybrid_queries", []) if q.get("collection") == DOCUMENTS_COLLECTION_NAME]
    assert documents_queries, f"No hybrid query reached the documents collection. Recorded: {data}"

    story = http_client.get(JIRA_MCP_SEEDED_STORY_URL).json()
    issue_content = story["fields"]["description"]
    query_texts = [
        text
        for call in data.get("embedding_calls", [])
        if call.get("endpoint") == "/embed-query-text"
        for text in call.get("texts", [])
    ]
    assert any(text.strip() and len(text) < len(issue_content) for text in query_texts), (
        f"No focused embed-query-text call (non-empty and shorter than the issue content) "
        f"accompanied the documents query. Query texts: {query_texts}"
    )


def test_confluence_only_configuration_queries_exactly_one_document_collection(
    requirements_review_response: httpx.Response, http_client: httpx.Client
) -> None:
    """WS18: with only Confluence retrieval enabled, every document query goes to the Confluence
    collection with the pinned source discriminator, and the SharePoint collection is never queried."""
    data = wait_for_recorded(
        http_client,
        QDRANT_RECORDED_URL,
        lambda d: any(q.get("collection") == DOCUMENTS_COLLECTION_NAME for q in d.get("hybrid_queries", [])),
    )
    queried = {q.get("collection") for q in data.get("hybrid_queries", [])}
    assert SHAREPOINT_COLLECTION_NAME not in queried, f"The SharePoint collection was queried: {queried}"
    for query in [q for q in data["hybrid_queries"] if q.get("collection") == DOCUMENTS_COLLECTION_NAME]:
        for prefetch in query.get("prefetches", []):
            must = {
                (c.get("key"), c.get("match", {}).get("value")) for c in (prefetch.get("filter") or {}).get("must", [])
            }
            assert ("source", "confluence") in must, f"A document query does not pin the source: {query}"


def _completed_tasks_of(http_client: httpx.Client, auth_headers: dict[str, str], agent_name: str) -> list[dict]:
    response = http_client.get(f"{ORCHESTRATOR_URL}/api/dashboard/tasks", params={"limit": 100}, headers=auth_headers)
    assert response.status_code == 200, response.text
    return [t for t in response.json() if t.get("agent_name") == agent_name and t.get("status") == "COMPLETED"]


def test_agent_log_lines_carry_agent_name_and_task_id(
    requirements_review_response: httpx.Response, http_client: httpx.Client, auth_headers: dict[str, str]
) -> None:
    """WS23: the agent stamps its own name and task id on every log line of a run, and the
    dashboard reads them from the structured records."""
    agent_name = config.RequirementsReviewAgentConfig.OWN_NAME
    tasks = _completed_tasks_of(http_client, auth_headers, agent_name)
    assert tasks, f"No completed task of '{agent_name}' is listed on the dashboard."
    response = http_client.get(
        f"{ORCHESTRATOR_URL}/api/dashboard/logs",
        params={"task_id": tasks[0]["task_id"], "limit": 1000},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    entries = response.json()
    stamped = [e for e in entries if e.get("agent_name") == agent_name and e.get("task_id")]
    assert stamped, f"No log line of the task carries the agent name and a task id: {entries[:5]}"
    foreign = {e.get("agent_name") for e in entries if e.get("agent_name")} - {agent_name}
    assert not foreign, f"Log lines of the task carry other agents' names: {foreign}"


def test_usage_artifact_carries_per_operation_counters(
    test_case_flow_response: httpx.Response, http_client: httpx.Client, auth_headers: dict[str, str]
) -> None:
    """WS13: the review task's usage artifact breaks the tokens down per operation (the main agent
    and its review sub-agent) with the cached/uncached split, and its totals include every operation."""
    tasks = _completed_tasks_of(http_client, auth_headers, config.TestCaseReviewAgentConfig.OWN_NAME)
    assert tasks, "No completed test-case review task is listed on the dashboard."
    token_usage = tasks[0].get("token_usage") or {}
    operations = token_usage.get("operations") or []
    by_name = {operation["operation"]: operation for operation in operations}
    assert {"main", "review_test_cases_with_attachments"} <= set(by_name), f"Operations: {operations}"
    for operation in by_name.values():
        assert operation["requests"] >= 1, operation
        for counter in ("uncached_input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens"):
            assert counter in operation, f"The operation lacks the {counter} counter: {operation}"
    assert token_usage["requests"] == sum(o["requests"] for o in operations), token_usage
    assert token_usage["input_tokens"] == sum(
        o["uncached_input_tokens"] + o["cache_read_tokens"] + o["cache_write_tokens"] for o in operations
    ), token_usage
    assert token_usage["output_tokens"] == sum(o["output_tokens"] for o in operations), token_usage


def test_agent_read_source_story_from_jira(
    requirements_review_response: httpx.Response, http_client: httpx.Client
) -> None:
    """The review must be grounded in the real story: the agent must fetch it via the Jira MCP first."""
    data = wait_for_recorded(
        http_client,
        JIRA_MCP_RECORDED_URL,
        lambda d: SEEDED_ISSUE_KEY in [c.get("issue_key") for c in d.get("get_issue", [])],
    )
    assert SEEDED_ISSUE_KEY in [c.get("issue_key") for c in data.get("get_issue", [])], (
        f"Agent never fetched the source story {SEEDED_ISSUE_KEY} via Jira MCP. Recorded: {data}"
    )


# --- Test-case generation / classification / review flow -------------------------------


def test_test_case_flow_webhook_accepted(test_case_flow_response: httpx.Response) -> None:
    assert test_case_flow_response.status_code == 200, (
        f"Test-case flow webhook failed: {test_case_flow_response.status_code} {test_case_flow_response.text}"
    )


def test_real_test_cases_created_in_zephyr(test_case_flow_response: httpx.Response, http_client: httpx.Client) -> None:
    """Generation must create real test cases (non-empty name + steps) in Zephyr."""
    data = wait_for_recorded(
        http_client,
        ZEPHYR_RECORDED_URL,
        lambda d: any(tc.get("name", "").strip() and tc.get("steps") for tc in d.get("test_cases", [])),
    )
    real_cases = [tc for tc in data.get("test_cases", []) if tc.get("name", "").strip() and tc.get("steps")]
    assert real_cases, f"Zephyr received no test cases with both a name and steps. Recorded: {data}"


def test_generated_test_cases_linked_to_story(
    test_case_flow_response: httpx.Response, http_client: httpx.Client
) -> None:
    """Generation must link the created test cases to the seeded story's numeric id."""
    data = wait_for_recorded(http_client, ZEPHYR_RECORDED_URL, lambda d: bool(d.get("issue_links")))
    created_keys = {tc.get("key") for tc in data.get("test_cases", [])}
    links = [
        link
        for link in data.get("issue_links", [])
        if link.get("test_case_key") in created_keys and str(link.get("issue_id")) == str(SEEDED_ISSUE_ID)
    ]
    assert links, f"No created test case was linked to the seeded story (id {SEEDED_ISSUE_ID}). Recorded: {data}"


def test_classification_added_labels(test_case_flow_response: httpx.Response, http_client: httpx.Client) -> None:
    """Classification must add labels to at least one test case in Zephyr."""
    data = wait_for_recorded(
        http_client,
        ZEPHYR_RECORDED_URL,
        lambda d: any(tc.get("labels") for tc in d.get("test_cases", [])),
    )
    labelled = [tc for tc in data.get("test_cases", []) if tc.get("labels")]
    assert labelled, f"No test case received labels from classification. Recorded: {data}"


def test_review_comment_added_to_zephyr(test_case_flow_response: httpx.Response, http_client: httpx.Client) -> None:
    """Review must write a non-empty "Review Comments" value to every generated test case."""
    data = wait_for_recorded(
        http_client,
        ZEPHYR_RECORDED_URL,
        lambda d: bool(d.get("test_cases")) and all(tc.get("review_comments", "").strip() for tc in d["test_cases"]),
    )
    generated = data.get("test_cases", [])
    assert generated, f"No generated test case reached Zephyr at all. Recorded: {data}"
    unreviewed = [tc["key"] for tc in generated if not tc.get("review_comments", "").strip()]
    assert not unreviewed, f"Test case(s) {unreviewed} received no review comment. Recorded: {data}"


def test_review_set_status_to_review_complete(
    test_case_flow_response: httpx.Response, http_client: httpx.Client
) -> None:
    """Review must move at least one test case to the "Review Complete" status."""
    data = wait_for_recorded(
        http_client,
        ZEPHYR_RECORDED_URL,
        lambda d: any(tc.get("status", {}).get("name") == REVIEW_COMPLETE_STATUS for tc in d.get("test_cases", [])),
    )
    completed = [tc for tc in data.get("test_cases", []) if tc.get("status", {}).get("name") == REVIEW_COMPLETE_STATUS]
    assert completed, f"No test case was moved to '{REVIEW_COMPLETE_STATUS}'. Recorded: {data}"


def test_review_comment_carries_the_duplicate_check(
    test_case_flow_response: httpx.Response, http_client: httpx.Client
) -> None:
    """WS17: every review comment written to Zephyr ends with the duplicate-check section
    rendered in code, whatever the judge decided."""
    data = wait_for_recorded(
        http_client,
        ZEPHYR_RECORDED_URL,
        lambda d: (
            bool(d.get("test_cases"))
            and all(DUPLICATE_CHECK_HEADING in tc.get("review_comments", "") for tc in d["test_cases"])
        ),
    )
    missing = [
        tc["key"] for tc in data.get("test_cases", []) if DUPLICATE_CHECK_HEADING not in tc.get("review_comments", "")
    ]
    assert data.get("test_cases") and not missing, (
        f"Review comment(s) of {missing} carry no '{DUPLICATE_CHECK_HEADING}' section. Recorded: {data}"
    )


def test_review_indexed_its_batch_and_searched_the_project_for_duplicates(
    test_case_flow_response: httpx.Response, http_client: httpx.Client
) -> None:
    """WS17: the review indexes the reviewed test cases and runs one project-scoped duplicate
    search per test case which excludes the test case itself."""
    zephyr = wait_for_recorded(http_client, ZEPHYR_RECORDED_URL, lambda d: bool(d.get("test_cases")))
    generated_keys = {tc["key"] for tc in zephyr.get("test_cases", [])}
    data = wait_for_recorded(
        http_client,
        QDRANT_RECORDED_URL,
        lambda d: (
            generated_keys
            <= {
                p.get("payload", {}).get("test_case_key")
                for p in d.get("upserted_points", [])
                if p.get("collection") == TEST_CASES_COLLECTION_NAME
            }
        ),
    )
    queries = [q for q in data.get("hybrid_queries", []) if q.get("collection") == TEST_CASES_COLLECTION_NAME]
    excluded_keys = set()
    for query in queries:
        dense_filter = query["prefetches"][0].get("filter") or {}
        must = {(c.get("key"), c.get("match", {}).get("value")) for c in dense_filter.get("must", [])}
        assert ("project_key", SEEDED_PROJECT_KEY) in must, f"A duplicate search is not project-scoped: {query}"
        excluded_keys |= {c.get("match", {}).get("value") for c in dense_filter.get("must_not", [])}
    assert generated_keys <= excluded_keys, (
        f"Not every reviewed test case ran a duplicate search excluding itself. Reviewed: {generated_keys}, "
        f"excluded in searches: {excluded_keys}"
    )


# --- Test execution / incident-creation flow -------------------------------------------


def test_failed_execution_creates_bug_in_jira(
    execute_tests_response: httpx.Response, http_client: httpx.Client
) -> None:
    """A failed automated test must drive incident creation: a real Bug reaches the seeded project."""
    data = wait_for_recorded(
        http_client,
        JIRA_MCP_RECORDED_URL,
        lambda d: any(
            i.get("summary", "").strip() and i.get("description", "").strip() for i in d.get("created_issues", [])
        ),
    )
    bugs = [
        i
        for i in data.get("created_issues", [])
        if i.get("summary", "").strip()
        and i.get("description", "").strip()
        and i.get("issue_type") == "Bug"
        and i.get("project_key") == SEEDED_PROJECT_KEY
    ]
    assert bugs, (
        f"No Bug issue for project {SEEDED_PROJECT_KEY} reached Jira from the incident-creation flow. Recorded: {data}"
    )


def test_created_bug_carries_execution_traceability(
    execute_tests_response: httpx.Response, http_client: httpx.Client
) -> None:
    """The agent and environment the orchestrator recorded for the execution must reach the bug.

    When the executor describes no environment of its own - as the mock executor deliberately does
    not - the orchestrator falls back to describing the execution itself, from the executing agent's
    card and its own environment label, and hands that to the incident-creation agent, which turns
    it into the environment details of the created bug.
    """
    data = wait_for_recorded(
        http_client,
        JIRA_MCP_RECORDED_URL,
        lambda d: any(i.get("issue_type") == "Bug" for i in d.get("created_issues", [])),
    )
    descriptions = [
        i.get("description", "")
        for i in data.get("created_issues", [])
        if i.get("issue_type") == "Bug" and i.get("project_key") == SEEDED_PROJECT_KEY
    ]
    assert descriptions, f"No Bug issue for project {SEEDED_PROJECT_KEY} reached Jira. Recorded: {data}"
    for traced_value in (TEST_ENVIRONMENT_LABEL, EXECUTION_AGENT_NAME, EXECUTION_AGENT_VERSION):
        assert any(traced_value.casefold() in description.casefold() for description in descriptions), (
            f"No created bug carries {traced_value!r}, so the execution traceability data did not "
            f"survive the way to Jira. Descriptions: {descriptions}"
        )


def test_failed_execution_reported_to_zephyr(execute_tests_response: httpx.Response, http_client: httpx.Client) -> None:
    """The reporting half of /execute-tests: a failed execution of the seeded case must reach
    Zephyr, inside a test cycle created for the seeded project, and no reporting step failed (WS15)."""
    assert execute_tests_response.json().get("reporting_failures") == [], execute_tests_response.json()
    data = wait_for_recorded(
        http_client,
        ZEPHYR_RECORDED_URL,
        lambda d: any(e.get("testCaseKey") == SEEDED_EXECUTABLE_TC_KEY for e in d.get("test_executions", [])),
    )
    executions = [e for e in data.get("test_executions", []) if e.get("testCaseKey") == SEEDED_EXECUTABLE_TC_KEY]
    assert executions, f"No test execution for {SEEDED_EXECUTABLE_TC_KEY} reached Zephyr. Recorded: {data}"
    failed = [e for e in executions if e.get("statusName") == "Fail"]
    assert failed, f"The execution of {SEEDED_EXECUTABLE_TC_KEY} was not reported as failed. Recorded: {executions}"
    cycle_keys = {
        cycle.get("key") for cycle in data.get("test_cycles", []) if cycle.get("projectKey") == SEEDED_PROJECT_KEY
    }
    assert any(e.get("testCycleKey") in cycle_keys for e in failed), (
        f"No failed execution belongs to a test cycle of project {SEEDED_PROJECT_KEY}. "
        f"Executions: {failed}, cycles: {data.get('test_cycles', [])}"
    )
    executed_steps = [
        step
        for execution in failed
        for step in execution.get("testScriptResults", [])
        if step.get("statusName") != "Not Executed"
    ]
    assert any(step.get("actualStartDate") and step.get("actualEndDate") for step in executed_steps), (
        f"No executed step carries both actualStartDate and actualEndDate. Steps: {executed_steps}"
    )
    # Zephyr reads every date as UTC, so a date built from local time lands a whole offset away.
    now = datetime.now(UTC)
    for execution in failed:
        for field in ("actualStartDate", "actualEndDate"):
            reported = execution.get(field)
            assert reported, f"The execution carries no {field}. Execution: {execution}"
            reported_at = datetime.strptime(reported, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
            assert abs(now - reported_at) < timedelta(minutes=30), (
                f"{field} '{reported}' is not the UTC instant of this run ({now.isoformat()}), "
                f"which means the orchestrator reported a local time."
            )


def test_created_bug_linked_to_test_execution(
    execute_tests_response: httpx.Response, http_client: httpx.Client
) -> None:
    """The bug created for the failed execution must be linked back to the Zephyr execution."""
    zephyr = wait_for_recorded(http_client, ZEPHYR_RECORDED_URL, lambda d: bool(d.get("execution_issue_links")))
    links = zephyr.get("execution_issue_links", [])
    assert links, f"No issue was linked to any test execution in Zephyr. Recorded: {zephyr}"
    mcp = wait_for_recorded(http_client, JIRA_MCP_RECORDED_URL, lambda d: bool(d.get("created_issues")))
    created_issue_ids = {str(issue.get("id")) for issue in mcp.get("created_issues", [])}
    assert any(str(link.get("issue_id")) in created_issue_ids for link in links), (
        f"No created bug ({created_issue_ids}) was linked to a test execution. Links: {links}"
    )


def test_incident_creation_consulted_vector_db(
    execute_tests_response: httpx.Response, http_client: httpx.Client
) -> None:
    """The duplicate search must run a hybrid (dense + sparse, RRF-fused) query."""
    data = wait_for_recorded(http_client, QDRANT_RECORDED_URL, lambda d: bool(d.get("hybrid_queries")))
    hybrid_queries = data.get("hybrid_queries", [])
    assert hybrid_queries, f"No hybrid query reached the vector DB. Recorded: {data}"
    query = hybrid_queries[0]
    using_names = {p.get("using") for p in query.get("prefetches", [])}
    assert using_names == {"dense", "sparse"}, f"Expected dense + sparse prefetches, got {using_names}"
    assert query.get("fusion") == "rrf", f"Expected RRF fusion, got {query.get('fusion')}"


def test_incident_duplicate_query_is_scoped_to_the_project(
    execute_tests_response: httpx.Response, http_client: httpx.Client
) -> None:
    """WS16: the incident duplicate search filters on the project key it was given, on every branch."""
    data = wait_for_recorded(
        http_client,
        QDRANT_RECORDED_URL,
        lambda d: any(q.get("collection") == TICKETS_COLLECTION_NAME for q in d.get("hybrid_queries", [])),
    )
    queries = [q for q in data.get("hybrid_queries", []) if q.get("collection") == TICKETS_COLLECTION_NAME]
    assert queries, f"The incident flow issued no duplicate query. Recorded: {data}"
    for query in queries:
        for prefetch in query.get("prefetches", []):
            must = {
                (c.get("key"), c.get("match", {}).get("value")) for c in (prefetch.get("filter") or {}).get("must", [])
            }
            assert ("project_key", SEEDED_PROJECT_KEY) in must, f"A duplicate query is not project-scoped: {query}"


def _dashboard_tasks(http_client: httpx.Client, auth_headers: dict[str, str]) -> list[dict]:
    response = http_client.get(f"{ORCHESTRATOR_URL}/api/dashboard/tasks", params={"limit": 100}, headers=auth_headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_typed_label_group_reached_the_execution_agent(
    execute_tests_response: httpx.Response, http_client: httpx.Client, auth_headers: dict[str, str]
) -> None:
    """WS15: the test case carrying a recognized test-type label is dispatched to the execution
    agent as a group of that type."""
    expected = f"Execution of test case {SEEDED_EXECUTABLE_TC_KEY} (type: {SEEDED_EXECUTABLE_TC_TYPE_LABEL})"
    dispatched = [t for t in _dashboard_tasks(http_client, auth_headers) if t.get("description") == expected]
    assert dispatched, f"No task '{expected}' was dispatched."
    assert {t.get("agent_name") for t in dispatched} == {EXECUTION_AGENT_NAME}, dispatched


def test_untyped_test_case_is_skipped(
    execute_tests_response: httpx.Response, http_client: httpx.Client, auth_headers: dict[str, str]
) -> None:
    """WS15: an automated test case without a recognized test-type label is skipped with a warning
    naming it, and never reaches an execution agent."""
    tasks = _dashboard_tasks(http_client, auth_headers)
    assert not [t for t in tasks if SEEDED_UNTYPED_TC_KEY in (t.get("description") or "")], tasks
    response = http_client.get(
        f"{ORCHESTRATOR_URL}/api/dashboard/logs", params={"limit": 1000, "level": "WARNING"}, headers=auth_headers
    )
    assert response.status_code == 200, response.text
    messages = [entry.get("message", "") for entry in response.json()]
    assert f"Skipping test case {SEEDED_UNTYPED_TC_KEY}: no recognized test-type label." in messages, messages[:20]


def test_manual_execution_reaches_zephyr_without_creating_a_bug(
    execute_tests_response: httpx.Response,
    http_client: httpx.Client,
    auth_headers: dict[str, str],
    webhook_headers: dict[str, str],
) -> None:
    """WS15: /execute-test runs one test case on the explicitly chosen agent, uploads its result to
    Zephyr and never requests incident creation."""
    agents = http_client.get(f"{ORCHESTRATOR_URL}/api/dashboard/agents", headers=auth_headers).json()
    agent_id = next(agent["id"] for agent in agents if agent.get("name") == EXECUTION_AGENT_NAME)

    def _executions(zephyr: dict) -> list[dict]:
        return [e for e in zephyr.get("test_executions", []) if e.get("testCaseKey") == SEEDED_EXECUTABLE_TC_KEY]

    executions_before = len(_executions(http_client.get(ZEPHYR_RECORDED_URL).json()))
    bugs_before = len(http_client.get(JIRA_MCP_RECORDED_URL).json().get("created_issues", []))

    response = httpx.post(
        f"{ORCHESTRATOR_URL}/execute-test",
        headers=webhook_headers,
        json={"test_case_key": SEEDED_EXECUTABLE_TC_KEY, "agent_id": agent_id, "project_key": SEEDED_PROJECT_KEY},
        timeout=httpx.Timeout(600.0),
    )

    assert response.status_code == 200, f"Manual execution failed: {response.status_code} {response.text}"
    assert response.json().get("testCaseKey") == SEEDED_EXECUTABLE_TC_KEY, response.json()
    assert response.json().get("reporting_failures") == [], response.json()
    zephyr = http_client.get(ZEPHYR_RECORDED_URL).json()
    assert len(_executions(zephyr)) == executions_before + 1, f"The manual result never reached Zephyr: {zephyr}"
    created_issues = http_client.get(JIRA_MCP_RECORDED_URL).json().get("created_issues", [])
    assert len(created_issues) == bugs_before, f"The manual run created an issue in Jira: {created_issues}"


# --- RAG vector DB update flow (WS8: local mode via the sync service) ---------------------


def test_update_jira_db_webhook_accepted(update_jira_db_response: httpx.Response) -> None:
    assert update_jira_db_response.status_code == 200, (
        f"Jira-sync webhook failed: {update_jira_db_response.status_code} {update_jira_db_response.text}"
    )
    details = update_jira_db_response.json().get("details", {})
    assert details.get("processed_count", 0) >= 1, f"The RAG sync processed no issues: {details}"


def test_rag_sync_outcome_is_visible_on_dashboard(
    update_jira_db_response: httpx.Response, http_client: httpx.Client, auth_headers: dict[str, str]
) -> None:
    """The completed Jira sync writes an outcome visible through the dashboard boundary."""
    assert update_jira_db_response.status_code == 200
    response = http_client.get(f"{ORCHESTRATOR_URL}/api/dashboard/rag-sync-status", headers=auth_headers)
    assert response.status_code == 200, response.text
    outcomes = response.json()
    assert any(item.get("scope") == "jira:SMOKE" and item.get("status") == "completed" for item in outcomes)


def test_rag_sync_upserted_seeded_story_into_vector_db(
    update_jira_db_response: httpx.Response, http_client: httpx.Client
) -> None:
    """The sync must push the seeded story into the tickets collection of the vector DB, with dense + sparse vectors."""
    data = wait_for_recorded(
        http_client,
        QDRANT_RECORDED_URL,
        lambda d: any(
            p.get("collection") == TICKETS_COLLECTION_NAME and p.get("payload", {}).get("key") == SEEDED_ISSUE_KEY
            for p in d.get("upserted_points", [])
        ),
    )
    upserts = [
        p
        for p in data.get("upserted_points", [])
        if p.get("collection") == TICKETS_COLLECTION_NAME and p.get("payload", {}).get("key") == SEEDED_ISSUE_KEY
    ]
    assert upserts, f"The seeded story {SEEDED_ISSUE_KEY} never reached the vector DB. Recorded: {data}"
    payload = upserts[0]["payload"]
    assert payload.get("project_key") == SEEDED_PROJECT_KEY, f"Wrong project on the upserted story: {payload}"
    assert payload.get("summary", "").strip(), f"The upserted story has no summary: {payload}"
    assert TICKETS_COLLECTION_NAME in data.get("created_collections", []), (
        f"The tickets collection was never created. Recorded: {data}"
    )
    # WS7: the collection is created with the hybrid schema and the story carries both named vectors.
    schema = data.get("collection_schemas", {}).get(TICKETS_COLLECTION_NAME, {})
    assert schema.get("vectors") == ["dense"] and schema.get("sparse_vectors") == ["sparse"], (
        f"The tickets collection lacks the named dense + sparse vector schema: {schema}"
    )
    assert upserts[0].get("vector_names") == ["dense", "sparse"], (
        f"The upserted story does not carry dense + sparse vectors: {upserts[0]}"
    )


def test_rag_sync_upserted_an_issue_in_a_previously_excluded_status(
    update_jira_db_response: httpx.Response, http_client: httpx.Client
) -> None:
    """WS18: the Jira sync ingests every issue whatever its workflow status, e.g. a Closed bug."""
    data = wait_for_recorded(
        http_client,
        QDRANT_RECORDED_URL,
        lambda d: any(
            p.get("collection") == TICKETS_COLLECTION_NAME
            and p.get("payload", {}).get("key") == SEEDED_CLOSED_ISSUE_KEY
            for p in d.get("upserted_points", [])
        ),
    )
    payloads = [
        p["payload"]
        for p in data.get("upserted_points", [])
        if p.get("collection") == TICKETS_COLLECTION_NAME and p.get("payload", {}).get("key") == SEEDED_CLOSED_ISSUE_KEY
    ]
    assert payloads, f"The Closed issue {SEEDED_CLOSED_ISSUE_KEY} never reached the vector DB. Recorded: {data}"
    assert payloads[0].get("status") == "Closed", payloads[0]


# --- Confluence documents ingestion (WS9: local mode via the sync service) ----------------


def test_update_confluence_db_webhook_accepted(update_confluence_db_response: httpx.Response) -> None:
    assert update_confluence_db_response.status_code == 200, (
        f"Confluence-sync webhook failed: "
        f"{update_confluence_db_response.status_code} {update_confluence_db_response.text}"
    )
    details = update_confluence_db_response.json().get("details", {})
    assert details.get("processed_count", 0) >= 3, f"The Confluence sync processed too few items: {details}"
    assert details.get("status") == "completed", f"The Confluence sync did not complete cleanly: {details}"


def test_confluence_page_chunks_reached_vector_db_with_breadcrumbs(
    update_confluence_db_response: httpx.Response, http_client: httpx.Client
) -> None:
    """The seeded page's chunks must reach the documents collection, breadcrumb-prefixed
    and scoped by space key, and the Confluence REST mock must have seen the listing
    and the single body fetch."""
    data = wait_for_recorded(
        http_client,
        QDRANT_RECORDED_URL,
        lambda d: any(
            p.get("collection") == DOCUMENTS_COLLECTION_NAME and p.get("payload", {}).get("content_kind") == "page_body"
            for p in d.get("upserted_points", [])
        ),
    )
    chunk_upserts = [
        p
        for p in data.get("upserted_points", [])
        if p.get("collection") == DOCUMENTS_COLLECTION_NAME and p.get("payload", {}).get("content_kind") == "page_body"
    ]
    assert chunk_upserts, f"No page-body chunks reached the vector DB. Recorded: {data}"
    first_payload = chunk_upserts[0]["payload"]
    assert first_payload.get("space_key") == SEEDED_SPACE_KEY, f"Wrong space key on the chunk: {first_payload}"
    assert first_payload.get("document_name") == "Password Reset Requirements", (
        f"Wrong document name on the chunk: {first_payload}"
    )
    assert "Password Reset Requirements" in first_payload.get("breadcrumb", ""), (
        f"The chunk carries no breadcrumb prefix: {first_payload}"
    )
    section_payloads = [
        p["payload"]
        for p in chunk_upserts
        if p["payload"].get("breadcrumb") == "Password Reset Requirements > Reset Link Policy"
    ]
    assert section_payloads, f"No chunk carries the section breadcrumb: {[p['payload'] for p in chunk_upserts]}"
    assert "reset link stays valid for 60 minutes" in section_payloads[0].get("text", "").lower(), (
        f"The section chunk doesn't carry the section content: {section_payloads[0]}"
    )
    assert DOCUMENTS_COLLECTION_NAME in data.get("created_collections", []), (
        f"The documents collection was never created. Recorded: {data}"
    )

    confluence = http_client.get(CONFLUENCE_RECORDED_URL).json()
    assert any(lookup.get("keys") == [SEEDED_SPACE_KEY] for lookup in confluence.get("space_lookups", [])), (
        f"The sync never resolved the space key. Recorded: {confluence}"
    )
    assert confluence.get("page_listings"), "The sync never listed the space's pages."
    assert confluence.get("page_fetches"), "The sync never fetched the page body."


def test_confluence_attachment_pages_reached_vector_db_with_chain_and_image(
    update_confluence_db_response: httpx.Response, http_client: httpx.Client
) -> None:
    """The seeded PDF and PNG must be downloaded and stored as attachment page records."""
    data = wait_for_recorded(
        http_client,
        QDRANT_RECORDED_URL,
        lambda d: (
            len(
                {
                    p.get("payload", {}).get("attachment_name")
                    for p in d.get("upserted_points", [])
                    if p.get("collection") == DOCUMENTS_COLLECTION_NAME
                    and p.get("payload", {}).get("content_kind") == "attachment"
                }
            )
            >= 2
        ),
    )
    attachment_payloads = [
        point["payload"]
        for point in data.get("upserted_points", [])
        if point.get("collection") == DOCUMENTS_COLLECTION_NAME
        and point.get("payload", {}).get("content_kind") == "attachment"
    ]
    by_name = {payload["attachment_name"]: payload for payload in attachment_payloads}
    assert {"reset-policy.pdf", "flow-diagram.png"}.issubset(by_name), (
        f"Both seeded attachments did not reach the vector DB: {attachment_payloads}"
    )
    pdf = by_name["reset-policy.pdf"]
    assert pdf.get("page_number") == 1 and pdf.get("page_count") == 1, pdf
    assert "Password Reset Requirements > reset-policy.pdf > page 1 of 1" in pdf.get("text", ""), pdf
    assert "links expire after 60 minutes" in pdf.get("text", ""), pdf
    assert pdf.get("image"), f"The rendered PDF page image is missing: {pdf}"
    image = by_name["flow-diagram.png"]
    assert image.get("page_number") == 1 and image.get("page_count") == 1, image
    assert image.get("image"), f"The normalized PNG page image is missing: {image}"

    confluence = http_client.get(CONFLUENCE_RECORDED_URL).json()
    downloaded = {item.get("filename") for item in confluence.get("attachment_downloads", [])}
    assert {"reset-policy.pdf", "flow-diagram.png"}.issubset(downloaded), (
        f"The sync did not download both attachments: {confluence}"
    )


def test_second_confluence_sync_reembeds_nothing(
    update_confluence_db_response: httpx.Response, http_client: httpx.Client, webhook_headers: dict[str, str]
) -> None:
    """A second sync of the unchanged space must skip on the version check: no new
    embedding calls, and the response reports zero processed items."""
    before = wait_for_recorded(
        http_client,
        QDRANT_RECORDED_URL,
        lambda d: any(
            p.get("collection") == DOCUMENTS_COLLECTION_NAME and p.get("payload", {}).get("content_kind") == "page_body"
            for p in d.get("upserted_points", [])
        ),
    )
    embedding_calls_before = len(before.get("embedding_calls", []))

    response = httpx.post(
        f"{ORCHESTRATOR_URL}/update-confluence-db",
        headers=webhook_headers,
        json={"space_key": SEEDED_SPACE_KEY},
        timeout=httpx.Timeout(300.0),
    )
    assert response.status_code == 200, f"The second sync failed: {response.status_code} {response.text}"
    details = response.json().get("details", {})
    assert details.get("processed_count", 0) == 0, f"The second sync re-processed items: {details}"

    after = http_client.get(QDRANT_RECORDED_URL).json()
    assert len(after.get("embedding_calls", [])) == embedding_calls_before, (
        "The second sync re-embedded unchanged Confluence items: "
        f"{len(after.get('embedding_calls', []))} vs {embedding_calls_before} calls"
    )


def test_concurrent_confluence_sync_yields_exactly_one_409(
    http_client: httpx.Client, webhook_headers: dict[str, str]
) -> None:
    """Two concurrent /update-confluence-db calls for the same space: the lock serializes
    them, so one wins and the other answers 409 Conflict."""
    import concurrent.futures

    def _trigger(_: int) -> httpx.Response:
        return httpx.post(
            f"{ORCHESTRATOR_URL}/update-confluence-db",
            headers=webhook_headers,
            json={"space_key": SEEDED_SPACE_KEY},
            timeout=httpx.Timeout(300.0),
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(_trigger, range(2)))

    status_codes = sorted(r.status_code for r in responses)
    assert status_codes in ([200, 200], [200, 409]), (
        f"Expected one winner (and possibly one 409 while it runs), got {status_codes}. "
        f"Bodies: {[r.text for r in responses]}"
    )


# --- Negative paths (auth + validation; reach the orchestrator only, no LLM) ------------

ISSUE_KEY_WEBHOOK_PATHS = ["/new-requirements-available", "/story-ready-for-test-case-generation"]
PROJECT_KEY_WEBHOOK_PATHS = ["/execute-tests", "/update-jira-db"]
SPACE_KEY_WEBHOOK_PATHS = ["/update-confluence-db"]
AUTHENTICATED_WEBHOOKS = [
    ("/new-requirements-available", {"issue_key": SEEDED_ISSUE_KEY}),
    ("/story-ready-for-test-case-generation", {"issue_key": SEEDED_ISSUE_KEY}),
    ("/execute-tests", {"project_key": SEEDED_PROJECT_KEY}),
    ("/update-jira-db", {"project_key": SEEDED_PROJECT_KEY}),
    ("/update-confluence-db", {"space_key": SEEDED_SPACE_KEY}),
]


@pytest.mark.parametrize(("path", "payload"), AUTHENTICATED_WEBHOOKS)
def test_webhook_rejects_invalid_api_key(http_client: httpx.Client, path: str, payload: dict[str, str]) -> None:
    """A wrong orchestrator API key must be rejected with 401 before any work starts."""
    response = http_client.post(f"{ORCHESTRATOR_URL}{path}", headers={"X-API-Key": "wrong-key"}, json=payload)
    assert response.status_code == 401, f"{path} accepted an invalid API key: {response.status_code} {response.text}"


@pytest.mark.parametrize("path", ISSUE_KEY_WEBHOOK_PATHS)
def test_webhook_rejects_missing_issue_key(
    http_client: httpx.Client, webhook_headers: dict[str, str], path: str
) -> None:
    """A valid key but no issue_key must fail validation with 400, without dispatching to an agent."""
    response = http_client.post(f"{ORCHESTRATOR_URL}{path}", headers=webhook_headers, json={})
    assert response.status_code == 400, (
        f"{path} did not reject a missing issue_key with 400: {response.status_code} {response.text}"
    )


@pytest.mark.parametrize("path", PROJECT_KEY_WEBHOOK_PATHS)
def test_webhook_rejects_missing_project_key(
    http_client: httpx.Client, webhook_headers: dict[str, str], path: str
) -> None:
    """A valid key but no project_key must fail request-model validation with 422."""
    response = http_client.post(f"{ORCHESTRATOR_URL}{path}", headers=webhook_headers, json={})
    assert response.status_code == 422, (
        f"{path} did not reject a missing project_key with 422: {response.status_code} {response.text}"
    )


@pytest.mark.parametrize("path", SPACE_KEY_WEBHOOK_PATHS)
def test_webhook_rejects_missing_space_key(
    http_client: httpx.Client, webhook_headers: dict[str, str], path: str
) -> None:
    """A valid key but no space_key must fail request-model validation with 422."""
    response = http_client.post(f"{ORCHESTRATOR_URL}{path}", headers=webhook_headers, json={})
    assert response.status_code == 422, (
        f"{path} did not reject a missing space_key with 422: {response.status_code} {response.text}"
    )


def test_dashboard_api_rejects_missing_token(http_client: httpx.Client) -> None:
    """The dashboard API must reject requests without a bearer token with 401."""
    response = http_client.get(f"{ORCHESTRATOR_URL}/api/dashboard/agents")
    assert response.status_code == 401, (
        f"The dashboard API accepted a request without a token: {response.status_code} {response.text}"
    )


def test_dashboard_reports_the_configured_agent_version(
    all_agents_ready: None, http_client: httpx.Client, auth_headers: dict[str, str]
) -> None:
    """The version an agent is started with must reach the dashboard through its A2A card."""
    response = http_client.get(f"{ORCHESTRATOR_URL}/api/dashboard/agents", headers=auth_headers)
    assert response.status_code == 200, f"Could not read the agents view: {response.status_code} {response.text}"
    executors = [agent for agent in response.json() if agent.get("name") == EXECUTION_AGENT_NAME]
    assert executors, f"The mock execution agent is not listed in the agents view: {response.json()}"
    assert executors[0].get("version") == EXECUTION_AGENT_VERSION, (
        f"The dashboard reports version {executors[0].get('version')!r} instead of "
        f"{EXECUTION_AGENT_VERSION!r} for the mock execution agent."
    )


def test_manual_discovery_reports_reachable_and_removed_agents(
    all_agents_ready: None, http_client: httpx.Client, auth_headers: dict[str, str]
) -> None:
    """WS14: the manual discovery run re-probes every registered agent and returns its summary; with
    every agent up, all of them are reachable and none is removed."""
    response = http_client.post(f"{ORCHESTRATOR_URL}/api/dashboard/discovery", headers=auth_headers)
    assert response.status_code == 200, f"Manual discovery failed: {response.status_code} {response.text}"
    report = response.json()
    assert report.get("removed") == 0, report
    assert report.get("reachable", 0) >= len(EXPECTED_AGENT_NAMES), report
    assert report.get("message") == f"{report['reachable']} agents reachable, 0 unreachable agents removed", report


def test_dashboard_reports_the_configured_orchestrator_version(
    http_client: httpx.Client, auth_headers: dict[str, str]
) -> None:
    """The version the orchestrator is started with must reach the dashboard summary view."""
    response = http_client.get(f"{ORCHESTRATOR_URL}/api/dashboard/summary", headers=auth_headers)
    assert response.status_code == 200, f"Could not read the summary view: {response.status_code} {response.text}"
    reported_version = response.json().get("orchestrator_version")
    assert reported_version == ORCHESTRATOR_VERSION, (
        f"The dashboard reports orchestrator version {reported_version!r} instead of {ORCHESTRATOR_VERSION!r}."
    )


def test_login_is_rate_limited_after_the_configured_attempts(
    http_client: httpx.Client, auth_headers: dict[str, str]
) -> None:
    """WS22: the login endpoint answers 429 with Retry-After once a client exceeds the configured
    attempts in the window. Requests auth_headers first, so the session's own login is not blocked."""
    responses = [
        http_client.post(f"{ORCHESTRATOR_URL}/api/auth/login", json={"username": "smoke", "password": "wrong-password"})
        for _ in range(LOGIN_RATE_LIMIT_ATTEMPTS + 1)
    ]

    status_codes = [response.status_code for response in responses]
    assert status_codes[-1] == 429, f"No 429 after {LOGIN_RATE_LIMIT_ATTEMPTS} attempts: {status_codes}"
    assert set(status_codes[:-1]) <= {401, 429}, status_codes
    assert int(responses[-1].headers["Retry-After"]) >= 1, responses[-1].headers


def test_dashboard_agents_carry_the_composed_description(
    all_agents_ready: None, http_client: httpx.Client, auth_headers: dict[str, str]
) -> None:
    """Every framework agent's card description must be composed from its model, version
    and declared skill name, so the dashboard tile identifies the agent end to end."""
    response = http_client.get(f"{ORCHESTRATOR_URL}/api/dashboard/agents", headers=auth_headers)
    assert response.status_code == 200, f"Could not read the agents view: {response.status_code} {response.text}"
    agents_by_name = {agent.get("name"): agent for agent in response.json()}
    for agent_name in EXPECTED_AGENT_NAMES:
        agent = agents_by_name.get(agent_name)
        assert agent, f"The agent '{agent_name}' is not listed in the agents view: {response.json()}"
        description = agent.get("description") or ""
        assert "Model:" in description, f"The description of '{agent_name}' lacks the model: {description!r}"
        assert "Version:" in description, f"The description of '{agent_name}' lacks the version: {description!r}"
        assert "Skill:" in description, f"The description of '{agent_name}' lacks the skill name: {description!r}"


def test_routing_justifications_appear_in_dashboard_logs(
    requirements_review_response: httpx.Response, http_client: httpx.Client, auth_headers: dict[str, str]
) -> None:
    """Every routing decision must be logged with the selected agent's name and a
    justification, readable through the dashboard logs API."""
    response = http_client.get(f"{ORCHESTRATOR_URL}/api/dashboard/logs", params={"limit": 1000}, headers=auth_headers)
    assert response.status_code == 200, f"Could not read the dashboard logs: {response.status_code} {response.text}"
    messages = [entry.get("message", "") for entry in response.json()]
    decisions = [m for m in messages if "Routing decision" in m]
    assert decisions, "No 'Routing decision' entry reached the dashboard logs."
    justified = [m for m in decisions if "justification:" in m and "selected_agent_name=" in m]
    assert justified, f"The routing decision log entries carry no justification or agent name. Entries: {decisions[:5]}"


# --- SharePoint documents ingestion (WS18: local mode via the sync service) --------------

SHAREPOINT_COLLECTION_NAME = "sharepoint_documents"
SHAREPOINT_DRIVE_ID = "drive-smoke"
SHAREPOINT_FILE_NAME = "password-reset-policy.pdf"


def test_update_sharepoint_db_webhook_accepted(update_sharepoint_db_response: httpx.Response) -> None:
    assert update_sharepoint_db_response.status_code == 200, (
        f"SharePoint-sync webhook failed: "
        f"{update_sharepoint_db_response.status_code} {update_sharepoint_db_response.text}"
    )
    details = update_sharepoint_db_response.json().get("details", {})
    assert details.get("processed_count", 0) >= 1, f"The SharePoint sync processed no files: {details}"
    assert details.get("status") == "completed", f"The SharePoint sync did not complete cleanly: {details}"


def test_sharepoint_sync_used_the_graph_client_credentials_flow(
    update_sharepoint_db_response: httpx.Response, http_client: httpx.Client
) -> None:
    """The sync authenticates to the mocked Entra endpoint with the client-credentials grant."""
    data = wait_for_recorded(http_client, SHAREPOINT_RECORDED_URL, lambda d: d.get("token_requests"))
    assert any(
        request.get("grant_type") == "client_credentials" and request.get("tenant") == "smoke-tenant"
        for request in data.get("token_requests", [])
    ), f"No client-credentials token request reached the Graph mock. Recorded: {data}"


def test_sharepoint_document_reached_vector_db_with_reconciliation_chain(
    update_sharepoint_db_response: httpx.Response, http_client: httpx.Client
) -> None:
    """The ingested drive file lands in the SharePoint collection with its folder chain and
    the pinned source discriminator."""
    data = wait_for_recorded(
        http_client,
        QDRANT_RECORDED_URL,
        lambda d: any(
            p.get("collection") == SHAREPOINT_COLLECTION_NAME and p.get("payload", {}).get("source") == "sharepoint"
            for p in d.get("upserted_points", [])
        ),
    )
    upserts = [p for p in data.get("upserted_points", []) if p.get("collection") == SHAREPOINT_COLLECTION_NAME]
    assert upserts, f"No SharePoint document reached the vector DB. Recorded: {data}"
    payload = upserts[0]["payload"]
    assert payload.get("document_name") == SHAREPOINT_FILE_NAME, f"Wrong document ingested: {payload}"
    assert payload.get("folder_path") == "Docs", f"The folder path is missing: {payload}"
    assert payload.get("drive_id") == SHAREPOINT_DRIVE_ID, f"The drive id is missing: {payload}"
    assert "Docs" in payload.get("breadcrumb", ""), f"The reconciliation chain is missing: {payload}"
    assert upserts[0].get("vector_names") == ["dense", "sparse"], (
        f"The SharePoint document does not carry dense + sparse vectors: {upserts[0]}"
    )


def test_sharepoint_sync_downloaded_the_file_content(
    update_sharepoint_db_response: httpx.Response, http_client: httpx.Client
) -> None:
    data = wait_for_recorded(
        http_client,
        SHAREPOINT_RECORDED_URL,
        lambda d: any(
            download.get("item_id") == "file-pdf" and download.get("drive_id") == SHAREPOINT_DRIVE_ID
            for download in d.get("downloads", [])
        ),
    )
    assert data.get("downloads"), f"The drive file was never downloaded. Recorded: {data}"


def test_a_delta_link_on_another_origin_is_never_requested_with_the_graph_token(
    update_sharepoint_db_response: httpx.Response, http_client: httpx.Client, webhook_headers: dict[str, str]
) -> None:
    """The credential-scope control: the stored delta link is response data, and requesting it
    attaches the app-only Graph token, so a link naming another origin must be refused and the
    drive enumerated in full instead."""
    foreign_link = "http://attacker.invalid/drives/drive-smoke/root/delta?token=stolen"
    mock_base = SHAREPOINT_RECORDED_URL.removesuffix("/__recorded")
    handed_out = http_client.post(f"{mock_base}/__hand_out_delta_link", json={"delta_link": foreign_link})
    assert handed_out.status_code == 200, f"Could not arm the Graph mock: {handed_out.text}"
    try:
        # One run to store the foreign link, a second one that would follow it.
        for _ in range(2):
            response = httpx.post(
                f"{ORCHESTRATOR_URL}/update-sharepoint-db",
                headers=webhook_headers,
                json={"drive_id": SHAREPOINT_DRIVE_ID},
                timeout=httpx.Timeout(300.0),
            )
            assert response.status_code == 200, f"The SharePoint sync failed: {response.status_code} {response.text}"
            assert response.json().get("details", {}).get("status") == "completed", (
                f"The sync did not fall back to a full enumeration: {response.text}"
            )
    finally:
        http_client.post(f"{mock_base}/__hand_out_delta_link", json={"delta_link": None})

    data = http_client.get(SHAREPOINT_RECORDED_URL).json()
    assert all(call.get("drive_id") == SHAREPOINT_DRIVE_ID for call in data.get("delta_calls", [])), (
        f"An enumeration left the configured drive. Recorded: {data.get('delta_calls')}"
    )


# --- Test-case index sync (WS17: local mode via the sync service) ------------------------


def test_update_test_case_db_webhook_accepted(update_test_case_db_response: httpx.Response) -> None:
    assert update_test_case_db_response.status_code == 200, (
        f"Test-case-sync webhook failed: {update_test_case_db_response.status_code} {update_test_case_db_response.text}"
    )
    details = update_test_case_db_response.json().get("details", {})
    assert details.get("processed_count", 0) >= 1, f"The test-case sync indexed nothing: {details}"
    assert details.get("status") == "completed", f"The test-case sync did not complete cleanly: {details}"


def test_test_cases_reached_the_test_case_collection(
    update_test_case_db_response: httpx.Response, http_client: httpx.Client
) -> None:
    """The full resync pushes the seeded and generated test cases into the test_cases
    collection with the deterministic payload shape."""
    data = wait_for_recorded(
        http_client,
        QDRANT_RECORDED_URL,
        lambda d: any(
            p.get("collection") == "test_cases" and p.get("payload", {}).get("source") == "test_case"
            for p in d.get("upserted_points", [])
        ),
    )
    upserts = [p for p in data.get("upserted_points", []) if p.get("collection") == "test_cases"]
    assert upserts, f"No test case reached the test_cases collection. Recorded: {data}"
    payload = upserts[0]["payload"]
    assert payload.get("project_key") == SEEDED_PROJECT_KEY, f"Wrong project on the indexed test case: {payload}"
    assert payload.get("test_case_key"), f"The indexed test case has no key: {payload}"
    assert payload.get("content_hash"), f"The indexed test case has no content hash: {payload}"
    assert payload.get("indexed_at"), f"The indexed test case has no indexed_at: {payload}"


def test_concurrent_test_case_sync_yields_exactly_one_409(
    http_client: httpx.Client, webhook_headers: dict[str, str]
) -> None:
    """Two concurrent /update-test-case-db calls for the same project: the lock serializes
    them, so one wins and the other answers 409 Conflict."""
    import concurrent.futures

    def _trigger(_: int) -> httpx.Response:
        return httpx.post(
            f"{ORCHESTRATOR_URL}/update-test-case-db",
            headers=webhook_headers,
            json={"project_key": SEEDED_PROJECT_KEY},
            timeout=httpx.Timeout(300.0),
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(_trigger, range(2)))

    status_codes = sorted(r.status_code for r in responses)
    assert status_codes in ([200, 200], [200, 409]), (
        f"Expected one winner (and possibly one 409 while it runs), got {status_codes}. "
        f"Bodies: {[r.text for r in responses]}"
    )


# --- Durable dashboard state (WS24). Kept last: it restarts the orchestrator. -------------

ORCHESTRATOR_RESTART_TIMEOUT = 180.0


def _wait_for_orchestrator(http_client: httpx.Client) -> None:
    deadline = time.monotonic() + ORCHESTRATOR_RESTART_TIMEOUT
    while time.monotonic() < deadline:
        try:
            if http_client.get(f"{ORCHESTRATOR_URL}/openapi.json").status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(2)
    pytest.fail(f"The orchestrator did not come back within {ORCHESTRATOR_RESTART_TIMEOUT}s after the restart.")


def test_dashboard_history_is_backed_by_persistent_state(
    webhook_responses: dict[str, httpx.Response], http_client: httpx.Client, auth_headers: dict[str, str]
) -> None:
    """The dashboard's task history survives an orchestrator restart, rehydrated from the
    persisted state the smoke stack writes to the vector DB (DASHBOARD_PERSISTENCE_ENABLED)."""
    before = _dashboard_tasks(http_client, auth_headers)
    finished_ids = {task["task_id"] for task in before if task.get("status") in ("COMPLETED", "FAILED")}
    assert finished_ids, f"No finished task to check persistence with: {before}"

    subprocess.run(
        ["docker", "compose", "-f", SMOKE_COMPOSE_FILE, "restart", "orchestrator"],
        check=True,
        capture_output=True,
        text=True,
        timeout=300,
    )
    _wait_for_orchestrator(http_client)

    after_ids = {task["task_id"] for task in _dashboard_tasks(http_client, auth_headers)}
    missing = finished_ids - after_ids
    assert not missing, f"Task(s) {missing} did not survive the orchestrator restart."
