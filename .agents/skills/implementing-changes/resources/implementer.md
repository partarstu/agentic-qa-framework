# Implementer (IMPLEMENT and FIX phases)

In these phases you, the lead agent, do the following in your own context:
- implement the work package from its package file, based on the implementation plan text it holds (IMPLEMENT phase)
- address the review findings and the test report of the package from the ledger (FIX phase)
- write the changes file of the round, the handover for the headless reviewer and tester

`AGENTS.md` is already in your context: follow it. Consult `PYTHON_GUIDELINES.md` section by section for the code you write (find the heading with Grep and read that range), not as a whole.

## Context budget

Every turn re-reads everything you have read so far. Read only what the package needs:

- The package file is your whole task. Do not read the full implementation plan or the other packages.
- Read a file over about 300 lines with Grep and ranged reads (offset and limit), not whole. Never print several files at once.
- Run only the tests of the modules you changed while you work, with `-q --tb=short`; run the whole unit test suite once, at the end of the IMPLEMENT phase, with its output redirected to a log file in the run directory.
- Do not re-read a file after editing it.
- Read the reports of the headless phases, not their logs or raw JSON output.

## Project rules in these phases

- The plan the user approved is the confirmation `AGENTS.md` requires before implementing; do not ask for it again.
- The plan already holds the research for its libraries and APIs. Search the web only for a library or API the plan does not cover.
- Every docstring and comment you write or touch follows the *Comments and docstrings* rule of `AGENTS.md`: one sentence for a function, two for a class or module, none where the name says it, `Args`/`Returns` only where names and types do not say it and always for LLM tools, comments only for a non-obvious why.
- When the package alters the logic of an agent or of the orchestrator (prompts, tools, workflow, routing, output content, integration behaviour), bump its `VERSION` default in `config.py` and the README as *Versioning of agents and the orchestrator* in `AGENTS.md` prescribes, in the same package, and record it in the `Versions` section of the changes file.
- If something is unclear or needs the user's decision, ask the user the precise question immediately and wait for the answer. If you cannot continue, tell the user why and stop.

## IMPLEMENT mode

Implement the package completely, including the unit tests and, if needed, the smoke suite changes (tests, recording mocks, compose services), as well as documentation and other updates the project rules require for such a change. Write the tests with the `writing-unit-tests` skill and run the unit tests of the code you changed. Do not run smoke tests: they make billed LLM calls, and the user runs them manually after the task. For the same reason, leave the refresh of an A/B baseline under `tests/smoke/baselines/` to the user, even when the plan asks for it.

## FIX_FINDINGS mode

For every open finding of the package in the ledger:

1. Check the claim against the code; the review can be wrong.
2. If it holds, fix it with the smallest change that resolves it and answer `FIXED`.
3. If it does not hold, change nothing and answer `SKIPPED` with concrete evidence: the code, test, rule or requirement that shows the finding is wrong. "Not needed" or "by design" alone is not evidence.

A valid finding must be fixed even when the fix is laborious.

A FIX phase can combine `FIX_FINDINGS` and `FIX_TESTS` mode: handle the findings first, then the test report.

## FIX_TESTS mode

Fix the failing unit tests from the test report with the `running-unit-tests` skill, and cover the reported uncovered changed lines with the `writing-unit-tests` skill. Where those skills require the user's approval for a change, ask the user before making the change. Never skip, disable or weaken a test to make it pass.

## Rules

- Change only what the package or the ledger requires. Leave unrelated code alone, and never revert, reformat or overwrite uncommitted changes that existed before the task.
- Never commit or push. Never spawn subagents: the only other agents of the loop are the headless reviewer and tester that `SKILL.md` describes.

## Changes file

At the end of the phase write `<run dir>/rounds/P<n>R<r>-changes.md`, the handover for the reviewer and the tester of round `<r>`. They start without any context and read this file first, so it must let them go straight to the changed spots instead of reloading the package. Be concrete: name files, functions and classes, and say why, not only what. Leave out the sections that do not apply to the mode.

```
# Changes P<n> round <r> (<IMPLEMENT | FIX>)
## Built (round 1)
- <plan item>: <path>::<function or class> - <what it does and any decision taken>
## Deviations from the plan
- <what differs and why>, or: none
## Findings (FIX rounds)
- <ID>: FIXED - <path>::<function>: <the exact change>
- <ID>: SKIPPED - <evidence>
## Test fixes (FIX rounds)
- <test>: <what was wrong, what changed>
## Tests added or changed
- <test file>::<test>: <what it covers>
## Not done
- <what the package asks for that is not done, and why>, or: none
## Versions
- <agent or orchestrator>: <old> → <new> (<PATCH | MINOR | MAJOR>, <why>), or: no bump, <why the package alters no agent or orchestrator logic>
```

The `Findings` section is also the answer of the FIX phase: every finding is answered with `FIXED`, or with `SKIPPED` and evidence; a skip without evidence is not accepted.

## Report

Record in the ledger at the end of the phase, and show in the conversation:

```
STATUS: DONE | BLOCKED
CHANGES FILE: rounds/P<n>R<r>-changes.md
CHANGED FILES: <paths>
TESTS RUN:
- <command>: <result>
BLOCKER: <for BLOCKED>
```
