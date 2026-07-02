# Smoke Suite Analysis: Enhancements and Optimizations

Analysis of the hermetic smoke suite (`tests/smoke/`, `docker-compose.smoke.yml`, `smoke` CI job) covering
coverage gaps, a latent mock hazard, and performance optimizations. Overall the suite is well-designed —
hermetic topology, recording mocks, session-scoped webhook fixtures, poll-with-deadline assertions — but the
items below would improve both coverage and wall-clock time.

## Coverage gaps (in order of value)

### 1. `/update-rag-db` is completely untested

It is one of the orchestrator's four public webhook endpoints (`orchestrator/main.py:724`), but no smoke test
drives it. The Qdrant mock only answers the "no collections" probe, so covering this flow means extending
`tests/smoke/mocks/qdrant_mock.py` to accept collection creation and point upserts and record them, then
asserting the sync pushed the seeded Zephyr test case into the vector DB. This is the only whole flow with
zero end-to-end coverage.

### 2. The reporting half of `/execute-tests` is exercised but never asserted

After incident creation, the orchestrator creates a test cycle and uploads execution results to Zephyr
(`_generate_test_report`, `orchestrator/main.py:789`). The Zephyr mock serves `/testcycles`,
`/testexecutions`, and `/testexecutions/{id}/links/issues` but records none of them
(`tests/smoke/mocks/zephyr_mock.py:137-153`). Recording those payloads and asserting a *failed* execution for
`SMOKE-T100` reached Zephyr — and that the created bug got linked to the execution — is a cheap, LLM-free
strengthening of an existing flow.

### 3. Several assertions don't pin the target, so wrong-destination writes would still pass

- `_has_jira_comment` (`tests/smoke/test_smoke.py:92`) accepts a comment on *any* issue; it should require
  `issue_key == "SMOKE-1"`.
- `test_failed_execution_creates_bug_in_jira` accepts any created issue; the MCP mock already records
  `project_key` and `issue_type`, so assert `issue_type == "Bug"` and `project_key == "SMOKE"`.
- `test_generated_test_cases_linked_to_story` only checks `issue_id` is truthy; it should equal the seeded
  story's numeric id (`10001`).

These are deterministic plumbing facts, not LLM output, so tightening them adds no flakiness.

### 4. Latent mock hazard: `PUT /testcases/{key}` writes into the generation store unconditionally

See `tests/smoke/mocks/zephyr_mock.py:156-160`. If any flow ever does a read-modify-write on the seeded
executable case `SMOKE-T100` — which carries a name, steps, labels, and Approved status — it lands in
`_test_cases` and appears in `/__recorded`, where it could spuriously satisfy the generation and
classification assertions. The comment at line 31 says the seeded case is "deliberately excluded" from
`/__recorded`, but this route breaks that guarantee. Guard it: route seeded keys back into
`_executable_test_cases`.

### 5. Negative paths cover only 2 of 4 authenticated endpoints

`/execute-tests` and `/update-rag-db` also take `X-API-Key`; adding them to the 401 parametrization is free
(no LLM). A missing-`project_key` check (FastAPI returns 422 there, unlike the custom 400 for `issue_key`)
and one dashboard-API-without-token 401 test round this out.

### 6. Incident-creation's duplicate-detection branch has zero coverage

The Qdrant mock reports no collections, so `VectorDbService.search` short-circuits before searching — and
nothing even asserts the agent *consulted* Qdrant. Minimum: record the `/collections` probe and assert it
happened. Full duplicate-path coverage (seeded collection + search endpoint) is a bigger lift and involves a
real embedding call; worth doing only if that branch matters. Relatedly, the MCP mock records
`updated_issues` (attachments) but nothing asserts on them.

## Performance optimizations (in order of impact)

### 1. Fire the three webhooks concurrently — the dominant cost is serialized LLM flows

Because each session fixture fires lazily and the webhook returns only after the whole flow completes
(timeout budget is 1200s each), the suite runs requirements-review, then the test-case flow, then
execute-tests strictly back-to-back. The flows are mutually independent: requirements review writes Jira
comments; the test-case flow's cases go Draft → Review Complete and never reach Approved; execute-tests
selects only Approved + `automated` (`common/services/zephyr_client.py:196`), i.e. only the seeded
`SMOKE-T100`. A single session fixture that posts all three webhooks via a thread pool, with the three
response fixtures consuming its results, cuts wall time from the sum of flows to the max — likely 2–3×
faster, and it derisks the 45-minute CI job timeout. It also simplifies readiness: wait once for all six
agents instead of the separate `agents_ready` / `execution_stack_ready` polls (one discovery pass registers
all six anyway).

### 2. CI Docker layer caching

The smoke job builds `Dockerfile.base` plus eight compose images cold on every run. Building the base image
with buildx and GHA cache (`cache-from`/`cache-to: type=gha`) and enabling compose build caching would save
minutes per run, since dependencies change far less often than code.

### 3. Compose startup determinism

Add healthchecks to the mocks and agents and use `depends_on: condition: service_healthy` plus
`docker compose up -d --wait`. Today the orchestrator starts against possibly-unready mocks and the suite
absorbs it with 120s/240s polling loops; healthchecks make startup deterministic and let those loops shrink.

### 4. Build the mock image once

Four compose services build the identical context + `tests/smoke/mocks/Dockerfile`. BuildKit dedupes most of
it, but giving one service `image: smoke-mocks:latest` with the `build:` block and having the other three
just reference the image makes it a single explicit build.

## Suggested implementation order

1. Mock hazard fix (coverage #4) and assertion tightening (coverage #3) — small, protect correctness.
2. Concurrent webhooks (performance #1) — biggest wall-clock win.
3. `/execute-tests` reporting assertions (coverage #2) — cheap, LLM-free.
4. `/update-rag-db` coverage (coverage #1) — closes the only untested flow.
5. CI/compose optimizations (performance #2–#4).
