## Project

QuAIA orchestrator and its A2A agents (requirements review, test case design - which runs the test case generation, review and classification agents in-process - and incident creation), written in Python with pydantic-ai, FastAPI and the A2A SDK and managed with `uv`; the UI and API test-execution agents live in the separate `test-execution-agents` repository. Project skills are in `.agents/skills/` (Claude Code reads them through a `.claude/skills` symlink to that folder). Local development is on Windows 11; CI runs on ubuntu-latest.

## Git Repo

* The main branch for this project is called "main".

## General development guidelines and rules

### Planning and progress

* Before implementing a task, present its general plan in a very short and concise form: what will be implemented and how, as numbered steps with their checks (`1. [step] → verify: [check]`), not every individual change. Wait for the user's confirmation, then carry out the plan without asking the user to confirm individual changes.
* When asked by the user or instruction to create a plan (implementation plan, TO-DO list or similar), write it straight to an .MD file in the "plans" folder of this project and reply with only its path and a short summary. Never print the plan in the conversation.
* When a change touches several modules, keep its TO-DO list in an .MD file in the "plans" folder, tick items as you finish them and add what you discover. After a context compaction, re-read that file instead of relying on the conversation.

### When to keep going and when to stop

* Once the user has confirmed the plan, work until the *Definition of done* is met. When a step doesn't need the user's input, keep going and put status notes in the same message as your next action. Don't end a turn with a summary that announces the next step without taking it, an offer to continue, or a list of decisions that don't block the work.
* Stop and ask the user only when you can't continue without them, when two readings of the request would lead to materially different work, when the architecture needs their approval (*Architecture first* below), or before anything destructive or outward-facing: deleting files you didn't create, force-pushing, creating or changing cloud resources, or changing anything outside this repository. Commit or push only when the user asks.

### Coding guidelines and rules

* Before implementing, state your assumptions. If the request has readings that would lead to materially different work, present them and ask; make routine judgement calls yourself. If a simpler approach exists, say so and push back when warranted.
* Keep your implementation simple and short:
    - No features beyond what was asked.
    - No abstractions for single-use code.
    - No "flexibility" or "configurability" that wasn't requested.
    - No error handling for impossible scenarios.
    - If you write 200 lines and it could be 50, rewrite it.
* When editing existing code:
    - Don't "improve" adjacent code, comments, or formatting.
    - Don't refactor things that aren't broken.
    - Match existing style, even if you'd do it differently.
    - If you notice unrelated dead code, mention it - don't delete it. Code you write or change leaves nothing redundant behind.
* Before changing code, read every file the change touches and trace the real flow end to end. A small diff in the wrong place is a second bug, not a small change.
* Fix bugs at the root: before editing a function, find every caller. One fix in the shared code beats a guard in each caller, and a fix that covers only the reported path leaves the other callers broken.
* Between two equally small solutions, take the one that is correct on edge cases. Less code never means the flimsier algorithm.
* Minimal never means dropping input validation at trust boundaries, error handling that prevents data loss, security controls, or anything that was explicitly requested.
* When you deliberately choose the simpler solution with a known limit, state the limit and the upgrade path in your summary and in the PR description, not as a code comment.
* Every changed by you line of code should trace directly to the user's request.
* Transform tasks into verifiable goals:
    - "Add validation" → "Write tests for invalid inputs, then make them pass"
    - "Fix the bug" → "Write a test that reproduces it, then make it pass"
    - "Refactor X" → "Ensure tests pass before and after".
