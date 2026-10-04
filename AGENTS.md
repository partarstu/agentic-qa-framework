## Project

QuAIA orchestrator and its A2A agents (requirements review, test case design - which runs the test case generation, review and classification agents in-process - and incident creation), written in Python with pydantic-ai, FastAPI and the A2A SDK and managed with `uv`. The UI and API test-execution agents live in the separate `test-execution-agents` repository.

* Agents are in `agents/<agent_name>/`, orchestrator workflows in `orchestrator/main.py`, models in `common/models.py`, integrations in `common/services/`, settings in `config.py`, tests in `tests/` mirroring the source tree, the architecture model in `calm/`.
* The language guidelines are [PYTHON_GUIDELINES.md](PYTHON_GUIDELINES.md): follow them in every Python change and check them in every review. Project skills are in `.agents/skills/`.
* Local development is on Windows 11 in PyCharm; CI (`.github/workflows/ci.yml`) runs on ubuntu-latest.

## Commands

Run from the repository root unless noted; if imports of third-party packages fail, run `uv sync` first.

* Unit tests: `uv run pytest` (`pytest.ini` deselects the smoke and A/B tests); one file: `uv run pytest tests/<path>/test_<module>.py -v`; with coverage, as CI runs them: `uv run pytest --cov=. --cov-report=term-missing`.
* Lint, the CI gate: `uv run ruff check .`
* CALM validation, run from `calm/` or from its temporary copy; a clean run prints `No issues found.` and exits `0`:
  ```bash
  npx -y @finos/calm-cli@1.46.0 validate -p patterns/quaia.pattern.json -a architecture/quaia.arch.json -u url-mapping.json --strict -f pretty
  ```
* CALM rendering, run from the temporary copy of `calm/`; the diagram is in `docs/index.md` of the output:
  ```bash
  npx -y @finos/calm-cli@1.46.0 docify -a architecture/quaia.arch.json -o <another directory outside the repository>
  ```
* Smoke and A/B suites: see *Smoke suite* and *A/B suite*.

## Project conventions

* Agents subclass `common.agent_base.AgentBase`, which handles prompt-injection screening, agent registration, activity streaming and the `report_activity` tool, so a prompt template never mentions that tool. Agents take MCP access as `mcp_toolset_factories`, never as live toolsets, and their structured results inherit `BaseAgentResult`.
* Every orchestrator workflow endpoint depends on `_validate_api_key`, and a Jira webhook endpoint first calls `_verify_jira_webhook_signature`. An endpoint puts `except HTTPException: raise` before `except Exception`; otherwise the 4xx raised by `_handle_exception` becomes a 500 and the error is recorded twice.
* External input is validated with Pydantic models, and untrusted text that reaches an LLM goes through the prompt-injection guard.
* New settings live in `config.py`, are read from SCREAMING_SNAKE_CASE environment variables and are documented in the README *Environment Variables* block. Configuration keys in `.toml`, `.ini` and `.yaml` files are snake_case.
* A new `.py` file starts with the SPDX header of the existing files (the first three lines of `config.py`); empty `__init__.py` files are the exception.

## Unit tests

* `tests/conftest.py` sets dummy API keys and environment variables, disables the prompt-injection checks and stubs `sentence_transformers`; a setting newly required at import time gets its test value there.
* a2a-sdk types follow the current 1.x API with snake_case fields (`Part(text=...)`, `Part(raw=..., media_type=...)`); errors on `root`, `artifactId` or `mimeType` mean a test still uses the old 0.x API.
* Endpoint tests override authentication with `orchestrator_app.dependency_overrides[_validate_api_key]`; patching `_validate_api_key` has no effect, because `Depends` already holds the original function, and the test gets a `401` or `503`.
* `_handle_exception` and `_record_error` schedule `error_history.add` on the running loop, so a test that reaches them is `async def` and patches `orchestrator.main.error_history` (see `mock_error_history` in `tests/orchestrator/test_parsing_logic.py`); otherwise it fails with `RuntimeError: no running event loop`.
* Module-global state (the agent registry, `dependency_overrides`, `sys.modules` stubs) is reset by a fixture; a test that passes alone but fails in the full run has leaked it.
* Unit tests mock every external boundary: LLM models, MCP toolsets, Jira, Qdrant, test management clients and `httpx`. A slow test or a real network call means a boundary is not mocked.

