# Python Development Guidelines

The Python rules for QuAIA. They apply to every `.py` file in the repository, tests and scripts included, and are what
the skills in `.agents/skills/` write and review code against.

- General working rules (confirming a plan, minimal changes, no reformatting of untouched code, commits) are in
  [AGENTS.md](AGENTS.md). QuAIA-specific conventions (agents, orchestrator endpoints, a2a types, test fixtures) are in
  the skills.
- The rules apply to new and changed code. Do not rewrite untouched code only to make it comply.
- ruff (`ruff.toml`) and bandit enforce part of these rules; the rest is checked in review. Cite a rule by its section,
  e.g. "`PYTHON_GUIDELINES.md` § 9 Concurrency and async".

## Contents

1. Principles
2. Language version
3. Style and naming
4. Type hints
5. Data modelling
6. Functions and classes
7. Errors and exceptions
8. Logging
9. Concurrency and async
10. Standard library and I/O
11. Security
12. Performance
13. Testing
14. Docstrings and comments
15. Dependencies and environment
16. Tooling and suppressions
17. Sources

## 1. Principles

- Follow the Zen of Python (`import this`): explicit over implicit, simple over complex, flat over nested, one obvious
  way to do it.
- Prioritise clarity over cleverness. No dense one-liners, nested comprehensions or chained conditional expressions that
  need a second read; extract a well-named helper function instead.
- Keep nesting shallow: return early from guard clauses instead of wrapping the main path in `if`/`else`.
- Make invalid states hard to represent: precise types (enums, `Literal`, dataclasses, models) over loose strings, dicts
  and flags.
- Ask forgiveness, not permission (EAFP) for operations that can race or fail (file access, lookups on shared state);
  check first (LBYL) only when the check is cheap and the negative case is part of the normal flow.

## 2. Language version

