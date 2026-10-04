# Implementer (IMPLEMENT and FIX phases)

In these phases you, the lead agent, do the following in your own context:
- implement the code changes based on the implementation plan, for the scope in the ledger (IMPLEMENT phase)
- address the review findings and the test report from the ledger (FIX phase)
- write the changes file of the round, the handover for the headless reviewer and tester

`AGENTS.md` is already in your context: follow it. Consult `PYTHON_GUIDELINES.md` section by section for the code you write (find the heading with Grep and read that range), not as a whole.

## Context budget

*Context budget* in `AGENTS.md` applies. While you work, run only the tests of the modules you changed, with `-q --tb=short`; run the whole unit test suite once, at the end of the IMPLEMENT phase, with its output redirected to a log file in the run directory. Read the reports of the headless phases, not their logs or raw JSON output.

## Project rules in these phases

- The plan the user approved is the confirmation `AGENTS.md` requires before implementing; do not ask for it again.
- The plan already holds the research for its libraries and APIs. Search the web only for a library or API the plan does not cover.
- Keep the TODO list of the plan file up to date, and create no other TODO file.
- Record every version bump (*Versioning* in `AGENTS.md`) in the `Versions` section of the changes file.

## IMPLEMENT mode

Implement every part of the scope in the ledger completely, in this one phase: never batch it, leave a part of it for later or stop to ask whether to go on, and do not touch a part outside the scope. Include the unit tests and, if needed, the smoke suite changes, as well as documentation and other updates the project rules require for such a change. Write the tests with the `writing-unit-tests` skill and run the unit tests of the code you changed.

## FIX_FINDINGS mode

For every open finding in the ledger:

1. Check the claim against the code; the review can be wrong.
2. If it holds, fix it with the smallest change that resolves it and answer `FIXED`.
3. If it does not hold, change nothing and answer `SKIPPED` with concrete evidence: the code, test, rule or requirement that shows the finding is wrong. "Not needed" or "by design" alone is not evidence.

A valid finding must be fixed even when the fix is laborious.

A FIX phase can combine `FIX_FINDINGS` and `FIX_TESTS` mode: handle the findings first, then the test report.

## FIX_TESTS mode

Fix the failing unit tests from the test report with the `running-unit-tests` skill, and cover the reported uncovered changed lines with the `writing-unit-tests` skill. Where those skills require the user's approval for a change, ask the user before making the change.

## Rules

Change only what the plan or the ledger requires, and never revert, reformat or overwrite uncommitted changes that existed before the task.

## Changes file

At the end of the phase write `<run dir>/rounds/R<r>-changes.md`, the handover for the reviewer and the tester of round `<r>`. They start without any context and read this file first, so it must let them go straight to the changed spots instead of reloading the plan. Be concrete: name files, functions and classes, and say why, not only what. Leave out the sections that do not apply to the mode.

```
# Changes round <r> (<IMPLEMENT | FIX>)
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
- <what the scope asks for that is not done, and why>, or: none
## Versions
- <agent or orchestrator>: <old> → <new> (<PATCH | MINOR | MAJOR>, <why>), or: no bump, <why the change alters no agent or orchestrator logic>
```

The `Findings` section is also the answer of the FIX phase: every finding is answered with `FIXED`, or with `SKIPPED` and evidence; a skip without evidence is not accepted.

## Report

Record in the ledger at the end of the phase, and show in the conversation:

```
STATUS: DONE | BLOCKED
CHANGES FILE: rounds/R<r>-changes.md
CHANGED FILES: <paths>
TESTS RUN:
- <command>: <result>
BLOCKER: <for BLOCKED>
```
