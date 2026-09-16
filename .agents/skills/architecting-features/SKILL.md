---
name: architecting-features
description: Designs new features or changes to existing behaviour in the QuAIA framework and produces an implementation plan for user approval, covering code reuse, research of the libraries involved, CALM architecture impact, smoke-suite impact and verification steps. Use before implementing a new agent, workflow, integration or other non-trivial change, or when the user asks for a design or architectural advice.
---

# Architecting Features

Produce an approved plan before writing code. Scale the plan to the change: a small fix needs a few lines, a new agent
or integration needs the full template.

Copy this checklist and track progress:

```
- [ ] 1. Understand the request
- [ ] 2. Study the existing code
- [ ] 3. Research the libraries and APIs involved
- [ ] 4. Design
- [ ] 5. Write the plan and get approval
- [ ] 6. Hand off to the implementing skill
```

## 1. Understand the request

- Restate the goal and list your assumptions.
- If the request allows several interpretations, present them and ask; do not pick one silently.
- If a simpler approach meets the need, propose it.

## 2. Study the existing code

- Find the closest existing implementation and follow its structure: agents in `agents/requirements_review/`,
  workflows in `orchestrator/main.py`, integrations in `common/services/`, settings in `config.py`.
- List what the change reuses. Existing logic must not be duplicated; if it cannot be reused as-is, plan its extraction.

## 3. Research

Search the web for the official documentation of every library, protocol or external API the change touches, for the
version pinned in `pyproject.toml` (pydantic-ai, a2a-sdk, FastAPI, Pydantic, qdrant-client, jira). Prefer official
docs and changelogs over blog posts, and record the sources in the plan.

## 4. Design

Decide and justify each point that applies:

- **Components**: which modules change and which are new. Prefer extending existing modules over new abstractions.
- **Alternatives**: for significant choices, compare two or three options briefly and recommend one.
- **Architecture as code**: a new, removed or renamed service, integration edge or security control requires an update
  to `calm/architecture/quaia.arch.json`, and to `calm/patterns/quaia.pattern.json` if it must be enforced. In-process
  changes need none.
- **Smoke suite**: a new or changed end-to-end behaviour requires a `tests/smoke/` update (test, recording mock, compose
  service, or an A/B baseline refresh when agent output changes intentionally). Otherwise state that none is needed.
- **Security**: external input validated with Pydantic, secrets only from env vars, new endpoints behind
  `_validate_api_key`, untrusted text reaching an LLM screened by the prompt-injection guard.
- **Python design**: data models, error handling and the concurrency model follow `PYTHON_GUIDELINES.md` (§ 5, § 7,
  § 9).
- **Dependencies**: a new package must meet `PYTHON_GUIDELINES.md` § 15.
- **Configuration**: new settings go in `config.py`, read from SCREAMING_SNAKE_CASE env vars, and are documented in the
  README *Environment Variables* block.

Add a Mermaid diagram only when the interaction is not obvious from the text, such as a new multi-agent sequence.

## 5. Write the plan and get approval

Write the plan in the conversation using [resources/implementation_plan_template.md](resources/implementation_plan_template.md),
omitting sections that do not apply. Save it to a file only if the user asks.

Then stop and ask for approval, listing the decisions that need the user's input: trade-offs, new dependencies and
security-sensitive choices. Do not start implementing before the user approves.

## 6. Hand off

| Change                               | Continue with                                 |
|--------------------------------------|-----------------------------------------------|
| Implement with review and test loops | `implementing-changes`                        |
| New agent                            | `creating-new-agent`                          |
| New or extended orchestrator workflow | `adding-orchestrator-workflow`               |
| Tests                                | `writing-unit-tests`, `running-unit-tests`    |
| Ready for review                     | `preparing-pull-requests`                     |