- Write for the version in `requires-python` of `pyproject.toml` (3.14) and use its idioms. No compatibility shims for
  older versions, and no features of newer ones (e.g. 3.15's `lazy import`, `frozendict`, `sentinel`) until
  `requires-python` is raised.
- Annotations are evaluated lazily (PEP 649/749): do not add `from __future__ import annotations` and do not quote
  forward references.
- Never `return`, `break` or `continue` out of a `finally` block (PEP 765): it silently discards the in-flight
  exception.
- Use `match` to destructure structured data or dispatch on its shape or type; use `if`/`elif` for simple value
  comparisons.
- Use the walrus operator (`:=`) only where it removes a repeated computation without hurting readability.
- Use template strings (`t"..."`, PEP 750) only together with a function that escapes or processes the interpolated
  values (HTML, SQL, shell); a t-string escapes nothing by itself.

## 3. Style and naming

- PEP 8. `ruff format` is the formatter and `ruff check` the linter (`ruff.toml`, line length 120); do not hand-format
  against them.
- `snake_case` for modules, functions, methods and variables; `PascalCase` for classes, type aliases and type
  parameters; `SCREAMING_SNAKE_CASE` for module-level constants; exception classes end in `Error`.
- A single leading underscore marks everything that is not part of a module's or class's public API. Use double
  underscores (name mangling) only to avoid clashes in subclasses.
- Names state intent: no abbreviations or single letters except loop indices, `exc` in handlers and established math
  names. Booleans read as predicates (`is_ready`, `has_attachments`).
- No magic numbers or strings in logic: use a named constant or an enum.
- Imports are absolute, at the top of the module, grouped standard library / third party / first party (ruff sorts
  them). No wildcard imports. Names needed only for annotations go under `if TYPE_CHECKING:`. Defer a heavy import into
  a function only when startup time requires it, with a comment saying so.
- Compare to `None` with `is` / `is not`. Rely on truthiness for empty containers (`if not items:`), but not where `0`
  or `""` are valid values. Never compare to `True` or `False` with `==`.
- Break long lines with parentheses, never backslashes.
- Format strings with f-strings (log calls are the exception, see § 8). Build strings in loops with `"".join(...)` or
  `io.StringIO`, not `+=`.
- Avoid mutable module-level state; when unavoidable, keep it private and access it through functions.

## 4. Type hints

- Annotate every function and method signature: all parameters and the return type, `-> None` included. Annotate local
  variables only where inference fails, such as an empty container.
- Use built-in generics and `collections.abc`: `list[str]`, `dict[str, int]`, `Iterable[str]`, `Callable[[int], str]`.
  Never `typing.List`, `Dict`, `Optional` or `Union`.
- Write optional values as `X | None`, with `None` last.
- Accept the most general type that works (`Iterable`, `Sequence`, `Mapping`) and return concrete types (`list`,
  `dict`). Pydantic fields are the exception (§ 5).
- Use `object` for a value used in no type-specific way and `Any` only when the type cannot be expressed. Never use
  `Any` to silence a checker.
- Declare generics with PEP 695 syntax: `def first[T](items: Sequence[T]) -> T:`, `class Page[T]:`,
  `type JsonObject = dict[str, Any]`. No module-level `TypeVar`.
- Use `Protocol` for structural interfaces such as injected dependencies, and `ABC` only when subclasses share an
  implementation.
- Use `Literal[...]` or `enum.StrEnum` for closed sets of values, and `TypedDict` (with `NotRequired`, `ReadOnly`) for
  dict-shaped data that is not validated into a model.
- Use `typing.Self` for methods returning their own class, `@typing.override` on overriding methods and `TypeIs` for
  narrowing predicates.
- `cast()` and `# type: ignore[<code>]` need a comment explaining why the checker is wrong.

## 5. Data modelling

- Plain data containers are `@dataclass(slots=True)`; add `frozen=True` for value objects and `kw_only=True` when there
  are more than a few fields. Mutable defaults use `field(default_factory=...)`.
- Use Pydantic models at trust boundaries, where data must be parsed and validated: HTTP request and response bodies,
  webhook payloads, LLM and agent outputs, external API responses. Data already known to be valid uses dataclasses.
- Validate once, at the boundary. Downstream code receives typed objects, not raw `dict`s.
- Use the Pydantic v2 API: `model_validate_json(raw)` instead of `model_validate(json.loads(raw))`, `model_dump()` and
  `model_dump_json()`, `model_config = ConfigDict(...)`, `Field(...)` constraints and `field_validator` /
  `model_validator` instead of ad-hoc checks.
- Create a `TypeAdapter` once at module level, not per call.
- Model polymorphic payloads as discriminated unions: `Field(discriminator="kind")` on a `Literal` field.
- Pydantic fields use concrete types (`list`, `dict`): abstract ones (`Sequence`, `Mapping`) validate more slowly.
- Replace dicts nested more than one level deep, and tuples whose positions carry meaning, with a dataclass or a model.

## 6. Functions and classes

- A function does one thing. Split it when it grows beyond about 40 lines or needs comments to separate its steps.
- Make boolean flags and optional settings keyword-only (`*`). More than about five parameters is a sign that related
  ones belong in a dataclass.
- Never use a mutable default argument; default to `None` and create the object in the body.
- Do not mutate objects passed in by the caller unless that is the function's documented purpose.
- Signal failure by raising, not by returning `None`, a sentinel or an error code. Return `None` only when "no result"
  is a normal outcome, typed as `X | None`.
- Return a dataclass instead of a tuple of more than two values.
- Prefer comprehensions and generator expressions to `map`/`filter` with `lambda` and to append loops. At most two
  `for`/`if` clauses, and no side effects inside a comprehension.
- Use generators or generator expressions for large or streamed sequences instead of building lists, and pass them
  straight to `any()`, `all()`, `sum()`, `min()` or `max()`.
- Use `enumerate()` instead of `range(len(...))`, `zip(..., strict=True)` when the lengths must match, and
  `dict.get()` or `collections.defaultdict` instead of manual key checks.
- Favour composition over inheritance. Inherit only for a true "is-a" relationship and keep hierarchies shallow.
- Expose plain public attributes instead of trivial getters and setters; use `@property` for cheap computed or validated
  attributes.
- Write a module-level function instead of a `@staticmethod`; use `@classmethod` for alternative constructors.
- Every decorator uses `functools.wraps`. Bind arguments with `functools.partial` rather than a `lambda`.
- Do not put `functools.cache` or `lru_cache` on instance methods: the cache keeps every instance alive.
- No metaclasses, monkey-patching or dynamic attribute magic in application code; `__init_subclass__` or a class
  decorator covers most needs. Never `eval` or `exec`.
- A class that owns a resource (client, session, file, executor) implements the context-manager protocol
  (`__enter__`/`__exit__` or `__aenter__`/`__aexit__`) or an explicit `close()` / `aclose()`.

## 7. Errors and exceptions

- Catch the most specific exception possible. Never a bare `except:`, and never `except BaseException` without
  re-raising: it also catches `KeyboardInterrupt`, `SystemExit` and `asyncio.CancelledError`.
- Catch `Exception` only at a boundary (request handler, task or worker loop, entry point), where the error is logged
  with its traceback and turned into a response, a recorded error or a clean exit.
- Never swallow an exception silently. If continuing is correct, log the exception and make clear why continuing is
  safe. Use `contextlib.suppress(SpecificError)` only for errors that are expected and harmless.
- Keep `try` blocks to the statements that can raise the handled exception. Put success-only code in `else` and cleanup
  in `finally` or a `with` block.
- Re-raise with a bare `raise`. When translating an exception, chain it: `raise SyncError("...") from exc`; use
  `from None` only when the original adds nothing.
- Add context to an exception passing through with `exc.add_note(...)` instead of wrapping it.
- Give each package a root exception (e.g. `class RagSyncError(Exception)`) with specific subclasses, so callers can
  catch the package's errors in one place. Never raise bare `Exception`.
- Use built-in exceptions for their standard meaning: `ValueError`, `TypeError`, `KeyError`, `LookupError`,
  `TimeoutError`, `NotImplementedError`.
- Error messages say what failed and include the offending value (`f"Unsupported media type: {media_type!r}"`), never a
  secret.
- Handle the `ExceptionGroup` raised by an `asyncio.TaskGroup` with `except*`.
- Use `assert` only for internal invariants and in tests, never to validate input: `python -O` strips assertions.
- Log an exception once, where it is handled, not at every layer it passes through.

## 8. Logging

- Create one module-level logger with the project helper: `logger = utils.get_logger(...)` from `common.utils`.
- No `print()` in application code. Command-line output of scripts is the only exception.
- Pass values as arguments, not pre-formatted strings: `logger.info("Synced %d pages of space %s", count, space_key)`,
  not f-strings, `%` or `.format()` in the message. Formatting is then skipped for disabled levels, and log aggregation
  can group records by the constant message. Existing f-string calls are converted only when their line changes anyway.
- Inside `except`, use `logger.exception(...)` (level `ERROR` with traceback), or `exc_info=True` on another level.
- Levels: `DEBUG` for diagnostics, `INFO` for significant events, `WARNING` for recoverable anomalies, `ERROR` for a
  failed operation, `CRITICAL` when the service cannot continue.
- Include the identifiers that make a record traceable (task ID, issue key, page ID). Never log secrets, tokens,
  credentials or whole payloads that may carry personal data.
- Guard expensive argument computation with `if logger.isEnabledFor(logging.DEBUG):`.
- Configure handlers only at application entry points, never as a side effect of importing a module.

## 9. Concurrency and async

Pick the model by workload:

| Workload                                              | Use                                                |
|-------------------------------------------------------|----------------------------------------------------|
| Many concurrent I/O operations                        | `asyncio`                                          |
| A blocking call from async code                       | `await asyncio.to_thread(func, *args)`             |
| I/O-bound work with synchronous or blocking libraries | `concurrent.futures.ThreadPoolExecutor`            |
| CPU-bound work                                        | `ProcessPoolExecutor` or `InterpreterPoolExecutor` |

### asyncio

- Never block the event loop. No `time.sleep()`, synchronous HTTP (`requests`), blocking file, database or SDK calls,
  or CPU-heavy work inside `async def`: use `asyncio.sleep()`, async clients (`httpx.AsyncClient`) or
  `asyncio.to_thread()`. In FastAPI, `async def` endpoints must not block; plain `def` endpoints run in a thread pool.
- Await or schedule every coroutine; a coroutine called without `await` never runs.
- Run related tasks that must all succeed in `async with asyncio.TaskGroup() as tg:`. One failure cancels the siblings
  and surfaces as an `ExceptionGroup`.
- When one task's failure must not cancel the others, use `asyncio.gather(..., return_exceptions=True)` and log every
  exception in the results, or catch the error inside each task and return a result value.
- Keep a reference to every task created with `asyncio.create_task()`, because the event loop holds only a weak one, and
  retrieve its result or exception. Prefer a `TaskGroup`, which owns its tasks. A deliberate background task needs a
  stored reference and a done-callback that logs its failure.
- Bound every external wait: `async with asyncio.timeout(seconds):` around the operation's overall budget, in addition
  to client-level timeouts.
- Never swallow `asyncio.CancelledError`. If you catch it for cleanup, re-raise it; `TaskGroup` and `asyncio.timeout()`
  rely on cancellation propagating.
- Protect state that is read and written across an `await` with `asyncio.Lock`. Bound fan-out with
  `asyncio.Semaphore`, and use `asyncio.Queue` for producer-consumer pipelines.
- Inside coroutines use `asyncio.get_running_loop()`, never `asyncio.get_event_loop()`. Start the loop only at entry
  points with `asyncio.run()`, or let the framework do it.
- Create async clients once per service lifetime and close them with `async with` or `aclose()`.
- Debug hangs and "never retrieved" exceptions with `PYTHONASYNCIODEBUG=1`; inspect the tasks of a live process with
  `python -m asyncio pstree <pid>`.

### Threads and processes

- Protect shared mutable state with `threading.Lock` or pass data through `queue.Queue`. Do not rely on the atomicity of
  built-in operations: the free-threaded build (PEP 779) has no GIL, and check-then-act sequences are never atomic.
- Use executors scoped with `with`, not hand-managed `Thread` objects.
- From another thread, hand work to an event loop only with `asyncio.run_coroutine_threadsafe()` or
  `loop.call_soon_threadsafe()`.
- Process pool arguments and results must be picklable. Since 3.14 Linux starts workers with `forkserver`, so workers do
  not inherit the parent's module state.

## 10. Standard library and I/O

- Manage every resource with `with` or `async with`: files, locks, clients, executors, temporary directories. Use
  `contextlib.ExitStack` for a dynamic number of them.
- Use `pathlib.Path` for paths and file operations (`/`, `read_text()`, `iterdir()`, `mkdir(parents=True,
  exist_ok=True)`) instead of `os.path` string handling.
- Pass `encoding="utf-8"` whenever text is read or written (`open()`, `read_text()`, `write_text()`): the default
  encoding depends on the platform.
- Datetimes are timezone-aware: `datetime.now(UTC)` (`from datetime import UTC`) and
  `datetime.fromtimestamp(ts, tz=UTC)`, never naive `datetime.now()` or `datetime.utcnow()`. Store and compare in UTC and
  convert with `zoneinfo.ZoneInfo` only for display. Measure durations with `time.monotonic()`.
- Run commands with `subprocess.run([...], check=True, timeout=..., capture_output=True, text=True)`, passing an
  argument list. Never `shell=True`, `os.system()` or `os.popen()`.
- Read TOML with `tomllib`. Use `decimal.Decimal` where exact decimal arithmetic matters.
- Use `secrets` for tokens and anything that must be unguessable, never `random`. Use `uuid.uuid4()` for random IDs and
  `uuid.uuid7()` for time-ordered ones.
- Reach for `collections` (`defaultdict`, `Counter`, `deque`), `itertools`, `functools`, `heapq` and `bisect` before
  writing an equivalent by hand.
- Create temporary files with `tempfile.TemporaryDirectory()` or `NamedTemporaryFile()`, never with hand-built paths or
  `mktemp()`.

## 11. Security

The general rules (never trust external input, secrets only from environment variables or a secrets manager) are in
[AGENTS.md](AGENTS.md). In Python code:

- Validate external input at the boundary with Pydantic models (types, lengths, patterns, enums) before it reaches
  business logic, file paths, queries, commands or prompts.
- Treat LLM output as untrusted input: validate it into a model before acting on it, and never execute it.
- Never `eval`, `exec` or `compile` data. Never unpickle (`pickle`, `shelve`, `marshal`) data from outside the process.
  Use `yaml.safe_load`, never `yaml.load`. Parse untrusted XML with `defusedxml`.
- Build commands as argument lists (§ 10); never interpolate input into a shell string.
- Bind parameters in queries. Where a query language has no binding (e.g. JQL), validate interpolated values against a
  strict pattern or allow-list first.
- Confine file paths built from input: resolve them and check `resolved.is_relative_to(base_dir.resolve())`.
- Extract archives only after inspection: `tarfile` with `filter="data"`, and zip members checked for absolute paths,
  `..` components and total size.
- Allow-list the scheme and host of any outbound request whose URL comes from input (SSRF).
- Give every network call a timeout. `httpx` defaults to 5 seconds; `requests` has no default, so always pass `timeout=`.
- Never disable TLS certificate verification (`verify=False`).
- Compare secrets, signatures and tokens with `hmac.compare_digest()`.
- Keep secrets out of logs, exception messages, `repr`s and prompts; type secret model fields as `pydantic.SecretStr`.
- Use SHA-256 or stronger for integrity checks. MD5 or SHA-1 used only as a non-security fingerprint must say so with
  `usedforsecurity=False`.

## 12. Performance

- Measure before optimising: `cProfile` or `py-spy` for CPU, `tracemalloc` for memory, `timeit` for micro-benchmarks.
  Keep the readable version unless the measured gain matters.
- Choose the right data structure first: `set` and `dict` for membership and lookup, `deque` for queues, generators for
  streams.
- Keep loops free of repeated work: hoist invariants, batch I/O and remote calls, compile repeatedly used regular
  expressions once at module level.
- Reuse expensive objects (HTTP and database clients, loaded models, `TypeAdapter`s) instead of creating them per call.
- Cache pure, expensive functions with `functools.cache`, or with a bounded `functools.lru_cache(maxsize=...)` when the
  inputs are unbounded.
- Stream large files and HTTP bodies instead of loading them into memory at once.
- For I/O, the lever is async concurrency (§ 9); move CPU-heavy work off the event loop into a process or interpreter
  pool.

## 13. Testing

The project's test layout, fixtures and mocking pitfalls are in the `writing-unit-tests` skill.

- Use pytest with plain `assert`. One behaviour per test, named after the behaviour and condition it checks, structured
  as arrange, act, assert.
- Cover the success path, every failure path the code handles explicitly and the edge cases it branches on (`None`,
  empty collections, boundary values).
- Use `@pytest.mark.parametrize` for the same assertion over several inputs, with `ids` when the inputs are not
  self-explanatory.
- Put shared setup in fixtures with the narrowest scope that works, in the nearest `conftest.py`. Use `yield` fixtures
  for teardown.
- Mock only boundaries (network, LLM, external services, clock, randomness) and exercise the real logic.
- Patch a name where it is looked up, not where it is defined.
- Use `autospec=True` or `create_autospec()` so a mock fails on a wrong call signature, and `AsyncMock` for coroutines.
  Assert the calls that matter (`assert_awaited_once_with(...)`).
- Use `monkeypatch` for environment variables and attributes, `tmp_path` for files and `caplog` for log assertions.
- Tests are deterministic and independent of each other and of execution order: no real network, no shared mutable
  state, no `sleep()` for synchronisation (use `asyncio.Event`, fakes or an injected clock).
- Assert observable behaviour and outputs, not private implementation details.
- Assert exceptions with `pytest.raises(SpecificError, match=...)`.
- For a bug fix, first write a test that reproduces the bug, then fix it.
- Never skip, `xfail`, delete or weaken an assertion to get a green run.
- Coverage shows what is untested; it is not a goal in itself.

## 14. Docstrings and comments

- Every public module, class, function and method has a PEP 257 docstring in triple double quotes, starting with a
  one-line summary in the imperative mood that ends with a period.
- Add Google-style `Args:`, `Returns:`, `Yields:` and `Raises:` sections when parameters, results or raised exceptions
  are not obvious from the names and type hints. Do not repeat the types.
- Comments explain *why* (a constraint, a workaround, a non-obvious decision), never *what* the code does, and are rare:
  the code must explain itself.
- No commented-out code. A `TODO` names an issue or its reason.
- Update docstrings and comments in the same change as the code they describe.

## 15. Dependencies and environment

- uv manages the project-local virtual environment. Create and update it with `uv sync`, run everything with
  `uv run <command>`, and never `pip install` into it or use a global interpreter.
- `pyproject.toml` is the single source of truth for dependencies:
    - `[project.dependencies]`: runtime dependencies shared by all services.
    - `[project.optional-dependencies]`: service-specific runtime dependencies (e.g. `rag-sync`,
      `embedding-service`).
    - `[dependency-groups]`: development and CI tooling.
- Pin runtime dependencies to exact versions (`==`), as the existing entries do. After changing `pyproject.toml`, run
  `uv lock`; never edit `uv.lock` by hand, and commit it.
- Import only packages declared directly in `pyproject.toml`, never a transitive dependency.
- Before adding a package, prefer the standard library or an existing dependency. A new package must be actively
  maintained, license-compatible with AGPL-3.0-only and clean under `uv audit`.

## 16. Tooling and suppressions

- A change is done only when ruff, pytest, bandit and `uv audit` pass. The commands are in the
  `preparing-pull-requests` skill.
- Suppressions are targeted and justified: `# noqa: <RULE>`, `# type: ignore[<code>]` or `# nosec <ID>`, each followed
  by the reason. Never a blanket `# noqa`.

## 17. Sources

- Python Enhancement Proposals: [PEP 8](https://peps.python.org/pep-0008/), [PEP 20](https://peps.python.org/pep-0020/),
  [PEP 257](https://peps.python.org/pep-0257/), [PEP 649](https://peps.python.org/pep-0649/) /
  [PEP 749](https://peps.python.org/pep-0749/), [PEP 654](https://peps.python.org/pep-0654/),
  [PEP 678](https://peps.python.org/pep-0678/), [PEP 695](https://peps.python.org/pep-0695/),
  [PEP 706](https://peps.python.org/pep-0706/), [PEP 750](https://peps.python.org/pep-0750/),
  [PEP 765](https://peps.python.org/pep-0765/), [PEP 779](https://peps.python.org/pep-0779/)
- Python documentation: [What's new in Python 3.14](https://docs.python.org/3/whatsnew/3.14.html),
  [Coroutines and tasks](https://docs.python.org/3/library/asyncio-task.html),
  [Developing with asyncio](https://docs.python.org/3/library/asyncio-dev.html),
  [Free threading](https://docs.python.org/3/howto/free-threading-python.html),
  [What's new in Python 3.15](https://docs.python.org/3.15/whatsnew/3.15.html)
- [Typing best practices](https://typing.python.org/en/latest/reference/best_practices.html), Python Typing Team
- [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)
- Brett Slatkin, [*Effective Python*, 3rd edition](https://effectivepython.com/) (2024)
- Luciano Ramalho, *Fluent Python*, 2nd edition (2022)
- Patrick Viafore, *Robust Python* (2021)
- Harry Percival and Bob Gregory, *Architecture Patterns with Python* (2020)
- [Pydantic performance tips](https://pydantic.dev/docs/validation/latest/concepts/performance/)
- [FastAPI best practices](https://github.com/zhanymkanov/fastapi-best-practices)
- Stuart Ellis, [Modern Good Practices for Python Development](https://www.stuartellis.name/articles/python-modern-practices/)
  (2026)
- [OWASP Secure Coding Practices](https://owasp.org/www-project-secure-coding-practices-quick-reference-guide/)
- [Ruff rules](https://docs.astral.sh/ruff/rules/)
