---
name: architecting-features
description: Designs new features or changes to existing behaviour in the QuAIA framework and produces a compact implementation plan for user approval, covering code reuse, research of the libraries involved, the architecture-first CALM update, smoke-suite impact and verification steps. Use before implementing a new agent, workflow, integration or other non-trivial change, or when the user asks for a design or architectural advice.
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

- Restate the goal and list your assumptions.
- If the request allows several interpretations, present them and ask; do not pick one silently.
- If a simpler approach meets the need, propose it.

## 2. Study the existing code

- Find the closest existing implementation and follow its structure: agents in `agents/`, workflows in `orchestrator/main.py`, integrations in `common/services/`, settings in `config.py`.
- List what the change reuses. Existing logic must not be duplicated; if it cannot be reused as-is, plan its extraction.

## 3. Research

Search the web for the official documentation of every library, protocol or external API the change touches, for the version pinned in `pyproject.toml` (pydantic-ai, a2a-sdk, FastAPI, Pydantic, qdrant-client, jira). Prefer official docs and changelogs over blog posts. Mention a source in the plan only where it drives a design decision.

## 4. Architecture first (CALM)

Decide whether the change alters the architecture: a service, agent, actor or external system is added, removed or renamed; an integration edge appears or disappears; a security control (authentication, prompt-injection protection, credential scope, job invocation) is added, removed or changed. In-process changes (a helper, a prompt, a setting, a new endpoint over existing edges) do not.

If it does, the architecture comes first and the implementation waits, as *Architecture first* in `AGENTS.md` requires:

1. Update `calm/architecture/quaia.arch.json`, and `calm/patterns/quaia.pattern.json` when the element must be enforced, mirroring the existing nodes, relationships and controls (`calm/README.md` lists the controls and their requirement schemas).
2. Validate from `calm/`; a clean run prints `No issues found.`:
   ```bash
   npx -y @finos/calm-cli@1.46.0 validate -p patterns/quaia.pattern.json -a architecture/quaia.arch.json -u url-mapping.json --strict -f pretty
   ```
3. When the change is more than a single edge, render the documentation outside the repository and show the user the Mermaid diagram in `docs/index.md` and the pages of the changed nodes and relationships:
   ```bash
   npx -y @finos/calm-cli@1.46.0 docify -a architecture/quaia.arch.json -o <directory outside the repository>
   ```
4. Present the architecture change to the user: what changed in the model and why, the validation result and the rendered diagram. Get their explicit approval; when the plan is written in step 6, its *Architecture* section records that approval with the date.

Nothing is implemented before the architecture is validated and approved. The updated CALM files stay in the working tree as part of the change.

## 5. Design

Decide and justify each point that applies, in one line each:

- **Components**: which modules change and which are new. Prefer extending existing modules over new abstractions.
- **Alternatives**: for a significant choice, name the chosen option and why.
- **Smoke suite**: a new or changed end-to-end behaviour requires a `tests/smoke/` update (test, recording mock, compose service, or an A/B baseline refresh when agent output changes intentionally). Otherwise state that none is needed.
- **Security**: external input validated with Pydantic, secrets only from env vars, new endpoints behind `_validate_api_key`, untrusted text reaching an LLM screened by the prompt-injection guard.
- **Python design**: data models, error handling and the concurrency model follow `PYTHON_GUIDELINES.md` (§ 5, § 7, § 9).
- **Dependencies**: a new package must meet `PYTHON_GUIDELINES.md` § 15.
- **Configuration**: new settings go in `config.py`, read from SCREAMING_SNAKE_CASE env vars, and are documented in the README *Environment Variables* block.
- **Versions**: name every agent, and the orchestrator, whose logic the change alters, with the bump *Versioning* in `AGENTS.md` prescribes.

Add a Mermaid diagram only when the interaction is not obvious from the text, such as a new multi-agent sequence.

## 6. Write the plan and get approval

Write the plan in the conversation using [resources/implementation_plan_template.md](resources/implementation_plan_template.md), omitting sections that do not apply. Keep it compact: architecture, logic and data workflows, impact and the steps; no explanatory prose, no restated code, no hard wraps. Save it to a file only if the user asks.

Then stop and ask for approval, listing the decisions that need the user's input: trade-offs, new dependencies and security-sensitive choices. Do not start implementing before the user approves.

## 7. Hand off

| Change                                | Continue with                              |
|---------------------------------------|--------------------------------------------|
| Implement with review and test loops  | `implementing-changes`                     |
| New agent                             | `creating-new-agent`                       |
| New or extended orchestrator workflow | `adding-orchestrator-workflow`             |
| Tests                                 | `writing-unit-tests`, `running-unit-tests` |
| Ready for review                      | `preparing-pull-requests`                  |
