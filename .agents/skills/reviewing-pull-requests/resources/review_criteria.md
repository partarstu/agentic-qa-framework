# Review Criteria

## Severity levels

| Prefix       | Use for                                                                                                    |
|--------------|------------------------------------------------------------------------------------------------------------|
| `[CRITICAL]` | Security hole, data loss, broken behaviour, failing CI gate                                                |
| `[HIGH]`     | Bug risk or unhandled edge case, missing tests, missing CALM or smoke update                               |
| `[MEDIUM]`   | AGENTS.md or PYTHON_GUIDELINES.md violation, duplicated logic, code the change does not need               |
| `[LOW]`      | Naming, style or small clarity issues, optional improvement or alternative approach                        |

CRITICAL, HIGH and MEDIUM findings must be fixed before merge; LOW findings are optional. When the intent of the code is unclear, rate the finding by the risk it carries if the code is wrong.

## How to review

- Read the full new version of every changed file, not only the diff hunks.
- Also check what the change is missing: tests, the CALM update, smoke coverage, README or skill updates.
- Confirm every finding against the code and drop speculative ones. Report problems in unchanged code only when the change causes or worsens them.
- Cite the rule a finding breaks (e.g. "`PYTHON_GUIDELINES.md` § 4", "*Versioning* in `AGENTS.md`") instead of restating it.

## Correctness and design

Review these first; they matter more than style.

- Logic errors and unhandled edge cases: `None`, empty collections, timeouts, partial failures.
- Concurrency and exception-handling defects (`PYTHON_GUIDELINES.md` § 7 and § 9).
- Logic duplicated from `common/` or `orchestrator/` instead of reused.
- Abstractions, options or code beyond what the change needs.

## Rules

Check every changed line, tests included, against `PYTHON_GUIDELINES.md` and every rule of `AGENTS.md`. Severities of the project rules:

- Comment bloat (*Comments and docstrings*): `[MEDIUM]`.
- A missing version bump, or one at the wrong level (*Versioning*): `[MEDIUM]`.
- An architecture change without the CALM update (*Architecture first (CALM)*): `[HIGH]`.
- An added or extended end-to-end flow without smoke coverage (*Smoke suite*): `[HIGH]`. A pure internal refactor is exempt; confirm that it really is one.
