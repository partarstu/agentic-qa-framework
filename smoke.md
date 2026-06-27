# Smoke Test Rework Plan

## Goal

Replace today's deployed-environment smoke suite (remote `SMOKE_*` HTTP probes + a
real-LLM end-to-end task) with a **hermetic, containerized integration test** that:

1. Mocks only the **external boundaries** (Jira MCP server, Jira REST client, Zephyr
   client).
2. Runs **all of our own code for real** — orchestrator + agents + services — and drives
   it through the orchestrator's **public HTTP endpoints** with mock inputs. Real A2A
   discovery and dispatch, no internal mocking.
3. Asserts on **what reaches the mocked boundary** (non-empty review to Jira/MCP, real
   test cases to Zephyr, non-empty review comment to Zephyr, labels to Zephyr).

## Locked decisions

| Decision | Choice |
|---|---|
| LLM | **Real** Gemini (`google-gla:gemini-3.5-flash`, needs `GOOGLE_API_KEY`) — drives both orchestrator routing and every agent's output |
| Topology | **Containers / docker-compose** |
| Existing remote-probe suite | **Replace it** |
| Flow coverage | **Just the two named flows** (requirements review; test-case generation→classification→review) |
| Run target | **docker-compose + GitHub Actions CI**; retire the Cloud Run Job smoke step + `Dockerfile.smoke` |
| LLM credentials | **`GOOGLE_API_KEY` as a CI secret** — real Gemini calls on every run |

## Components that run for real (our code, existing Dockerfiles)

Orchestrator + 4 agents:

- `requirements_review`
- `test_case_generation`
- `test_case_classification`
- `test_case_review`

`incident_creation` and the test-execution path are **excluded** (not in the named flows).

The orchestrator discovers agents by scanning `REMOTE_EXECUTION_AGENT_HOSTS` ×
`AGENT_DISCOVERY_PORTS`. No Qdrant / embedding / prompt-guard needed: none of the 4 agents
pass `vector_db_collection_name`, and `PROMPT_INJECTION_CHECK_ENABLED` defaults off (kept
off).

## External boundaries to mock

| Boundary | Used by | Mock must serve |
|---|---|---|
| **Jira MCP server** (`MCPServerSSE` SSE, = `mcp-atlassian`) | all 4 agents — fetch story / download attachments / (maybe) comment | SSE MCP server advertising `jira_get_issue`, `jira_download_attachments` (+ `jira_add_comment`), seeded with a canned user story that has **no** attachments (so no shared volume needed) |
| **Jira REST** (`jira` Python lib in `add_jira_comment`) | requirements_review — post the review comment | minimal Jira REST (`serverInfo` + add-comment) |
| **Zephyr Scale REST** (`ZephyrClient`, httpx) | tc_generation (create test cases + steps + links), tc_review (review comment + status), tc_classification (labels) | `/testcases*`, `/teststeps`, `/links/issues`, `/statuses`, `/testcases/{k}` GET/PUT |

## Assertions (read back from the mocks' introspection endpoints)

- **Requirements review** (`POST /new-requirements-available`) → a **non-empty** comment
  reached the Jira REST **or** MCP mock.
- **TC generation** (`POST /story-ready-for-test-case-generation`) → the Zephyr mock
  received `POST /testcases` carrying **real test cases** (non-empty name + steps).
- **TC review** (same webhook, later stage) → Zephyr mock received a **non-empty**
  "Review Comments" value.
- **TC classification** (same webhook, middle stage) → Zephyr mock received **labels**.

## Files

### New
- `docker-compose.smoke.yml` — 4 mocks + orchestrator + 4 agents. Each agent on `:8001`
  with its service name as host; orchestrator gets
  `REMOTE_EXECUTION_AGENT_HOSTS=<4 hosts>`, `AGENT_DISCOVERY_PORTS=8001-8001`, real
  `GOOGLE_API_KEY`, all `*_URL` pointed at the mocks, `PROMPT_INJECTION_CHECK_ENABLED=false`.
- `tests/smoke/mocks/` — three recording mock apps + their own `Dockerfile`:
  - `jira_mcp_mock` (SSE MCP: `jira_get_issue`, `jira_download_attachments`,
    `jira_add_comment`; seeds one attachment-free story),
  - `jira_rest_mock` (minimal `serverInfo` + add-comment for the `jira` lib),
  - `zephyr_mock` (the `/testcases*`, `/teststeps`, `/links/issues`, `/statuses`,
    `/testcases/{k}` surface),
  - each exposing `/__recorded` for assertions.

### Rewritten
- `tests/smoke/conftest.py` + `tests/smoke/test_smoke.py` — drop the `SMOKE_*` remote
  probes; new driver waits for the 4 agents to register, fires
  `POST /new-requirements-available` then `POST /story-ready-for-test-case-generation`,
  polls the mocks, and asserts the four outcomes.

### Edited
- `.github/workflows/ci.yml` — replace the deploy-smoke wiring with a job that
  `docker compose -f docker-compose.smoke.yml up`, runs `pytest tests/smoke -m smoke`,
  tears down; `GOOGLE_API_KEY` from `secrets`.
- `cloudbuild.yaml` — remove the smoke-image build/push and the Cloud Run Job smoke step +
  the now-unused `_RUN_SMOKE_TESTS` / `SMOKE_*` substitutions.

### Deleted
- `Dockerfile.smoke`.

### Untouched
- `calm/` — the prod architecture is unchanged; the smoke topology just omits
  `incident_creation`. (Confirm the CALM gate isn't keyed on the smoke suite.)

## Risks

- Real-LLM path makes the suite slow, non-deterministic, and billed per run.
- The MCP mock must advertise tool names/descriptions close enough to `mcp-atlassian` that
  the model picks them — the fiddliest part. Mitigated by seeding an attachment-free story.

## Verifiable milestones

1. Mocks build + respond in isolation → unit-hit each.
2. `docker compose up` → orchestrator `/api/dashboard/agents` shows all 4 healthy →
   registration assertion passes.
3. Both webhooks drive the flows → mock `/__recorded` shows the expected payloads → suite
   green.
4. CI job + cloudbuild/Dockerfile cleanup; CALM gate unaffected.
