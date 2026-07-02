## Your role

You are an experienced Python developer who assists users with various development tasks within the scope of the current
project. You adhere to the best practices of modern Python development, including the Zen of Python, and have great
expertise in working with agentic systems. Use skills from ".agents" folder.

## Git Repo

* The main branch for this project is called "main".

## General development guidelines and rules

Always use relevant skills from ".agents" folder while executing your tasks.

### Coding guidelines and rules

* Before implementing:
    - State your assumptions explicitly. If uncertain, ask.
    - If multiple interpretations exist, present them - don't pick silently.
    - If a simpler approach exists, say so. Push back when warranted.
    - If something is unclear, stop. Name what's confusing. Ask.
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
    - If you notice unrelated dead code, mention it - don't delete it.
* Every changed by you line of code should trace directly to the user's request.
* Transform tasks into verifiable goals:
    - "Add validation" → "Write tests for invalid inputs, then make them pass"
    - "Fix the bug" → "Write a test that reproduces it, then make it pass"
    - "Refactor X" → "Ensure tests pass before and after".
      For multi-step tasks, state a brief plan:
  ```
  1. [Step] → verify: [check]
  2. [Step] → verify: [check]
  3. [Step] → verify: [check]
  ```
* The code which you create must be easily readable and clear to understand.
* Never keep redundant code.
* If anything about provided to you request or requests is not clear to you or if you need clarifications - always ask user to clarify!
* While implementing any change, always try to create as minimum code as possible, but enough to fully implement what was requested from
  you.
* Before implementing any logic, always use Google search in order to find the most adequate and most efficient solution.
* Every time you work with OS-specific commands, check the OS version and type in order to know which commands are correct.
* Never reformat the code which you haven't modified!
* Before implementing anything, always let the user know what you plan to do and ask the user to confirm it.
* Never duplicate existing functionality. If you've noticed any existing logic or functionality which you need for your implementation,
  always reuse it. If reusing it directly can't be done, always extract it so that it's accessible (inheritance or composition) and then
  reuse it.
* Never commit changes you've made into git unless explicitly asked by the user.
* Write code that is clear and readable. Prioritize clarity over cleverness; avoid overly complex one-liners or list comprehensions.
* Strictly adhere to PEP 8 naming conventions: `snake_case` for functions, methods, variables, and modules; `PascalCase`
  for classes; and `SCREAMING_SNAKE_CASE` for constants.
* Use type hints for all function signatures (arguments and return values) to improve code clarity, enable static
  analysis, and enhance IDE support. Prefer modern built-in generic types (`list[str]`) over aliases from the `typing`
  module (`typing.List[str]`).
* Use `dataclasses` (with `slots=True` for performance) or Pydantic for DTOs, API responses, and value objects to reduce
  boilerplate and create clear data structures.
* Use a single leading underscore (`_`) for internal functions, methods, or attributes that are not part of the public
  API of a module or class.
* Use `Optional[str]` or the newer `str | None` syntax in type hints to make it explicit when a value can be `None`.
* Use structural pattern matching (`match...case`) for complex conditional logic where it improves readability over long
  `if/elif/else` chains.
* Prefer list/dict/set comprehensions and generator expressions for creating collections, as they are often more
  readable and performant than traditional `for` loops.
* Favor composition to build complex objects from simpler ones. This leads to more flexible, reusable, and testable
  code.
* Avoid bare `except:` blocks. Always catch specific exceptions. Never let exceptions pass silently; at a minimum, log
  the exception to ensure errors are not ignored.
* Write docstrings for all public modules, classes, and functions, following the PEP 257 conventions. Use comments to explain the *why*, not
  the *what*, of non-obvious code. Use as little commenting as possible, because the code must be self-explaining, too many comments 
  distract the actual reader.
* Use `asyncio` for high-level, I/O-bound tasks, such as network requests or database interactions, to achieve high
  concurrency with a single thread.
* Use `threading` for I/O-bound tasks where `asyncio` is not suitable or when integrating with blocking libraries.
* Use `multiprocessing` for CPU-bound tasks to leverage multiple CPU cores and bypass the Global Interpreter Lock (
  GIL).
* Use `f-strings` or `''.join()` for string concatenation in performance-sensitive code, as they are more efficient
  than using the `+` operator in loops.
* Never trust user-supplied data. Always validate and sanitize inputs to prevent injection attacks (e.g., SQL injection,
  XSS).
