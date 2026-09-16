# PR Review Criteria

## Contents

- Severity levels
- Correctness and design
- Python guidelines (PYTHON_GUIDELINES.md)
- Project rules (AGENTS.md)
- QuAIA-specific checks
- Architecture as code (CALM)
- Hermetic smoke suite

## Severity levels

| Prefix       | Use for                                                                                                    |
|--------------|------------------------------------------------------------------------------------------------------------|
| `[CRITICAL]` | Security hole, data loss, broken behaviour, failing CI gate                                                |
| `[HIGH]`     | Bug risk or unhandled edge case, missing tests, missing CALM or smoke update                               |
| `[MEDIUM]`   | AGENTS.md or PYTHON_GUIDELINES.md violation, duplicated logic, code the change does not need               |
| `[LOW]`      | Naming, style or small clarity issues, optional improvement or alternative approach                        |

CRITICAL, HIGH and MEDIUM findings must be fixed before merge; LOW findings are optional. When the intent of the code is
unclear, rate the finding by the risk it carries if the code is wrong.

## Correctness and design

Review these first; they matter more than style.

- Logic errors and unhandled edge cases: `None`, empty collections, timeouts, partial failures.
- Concurrency and exception-handling defects (`PYTHON_GUIDELINES.md` § 7 and § 9).
- `except HTTPException: raise` before a generic `except Exception` in endpoints.
- Logic duplicated from `common/` or `orchestrator/` instead of reused.
- Abstractions, options or code beyond what the change needs.

## Python guidelines (PYTHON_GUIDELINES.md)

Check every changed Python line, tests included, against `PYTHON_GUIDELINES.md` and cite the section in the comment
(e.g. "`PYTHON_GUIDELINES.md` § 4") instead of restating the rule.

## Project rules (AGENTS.md)

Check the changed code against the coding guidelines in `AGENTS.md` and cite the rule in the comment instead of
restating it. The most frequent findings:

- Unrelated reformatting or refactoring mixed into the diff.
- Secrets in code, or external input used without validation.
- New `.py` files without the SPDX header used by existing files.
- Config keys not in snake_case, environment variables not in SCREAMING_SNAKE_CASE.

## QuAIA-specific checks

- Orchestrator workflow endpoints depend on `_validate_api_key`; Jira webhook endpoints call
  `_verify_jira_webhook_signature`.
- Agents subclass `AgentBase`, pass MCP access as `mcp_toolset_factories` rather than live toolsets, and do not mention
  `report_activity` in prompt templates.
- Agent results inherit `BaseAgentResult`.
- New settings live in `config.py`, read environment variables and are documented in `README.md`.
- a2a-sdk types use the current 1.x API (snake_case fields, `Part(text=...)`).
- Unit tests mock every external boundary: LLM, MCP, Jira, Qdrant, test management systems, HTTP clients.

## Architecture as code (CALM)

The architecture under `calm/` is validated by the blocking `Architecture (CALM)` CI job. When the PR changes the
component topology, check that:

- A new, removed or renamed service or agent is reflected in `calm/architecture/quaia.arch.json` and asserted in
  `calm/patterns/quaia.pattern.json`.
- A new integration edge (orchestrator to agent, agent to service, outbound external call) appears as a `relationship`.
- A new or changed security control (authentication, prompt-injection protection) appears as a `controls` block on the
  relevant node or relationship.

A PR that adds an agent or integration without the CALM update is incomplete: `[HIGH]`.

## Hermetic smoke suite

The smoke suite under `tests/smoke/` is enforced by the `smoke` CI job. When the PR changes observable end-to-end
behaviour, check that:

- A new agent, orchestrator endpoint or external integration is exercised by a test in `tests/smoke/test_smoke.py`,
  with the fixtures, recording mocks under `tests/smoke/mocks/` and `docker-compose.smoke.yml` services it needs.
- A change to what an existing flow produces is covered by strengthened assertions.
- An intentional change to agent output comes with a refreshed baseline under `tests/smoke/baselines/`, not loosened
  checks.

A PR that adds or extends an end-to-end flow without smoke coverage is incomplete: `[HIGH]`. A pure internal refactor
is exempt; confirm that it really is one.
