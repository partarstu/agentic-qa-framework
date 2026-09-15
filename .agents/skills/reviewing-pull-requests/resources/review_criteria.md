# PR Review Criteria

## Contents

- Severity levels
- Correctness and design
- Project rules (AGENTS.md)
- QuAIA-specific checks
- Architecture as code (CALM)
- Hermetic smoke suite

## Severity levels

| Prefix         | Use for                                                                                      |
|----------------|----------------------------------------------------------------------------------------------|
| `[CRITICAL]`   | Must fix before merge: security hole, data loss, broken behaviour, failing CI gate           |
| `[MAJOR]`      | Should fix: bug risk, missing tests, missing CALM or smoke update, AGENTS.md violation        |
| `[MINOR]`      | Naming, style or small clarity issues                                                        |
| `[SUGGESTION]` | Optional improvement or alternative approach                                                 |
| `[QUESTION]`   | Intent is unclear; ask the author                                                            |

## Correctness and design

Review these first; they matter more than style.

- Logic errors and unhandled edge cases: `None`, empty collections, timeouts, partial failures.
- Async pitfalls: un-awaited coroutines, blocking calls inside `async def`, shared state mutated without a lock,
  fire-and-forget tasks whose exceptions are lost.
- Exceptions: no bare `except:`, nothing swallowed silently, `except HTTPException: raise` before a generic
  `except Exception` in endpoints.
- Logic duplicated from `common/` or `orchestrator/` instead of reused.
- Abstractions, options or code beyond what the change needs.

## Project rules (AGENTS.md)

Check the changed code against the coding guidelines in `AGENTS.md` and cite the rule in the comment instead of
restating it. The most frequent findings:

- Missing type hints or docstrings on public functions and classes.
- Unrelated reformatting or refactoring mixed into the diff.
- Secrets in code, or external input used without validation.
- Dependencies in the wrong `pyproject.toml` table, or `uv.lock` not regenerated.
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

A PR that adds an agent or integration without the CALM update is incomplete: `[MAJOR]`.

## Hermetic smoke suite

The smoke suite under `tests/smoke/` is enforced by the `smoke` CI job. When the PR changes observable end-to-end
behaviour, check that:

- A new agent, orchestrator endpoint or external integration is exercised by a test in `tests/smoke/test_smoke.py`,
  with the fixtures, recording mocks under `tests/smoke/mocks/` and `docker-compose.smoke.yml` services it needs.
- A change to what an existing flow produces is covered by strengthened assertions.
- An intentional change to agent output comes with a refreshed baseline under `tests/smoke/baselines/`, not loosened
  checks.

A PR that adds or extends an end-to-end flow without smoke coverage is incomplete: `[MAJOR]`. A pure internal refactor
is exempt; confirm that it really is one.