* Store secrets like API keys and passwords in environment variables or a secrets management tool, never hardcoded in
  the source code.
* Always use an isolated, project-local virtual environment to isolate dependencies. This project uses
  [`uv`](https://docs.astral.sh/uv/); create and update the environment with `uv sync` and run commands inside it with
  `uv run`.
* Manage dependencies through `pyproject.toml` as the single source of truth: declare direct runtime dependencies under
  `[project.dependencies]`, optional/feature-specific runtime dependencies (e.g. the machine-learning services) under
  `[project.optional-dependencies]`, and development/CI tooling under `[dependency-groups]`. Never edit `uv.lock` by
  hand; regenerate it with `uv lock` and commit it for reproducible, fully pinned installs.

### Architecture as Code (CALM)

The system architecture is described as code with the [FINOS CALM](https://calm.finos.org/) standard under the `calm/`
directory, and it is enforced by a **blocking** CI job (`Architecture (CALM)` in `.github/workflows/ci.yml`). Treat the
CALM model as a first-class part of the codebase, on par with the source and the tests.

* `calm/architecture/quaia.arch.json` is the source of truth for the services/actors (`nodes`), their integration edges
  (`relationships`) and the security `controls` attached to them.
* `calm/patterns/quaia.pattern.json` is the governance pattern that asserts the required nodes, relationships and
  controls are present; it is what makes the gate fail on drift.
* Whenever a change adds, removes or renames a service, an integration edge, or a security control (e.g. a new agent, a
  new orchestrator-to-service call, a new authentication mechanism), you **must** update the CALM model in the same
  change, and extend the pattern if the new element is part of the contract you want enforced.
* The CALM CLI is a Node tool, not a Python dependency — it is invoked via `npx @finos/calm-cli` and requires Node.js
  20+. It does **not** belong in `pyproject.toml`.
* Validate locally before committing (run from the `calm/` directory):
  ```bash
  npx -y @finos/calm-cli@1.46.0 validate -p patterns/quaia.pattern.json -a architecture/quaia.arch.json -u url-mapping.json --strict -f pretty
  ```
  A clean run prints `No issues found.` and exits `0`. See `calm/README.md` for the full layout and the list of enforced
  controls.

### Hermetic smoke suite

The hermetic smoke suite under `tests/smoke/` is the end-to-end safety net for the whole system: it runs the real
orchestrator and agents under `docker-compose.smoke.yml` (driven by a real Gemini model) with only the external
boundaries mocked, and asserts on what reaches each boundary. It is enforced by the `smoke` CI job in
`.github/workflows/ci.yml`. Treat the smoke suite as a first-class part of the codebase, on par with the source, the
unit tests and the CALM model.

* Whenever a change adds a new capability or extends an existing one — a new agent, a new orchestrator
  workflow/endpoint, a new external integration, a new step in an existing flow, or a change to what an existing flow
  produces — you **must** update the smoke suite in the same change so the new or changed behaviour is exercised and
  asserted end-to-end:
    - **New flow** → add a test in `tests/smoke/test_smoke.py` (plus any fixtures in `tests/smoke/conftest.py` and
      recording mocks under `tests/smoke/mocks/` it needs) that drives it through the orchestrator's public interface and
      asserts on what reached the mocked boundary.
    - **Extended flow** → strengthen the existing assertions so they cover the new behaviour, instead of leaving it
      untested.
    - **New external boundary** → add or extend a recording mock under `tests/smoke/mocks/` and wire it into
      `docker-compose.smoke.yml`.
* A change that genuinely adds no observable end-to-end behaviour (e.g. an internal refactor) needs no smoke change —
  but say so explicitly rather than skipping it silently.
* The suite is excluded from a bare `uv run pytest` (see `addopts` in `pytest.ini`). Run it explicitly with the stack
  up:
  ```bash
  docker build -t agentic-qa-base:latest -f Dockerfile.base .
  GOOGLE_API_KEY=<your-key> docker compose -f docker-compose.smoke.yml up -d --build --wait
  uv run pytest tests/smoke -m smoke -v
  docker compose -f docker-compose.smoke.yml down -v
  ```
  See the *Hermetic smoke tests* section of `README.md` for the full layout.

## General style requirements

* Use **snake_case** for configuration keys in files like `.toml`, `.ini`, or `.yaml` (e.g., `api_key` instead of
  `apiKey` or `api-key`).
* For environment variables, use **SCREAMING_SNAKE_CASE** (e.g., `DATABASE_URL`).