## Versioning

Every agent and the orchestrator carries a `VERSION` in `config.py`, the default of its `<NAME>_VERSION` environment variable, in the form `MAJOR.MINOR.PATCH`. A change that alters the logic of an agent or of the orchestrator (its prompts, tools, workflow, routing, output content or integration behaviour) bumps that default in the same change, together with the default shown in the README *Environment Variables* block:

* **PATCH** for a fix or an internal change that keeps the observable behaviour and the contract.
* **MINOR** for a backwards-compatible change of behaviour or a new capability (a new tool, a changed prompt, a new workflow step or endpoint, changed output content).
* **MAJOR** for an incompatible change (a changed output model, skill, request contract or endpoint).

A change that touches none of their logic (documentation, tests, tooling, a shared helper refactored without a behaviour change) bumps nothing. A new agent starts at `1.0.0`.

## Architecture first (CALM)

The architecture is modelled with the FINOS CALM standard under `calm/` and gated by the blocking `Architecture (CALM)` CI job. `calm/architecture/quaia.arch.json` holds the services and actors (`nodes`), their integration edges (`relationships`) and their security `controls`; `calm/patterns/quaia.pattern.json` asserts the required ones; `calm/README.md` lists the controls and their requirement schemas. The CALM CLI is a Node.js 20+ tool run with `npx`, never a dependency in `pyproject.toml`.

An architecture change adds, removes or renames a service, agent, actor or external system, adds or removes an integration edge, or adds, removes or changes a security control (authentication, prompt-injection protection, credential scope, job invocation). In-process changes (a helper, a prompt, a setting, a new endpoint over existing edges) are not architecture changes.

An architecture change is approved before anything is implemented, and checking it leaves nothing in the repository:

1. Copy the whole `calm/` directory to a temporary directory outside the repository (validation needs its URL mapping and control schemas) and draft the change there, mirroring the existing elements: in the architecture, and in the pattern when the element must be enforced.
2. Validate the copy (*Commands*).
3. When the change is more than a single edge, render the copy (*Commands*) and show the user the diagram and the pages of the changed nodes and relationships.
4. Present the draft to the user - what changes in the model and why, the validation result and the diagram - and get their explicit approval.
5. Delete the copy and the rendered output.
6. Record the approval in the *Architecture* section of the plan, which lists the drafted elements, with the line `CALM change validated on a temporary copy and approved by the user on <date>`. A plan that names an architecture change without that line is not ready to be implemented.
7. Only then implement: apply the approved change to `calm/` in the same change as the code and validate it again. `calm/` never changes before the implementation starts.

## Smoke suite

The hermetic smoke suite in `tests/smoke/` runs the real orchestrator and agents under `docker-compose.smoke.yml` with every external boundary mocked, the LLM included: the scripted LLM mock (`tests/smoke/mocks/llm_mock.py`) answers every model call, so the suite needs no key and makes no billed call. It asserts on what reaches those boundaries; CI runs it (the `smoke` job) on every push and pull request. *Hermetic smoke tests* in `README.md` describes the layout.

* A change that adds or extends end-to-end behaviour - a new agent, orchestrator workflow or endpoint, external integration or step in a flow, or a change to what a flow produces - updates the suite in the same change:
    - **New flow**: a test in `tests/smoke/test_smoke.py` (fixtures in `tests/smoke/conftest.py`, recording mocks in `tests/smoke/mocks/`) that drives it through the orchestrator's public endpoints and asserts on what reached the mocked boundary.
    - **Extended flow**: stronger assertions in the existing tests that cover the new behaviour.
    - **New external boundary**: a new or extended recording mock in `tests/smoke/mocks/`, wired into `docker-compose.smoke.yml`.
    - **New or changed LLM call** (a new agent, sub-agent, tool or output model, or a changed tool sequence): its scripted answer in `tests/smoke/mocks/llm_mock.py`; the suite fails on every model call the mock cannot attribute.
* A change that adds no observable end-to-end behaviour (e.g. an internal refactor) needs no smoke change; say so explicitly instead of skipping it silently.
* Run it with:
  ```bash
  docker build -t agentic-qa-base:latest -f Dockerfile.base .
  docker compose -f docker-compose.smoke.yml up -d --build --wait
  uv run pytest tests/smoke -m smoke -v
  docker compose -f docker-compose.smoke.yml down -v
  ```