* Search the web before relying on memory for anything version-sensitive: a library, API or tool you're about to use or upgrade, its flags, an error you don't recognise. Read the most relevant result pages in full with the `curl` command (`curl.exe` in PowerShell), because the built-in fetch tool returns a summary written by a small model that can drop details crucial to the task, while `curl` returns the page in its original form and leaves the judgement to you. Mark anything you couldn't confirm and say where you looked.
* Never reformat the code which you haven't modified!
* Never hard-wrap Markdown or any other text file you create or edit: a paragraph, a list item or a table row is one line, however long it gets. The files are read in an editor with soft wraps, so hard wraps only add noise. This applies to every generated file, including plans, skills, prompts and documentation.
* You're working with a project which is always used in PyCharm.
* Never duplicate existing functionality. If you've noticed any existing logic or functionality which you need for your implementation, always reuse it. If reusing it directly can't be done, always extract it so that it's accessible (inheritance or composition) and then reuse it.
* Always clean up everything you created temporarily during a task before reporting it as done, without being asked: tear down any stack you started (e.g. `docker compose -f docker-compose.smoke.yml down -v`), remove containers, networks and volumes, and delete scratch scripts, outputs, probe baselines and any other file that isn't part of the deliverable. Never leave such things running or lying around "in case they're needed later".
* Never trust user-supplied data. Always validate and sanitize inputs to prevent injection attacks (e.g., SQL injection, XSS).
* Store secrets like API keys and passwords in environment variables or a secrets management tool, never hardcoded in the source code.

### Comments and docstrings

The code must be self-explanatory: names, types and structure carry the meaning, and a comment is the exception, never the norm. This rule applies to every file (source, tests, scripts, templates) and is enforced by every skill that writes or reviews code.

* A function or method docstring is one sentence. A class or module docstring is at most two sentences. Add `Args`, `Returns` or `Raises` only where a name and its type hint do not already say it, and always for the tools an LLM calls, because their docstring is the tool specification the model reads.
* A module, class, function or method whose name and signature already say what it does gets no docstring at all.
* An inline comment states a non-obvious *why*: a constraint, a workaround, a decision. It never restates *what* the code does and never records history (no plan, work-stream, ticket or "previously" references).
* When a comment seems necessary, first make the code say it (a better name, a smaller function, an explicit type); write the comment only if that fails.
* In the code you change, remove comments and docstrings that violate this rule; leave untouched code as it is, and never add one that does.

### Versioning of agents and the orchestrator

Every agent and the orchestrator carries a `VERSION` in `config.py` (the default of its `<NAME>_VERSION` environment variable) in the form `MAJOR.MINOR.PATCH`. Whenever a change alters the logic of an agent or of the orchestrator (its prompts, tools, workflow, routing, output content or integration behaviour), bump that default in the same change and update the default shown in the README *Environment Variables* block:

* **PATCH** for a fix or an internal change that keeps the observable behaviour and the contract unchanged.
* **MINOR** for a backwards-compatible change of behaviour or a new capability (a new tool, a changed prompt, a new workflow step, changed output content).
* **MAJOR** for an incompatible change (a changed output model, skill, request contract or endpoint).

A change that touches none of their logic (documentation, tests, tooling, a shared helper refactored without a behaviour change) bumps nothing. A new agent starts at `1.0.0`.

### Python development guidelines

All Python-specific rules (language version, style and naming, type hints, data modelling, errors and exceptions, logging, concurrency, security pitfalls, performance, testing, docstrings, dependencies and the `uv` environment) are in [PYTHON_GUIDELINES.md](PYTHON_GUIDELINES.md). Follow them in every Python change and check them in every review.

### Architecture as Code (CALM)

