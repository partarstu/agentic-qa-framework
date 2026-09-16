# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Hermetic end-to-end smoke checks for the core QuAIA flows.

All of our own code runs for real (orchestrator + agents + real Gemini); only
the external boundaries are mocked. Each test asserts on what reached a mocked
boundary, read back from its ``/__recorded`` endpoint:

* Requirements review   -> a non-empty comment reached Jira (REST or MCP) on the seeded story.
* Requirements review   -> the agent first fetched the source story via the Jira MCP.
* Requirements review   -> the story's attachment was pulled over the protocol, by issue key alone.
* Requirements review   -> with JIRA_ADDITIONAL_FIELD_IDS configured, the agent requests those custom
                           field IDs (together with the standard content fields) when fetching the story.
* Test-case generation  -> real test cases (name + steps) reached Zephyr.
* Test-case generation  -> the created test cases were linked to the seeded story's numeric id.
* Test-case classification -> labels reached Zephyr.
* Test-case review      -> a non-empty "Review Comments" value reached Zephyr for every generated test case.
* Test-case review      -> at least one test case reached the "Review Complete" status.
* Test execution        -> a failed automated test drove a real Bug issue into the seeded project.
* Test execution        -> a failed execution for the seeded case was reported to Zephyr with UTC
                           execution dates, and the created bug was linked to that execution.
* Test execution        -> the incident-creation flow consulted the vector DB for duplicates.
* RAG DB update         -> the sync pushed the seeded story into the vector DB.
* Agent traceability    -> the version an agent is started with reaches the dashboard agents view,
                           the orchestrator's own version reaches the dashboard status view, and the
                           executing agent's name, version and environment reach the created bug.
* Negative paths        -> all four webhooks reject a bad API key (401), the issue-key webhooks
                           reject a missing issue_key (400), the project-key webhooks reject a
                           missing project_key (422), and the dashboard API rejects a missing
                           token (401).
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from tests.smoke.conftest import (
    CONFLUENCE_RECORDED_URL,
    DOCUMENTS_COLLECTION_NAME,
    EXECUTION_AGENT_NAME,
    EXECUTION_AGENT_VERSION,
    JIRA_MCP_RECORDED_URL,
    JIRA_REST_RECORDED_URL,
    ORCHESTRATOR_URL,
    ORCHESTRATOR_VERSION,
    QDRANT_RECORDED_URL,
    REVIEW_COMPLETE_STATUS,
    SEEDED_EXECUTABLE_TC_KEY,
    SEEDED_ISSUE_ID,
    SEEDED_ISSUE_KEY,
    SEEDED_PROJECT_KEY,
    SEEDED_SPACE_KEY,
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
    return any(
        c.get("issue_key") == SEEDED_ISSUE_KEY and c.get("body", "").strip() for c in rest_comments
    ) or any(c.get("issue_key") == SEEDED_ISSUE_KEY and c.get("comment", "").strip() for c in mcp_comments)


def test_review_comment_reached_jira(
    requirements_review_response: httpx.Response, http_client: httpx.Client
) -> None:
    """The agent must post a non-empty review comment to Jira, via REST or MCP."""
    data = wait_for_any_recorded(
        http_client,
        {"rest": JIRA_REST_RECORDED_URL, "mcp": JIRA_MCP_RECORDED_URL},
        _has_jira_comment,
    )
    assert _has_jira_comment(data), (
        f"No non-empty review comment reached Jira. REST={data['rest']}, MCP={data['mcp']}"
    )


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


def test_agent_downloaded_the_story_attachment(
    requirements_review_response: httpx.Response, http_client: httpx.Client
) -> None:
    """The attachment must reach the agent over the protocol, with no folder to download it to."""
    data = wait_for_recorded(http_client, JIRA_MCP_RECORDED_URL, lambda d: bool(d.get("download_attachments")))
    downloads = data.get("download_attachments", [])
    assert downloads, f"Agent never downloaded the attachment of {SEEDED_ISSUE_KEY}. Recorded: {data}"
    assert all(call == {"issue_key": SEEDED_ISSUE_KEY} for call in downloads), (
        f"Attachments must be requested by issue key alone, with no target path. Recorded: {downloads}"
    )


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
        f"Test-case flow webhook failed: "
        f"{test_case_flow_response.status_code} {test_case_flow_response.text}"
    )


