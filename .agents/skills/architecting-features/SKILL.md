---
name: architecting-features
description: Designs new features or changes to existing behaviour in the QuAIA framework and produces a compact implementation plan for user approval, covering code reuse, research of the libraries involved, the architecture-first CALM check on a temporary copy, smoke-suite impact and verification steps. Use before implementing a new agent, workflow, integration or other non-trivial change, or when the user asks for a design or architectural advice.
---

# Architecting Features

Produce an approved plan before writing code. Scale the plan to the change: a small fix needs a few lines, a new agent or integration needs the full template.

Copy this checklist and track progress:

```
- [ ] 1. Understand the request
- [ ] 2. Study the existing code
- [ ] 3. Research the libraries and APIs involved
- [ ] 4. Architecture first (CALM)
- [ ] 5. Design
- [ ] 6. Write the plan and get approval
- [ ] 7. Hand off
```

## 1. Understand the request

Restate the goal and list your assumptions.

## 2. Study the existing code

Find the closest existing implementation and follow its structure. List what the change reuses, and plan the extraction of logic that cannot be reused as it is.

## 3. Research

Research every library, protocol or external API the change touches for the version pinned in `pyproject.toml` (pydantic-ai, a2a-sdk, FastAPI, Pydantic, qdrant-client, jira), preferring official docs and changelogs over blog posts. Mention a source in the plan only where it drives a design decision.

## 4. Architecture first (CALM)

Decide whether the change is an architecture change as *Architecture first (CALM)* in `AGENTS.md` defines it. If it is, carry out steps 1-5 of that procedure now. The plan written in step 6 records the approval in its *Architecture* section, and its TODO list carries step 7: applying the approved elements to `calm/` together with the code that realises them, and validating the result.

## 5. Design

Decide and justify each point that applies, in one line each:

- **Components**: which modules change and which are new. Prefer extending existing modules over new abstractions.
- **Alternatives**: for a significant choice, name the chosen option and why.
- **Smoke and A/B suites**: the updates *Smoke suite* and *A/B suite* in `AGENTS.md` require (smoke tests, scripted answers of the LLM mock, an A/B test, baselines to refresh), or that none is needed.
- **Security**: how external input, secrets and untrusted text reaching an LLM are handled (*Project conventions* in `AGENTS.md`, `PYTHON_GUIDELINES.md` § 11).
- **Python design**: data models, error handling and the concurrency model follow `PYTHON_GUIDELINES.md` (§ 5, § 7, § 9).
- **Dependencies**: a new package must meet `PYTHON_GUIDELINES.md` § 15.
- **Configuration**: new settings and their environment variables.
- **Versions**: every agent, and the orchestrator, whose logic the change alters, with the bump *Versioning* in `AGENTS.md` prescribes.

Add a Mermaid diagram only when the interaction is not obvious from the text, such as a new multi-agent sequence.

## 6. Write the plan and get approval

Write the plan with [resources/implementation_plan_template.md](resources/implementation_plan_template.md), omitting sections that do not apply. Keep it compact: architecture, logic and data workflows, impact and the steps; no explanatory prose and no restated code.

The summary in your reply names the decisions needing the user's input (trade-offs, new dependencies, security-sensitive choices) and asks for approval. Do not start implementing before the user approves.

## 7. Hand off

| Change                                | Continue with                              |
|---------------------------------------|--------------------------------------------|
| Implement with review and test loops  | `implementing-changes`                     |
| New agent                             | `creating-new-agent`                       |
| New or extended orchestrator workflow | `adding-orchestrator-workflow`             |
| Tests                                 | `writing-unit-tests`, `running-unit-tests` |
| Ready for review                      | `preparing-pull-requests`                  |