## A/B suite

The A/B suite in `tests/ab/` runs the smoke topology with the model-driven services on a real model (the `docker-compose.ab.yml` override) and gives every LLM-driven workflow its own A/B test, which compares that workflow's outputs with its committed baseline in `tests/ab/baselines/<name>/` on structural metrics and judged quality and fails on a regression. It never runs automatically: CI runs it only through the manually started `A/B` workflow (`.github/workflows/ab.yml`). *A/B tests against a baseline* in `README.md` describes it.

* A new LLM-driven workflow gets its own A/B test in the same change: an entry in `WORKFLOWS` of `tests/ab/artifacts.py` with its dimensions (snapshot collection, metrics, judge rendering and criteria) and its captured baseline.
* An intentionally changed agent output gets the baselines of the affected workflows refreshed, never loosened checks.
* Never run the A/B suite or refresh a baseline unless the user asks for that run in the conversation (a plan step is not such a request): it needs `GOOGLE_API_KEY` and makes billed model calls. When asked, run only the affected workflows, on a fresh stack:
  ```bash
  GOOGLE_API_KEY=<your-key> docker compose -f docker-compose.smoke.yml -f docker-compose.ab.yml up -d --build --wait
  uv run pytest tests/ab -m ab -k <workflow> -v
  AB_WRITE_BASELINE=1 AB_BASELINE_NAME=<name> uv run pytest tests/ab -m ab -k <workflow>  # refreshes the baseline instead
  docker compose -f docker-compose.smoke.yml -f docker-compose.ab.yml down -v
  ```

<!-- Shared rules: start. This block is identical in the agentic-qa-framework and test-execution-agents repositories; edit it in one of them and copy it unchanged to the other. -->

## Working with the user

* Before implementing a task, present a short plan: what will be implemented and how, as numbered steps with their checks (`1. <step> → verify: <check>`), not every individual change. Wait for the user's confirmation, then carry out the plan without asking them to confirm individual changes.
* When the user or an instruction asks for a plan (an implementation plan, a TO-DO list or similar), write it straight to an .MD file in the `plans` folder and reply with only its path and a short summary; never print the plan in the conversation.
* When a change touches several modules, keep its TO-DO list in an .MD file in the `plans` folder, tick items as you finish them and add what you discover. After a context compaction, re-read that file instead of relying on the conversation.
* Once the plan is confirmed, work until the *Definition of done* is met. Put status notes in the same message as your next action. Never end a turn with a summary that announces the next step without taking it, an offer to continue, or a list of decisions that don't block the work.
* Stop and ask the user only when you can't continue without them, when two readings of the request would lead to materially different work, when an architecture change needs their approval (*Architecture first (CALM)*), before spawning a subagent (*Subagents*), or before anything destructive or outward-facing: deleting files you didn't create, pushing, creating or changing cloud resources, or changing anything outside this repository. Make routine judgement calls yourself.

## Git

* The main branch is `main`. Commit only when the user asks. Commit messages and pull request titles follow Conventional Commits (`feat`, `fix`, `refactor`, `test`, `docs`, `chore`) and stay under 72 characters.
* **Never push** anything to the remote repository (any `git push`, including force-pushes, tags and pushes run by a skill or script) without the user's explicit consent to that specific push in the current conversation. A request to commit, an approved plan, auto mode or consent given for an earlier push is not consent; when in doubt, ask and wait.

## Subagents

* Never start a subagent without the user's explicit consent to that specific spawn, unless a project skill starts it as part of its procedure. If the user doesn't consent, do the work yourself.
* When asking, propose a model and effort for each subagent and whether it forks this conversation or starts with a fresh context, and always offer "no subagents". Spawn exactly what is approved; any extra spawn or resume needs a new approval. If something can't be set per subagent, say so.
* Keep the usage low: the cheapest sufficient model and the effort the task needs, a self-contained prompt with the files and facts already known, a short capped result, a fork when it needs most of the conversation. A subagent never redoes the work of the main agent.

## Coding rules