The system architecture is described as code with the [FINOS CALM](https://calm.finos.org/) standard under the `calm/` directory, and it is enforced by a **blocking** CI job (`Architecture (CALM)` in `.github/workflows/ci.yml`). Treat the CALM model as a first-class part of the codebase, on par with the source and the tests.

* `calm/architecture/quaia.arch.json` is the source of truth for the services/actors (`nodes`), their integration edges (`relationships`) and the security `controls` attached to them.
* `calm/patterns/quaia.pattern.json` is the governance pattern that asserts the required nodes, relationships and controls are present; it is what makes the gate fail on drift.
* Whenever a change adds, removes or renames a service, an integration edge, or a security control (e.g. a new agent, a new orchestrator-to-service call, a new authentication mechanism), you **must** update the CALM model in the same change, and extend the pattern if the new element is part of the contract you want enforced.
* **Architecture first.** Such a change is never implemented before its architecture is checked and approved, and checking it creates no artifact in the repository. The order is fixed: (1) copy the whole `calm/` directory to a temporary directory outside the repository and draft the change there, in the architecture and in the pattern when the element is enforced; (2) validate the copy with the command below, run from the copy; (3) when the change is more than a single edge, render the copy with `npx -y @finos/calm-cli@1.46.0 docify -a architecture/quaia.arch.json -o <another directory outside the repository>` and show the user the resulting diagram and pages; (4) present the drafted architecture to the user and get their explicit approval; (5) delete the temporary copy and the rendered output; (6) only then implement, applying the approved change to `calm/` in the same change as the code and validating it again. Implementing a change whose architecture was not validated and approved is not allowed, and neither is changing `calm/` before the implementation starts.
* The CALM CLI is a Node tool, not a Python dependency — it is invoked via `npx @finos/calm-cli` and requires Node.js 20+. It does **not** belong in `pyproject.toml`.
* Validate locally before committing (run from the `calm/` directory):
  ```bash
  npx -y @finos/calm-cli@1.46.0 validate -p patterns/quaia.pattern.json -a architecture/quaia.arch.json -u url-mapping.json --strict -f pretty
  ```
  A clean run prints `No issues found.` and exits `0`. See `calm/README.md` for the full layout and the list of enforced controls.

### Hermetic smoke suite

The hermetic smoke suite under `tests/smoke/` is the end-to-end safety net for the whole system: it runs the real orchestrator and agents under `docker-compose.smoke.yml` (driven by a real Gemini model) with only the external boundaries mocked, and asserts on what reaches each boundary. It is enforced by the `smoke` CI job in `.github/workflows/ci.yml`. Treat the smoke suite as a first-class part of the codebase, on par with the source, the unit tests and the CALM model.

* Whenever a change adds a new capability or extends an existing one — a new agent, a new orchestrator workflow/endpoint, a new external integration, a new step in an existing flow, or a change to what an existing flow produces — you **must** update the smoke suite in the same change so the new or changed behaviour is exercised and asserted end-to-end:
    - **New flow** → add a test in `tests/smoke/test_smoke.py` (plus any fixtures in `tests/smoke/conftest.py` and recording mocks under `tests/smoke/mocks/` it needs) that drives it through the orchestrator's public interface and asserts on what reached the mocked boundary.
    - **Extended flow** → strengthen the existing assertions so they cover the new behaviour, instead of leaving it untested.
    - **New external boundary** → add or extend a recording mock under `tests/smoke/mocks/` and wire it into `docker-compose.smoke.yml`.
* The suite also A/B-compares each run's outputs against a committed baseline under `tests/smoke/baselines/` (`tests/smoke/test_ab_compare.py`), on structural metrics and on judged quality, and **fails on a regression**. When a change is meant to alter what the agents produce (a new prompt, a different model, changed output fields), refresh the baseline in the same change - `SMOKE_WRITE_BASELINE=1 SMOKE_BASELINE_NAME=<name> uv run pytest tests/smoke -m smoke` - rather than loosening the checks. See the *A/B comparison against a baseline* part of `README.md`.
* A change that genuinely adds no observable end-to-end behaviour (e.g. an internal refactor) needs no smoke change — but say so explicitly rather than skipping it silently.
* The suite is excluded from a bare `uv run pytest` (see `addopts` in `pytest.ini`). Run it explicitly with the stack up:
  ```bash
  docker build -t agentic-qa-base:latest -f Dockerfile.base .
  GOOGLE_API_KEY=<your-key> docker compose -f docker-compose.smoke.yml up -d --build --wait
  uv run pytest tests/smoke -m smoke -v
  docker compose -f docker-compose.smoke.yml down -v
  ```
  See the *Hermetic smoke tests* section of `README.md` for the full layout.

### Definition of done

A change is done when the unit tests pass, the affected versions are bumped, the smoke suite and the CALM model cover the change, README.md describes the changed behaviour, and everything temporary is cleaned up. Skip what doesn't apply; if you skip something that might look applicable, say why.

Finish every implementation task with a report in three short parts: **Blocked on me** (decisions or approvals you need from the user, or "nothing"), **Changed** (what and where), **Found** (known limits of a deliberately simple solution, unrelated dead code, anything you couldn't confirm).

## General style requirements

* Use **snake_case** for configuration keys in files like `.toml`, `.ini`, or `.yaml` (e.g., `api_key` instead of `apiKey` or `api-key`).
* For environment variables, use **SCREAMING_SNAKE_CASE** (e.g., `DATABASE_URL`).