def test_real_test_cases_created_in_zephyr(
    test_case_flow_response: httpx.Response, http_client: httpx.Client
) -> None:
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


def test_classification_added_labels(
    test_case_flow_response: httpx.Response, http_client: httpx.Client
) -> None:
    """Classification must add labels to at least one test case in Zephyr."""
    data = wait_for_recorded(
        http_client,
        ZEPHYR_RECORDED_URL,
        lambda d: any(tc.get("labels") for tc in d.get("test_cases", [])),
    )
    labelled = [tc for tc in data.get("test_cases", []) if tc.get("labels")]
    assert labelled, f"No test case received labels from classification. Recorded: {data}"


def test_review_comment_added_to_zephyr(
    test_case_flow_response: httpx.Response, http_client: httpx.Client
) -> None:
    """Review must write a non-empty "Review Comments" value to every generated test case."""
    data = wait_for_recorded(
        http_client,
        ZEPHYR_RECORDED_URL,
        lambda d: bool(d.get("test_cases"))
        and all(tc.get("review_comments", "").strip() for tc in d["test_cases"]),
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
        f"No Bug issue for project {SEEDED_PROJECT_KEY} reached Jira from the incident-creation flow. "
        f"Recorded: {data}"
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


def test_failed_execution_reported_to_zephyr(
    execute_tests_response: httpx.Response, http_client: httpx.Client
) -> None:
    """The reporting half of /execute-tests: a failed execution of the seeded case must reach
    Zephyr, inside a test cycle created for the seeded project."""
    data = wait_for_recorded(
        http_client,
        ZEPHYR_RECORDED_URL,
        lambda d: any(e.get("testCaseKey") == SEEDED_EXECUTABLE_TC_KEY for e in d.get("test_executions", [])),
    )
    executions = [e for e in data.get("test_executions", []) if e.get("testCaseKey") == SEEDED_EXECUTABLE_TC_KEY]
    assert executions, f"No test execution for {SEEDED_EXECUTABLE_TC_KEY} reached Zephyr. Recorded: {data}"
    failed = [e for e in executions if e.get("statusName") == "Fail"]
    assert failed, f"The execution of {SEEDED_EXECUTABLE_TC_KEY} was not reported as failed. Recorded: {executions}"
    cycle_keys = {cycle.get("key") for cycle in data.get("test_cycles", []) if cycle.get("projectKey") == SEEDED_PROJECT_KEY}
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


# --- RAG vector DB update flow (WS8: local mode via the sync service) ---------------------


def test_update_jira_db_webhook_accepted(update_jira_db_response: httpx.Response) -> None:
    assert update_jira_db_response.status_code == 200, (
        f"Jira-sync webhook failed: {update_jira_db_response.status_code} {update_jira_db_response.text}"
    )
    details = update_jira_db_response.json().get("details", {})
    assert details.get("processed_count", 0) >= 1, f"The RAG sync processed no issues: {details}"


def test_rag_sync_upserted_seeded_story_into_vector_db(
    update_jira_db_response: httpx.Response, http_client: httpx.Client
) -> None:
    """The sync must push the seeded story into the tickets collection of the vector DB."""
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
            p.get("collection") == DOCUMENTS_COLLECTION_NAME
            and p.get("payload", {}).get("content_kind") == "page_body"
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
        lambda d: len(
            {
                p.get("payload", {}).get("attachment_name")
                for p in d.get("upserted_points", [])
                if p.get("collection") == DOCUMENTS_COLLECTION_NAME
                and p.get("payload", {}).get("content_kind") == "attachment"
            }
        )
        >= 2,
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
            p.get("collection") == DOCUMENTS_COLLECTION_NAME
            and p.get("payload", {}).get("content_kind") == "page_body"
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