* Before implementing, state your assumptions. If a simpler approach exists, say so, and push back when warranted.
* Keep the implementation simple and short: no features beyond the request, no abstractions for single-use code, no "flexibility" or "configurability" that wasn't requested, no error handling for impossible scenarios. If you write 200 lines and it could be 50, rewrite it.
* Minimal never means dropping input validation at trust boundaries, error handling that prevents data loss, security controls, or anything explicitly requested. Between two equally small solutions, take the one that is correct on edge cases.
* Every line you change traces directly to the request. Don't improve, refactor or reformat code you don't otherwise change, and match the existing style even if you'd do it differently. Mention unrelated dead code instead of deleting it; the code you write or change leaves nothing redundant behind.
* Before changing code, read every file the change touches and trace the real flow end to end: a small diff in the wrong place is a second bug. Fix a bug at its root: find every caller of the function first, and prefer one fix in the shared code to a guard in each caller.
* Never duplicate existing functionality: reuse it, and if it can't be reused directly, extract it (inheritance or composition) and reuse it.
* Turn tasks into verifiable goals: "add validation" means tests for invalid inputs that then pass, "fix the bug" a test that reproduces it and then passes, "refactor" tests that pass before and after. Never skip, disable (`xfail`, `@Disabled`), delete or weaken a test or an assertion to get a green run.
* When you deliberately choose a simpler solution with a known limit, state the limit and the upgrade path in your summary and in the PR description, not as a code comment.
* Never trust user-supplied data: validate and sanitize every input from outside (requests, webhooks, tool arguments, LLM output) against injection. Secrets come only from environment variables or a secrets manager, never from the source code.
* Never hard-wrap Markdown or any other text file you create or edit: a paragraph, a list item or a table row is one line, however long. This applies to every generated file, including plans, skills, prompts and documentation.

## Comments and docstrings

The code must be self-explanatory: names, types and structure carry the meaning, and a comment is the exception, never the norm. This applies to every file (source, tests, scripts, prompts, templates); the language guidelines fix the syntax.

* A function or method doc comment is one sentence; a class, type, module or package doc comment is at most two sentences. A unit whose name and signature already say what it does gets none.
* Parameter, return and exception sections appear only where a name and its type don't already say it. Texts that the LLM reads as a tool specification (the docstring of a tool an LLM calls, `@Tool`, `@P` and `@Description` texts) always stay complete and precise.
* An inline comment states a non-obvious *why* - a constraint, a workaround, a decision. It never restates *what* the code does and never records history (no plan, work-stream, ticket or "previously" references). Before writing one, try to make the code say it with a better name, a smaller function or an explicit type.
* In the code you change, remove comments and doc comments that violate this rule; leave untouched code as it is.

## Research

Search the web before relying on memory for anything version-sensitive: a library, API or tool you're about to use or upgrade, its flags, an error you don't recognise. Read the most relevant result pages in full with `curl` (`curl.exe` in PowerShell), because the built-in fetch tool returns a summary written by a small model that can drop details crucial to the task. Mark anything you couldn't confirm and say where you looked.

## Context budget

Every turn re-reads the whole context, so its size is the cost:

* Read a file over about 300 lines with search and ranged reads, not whole; never print several files at once; don't re-read a file after editing it.
* Redirect long test or build output to a log file and read only its summary and its failure blocks.

## Temporary files and clean-up

Temporary files - scratch scripts, drafts, PR descriptions, review JSON, copies made for a check - go outside the repository, into the scratchpad directory when there is one. Before reporting a task as done, clean up everything you created temporarily, without being asked: stop the stacks and services you started, remove their containers, networks and volumes and any temporary cloud resources (VMs, disks, firewall rules, tunnels), and delete every file that isn't part of the deliverable. Nothing stays running or lying around "in case it's needed later".

## Definition of done

A change is done when the unit tests of every touched module pass, the affected versions are bumped (*Versioning*), the smoke suite, the A/B suite and the CALM model cover the change (*Smoke suite*, *A/B suite*, *Architecture first (CALM)*), README.md describes the changed behaviour, and everything temporary is cleaned up. Skip what doesn't apply; if you skip something that might look applicable, say why.

Finish every implementation task with a report in three short parts:

* **Blocked on me**: decisions or approvals you need from the user, or "nothing".
* **Changed**: what and where.
* **Found**: known limits of a deliberately simple solution, unrelated dead code, anything you couldn't confirm.

<!-- Shared rules: end -->
