# Implementer (IMPLEMENT and FIX phases)

In these phases you do the following:
- implement the work package from its package file, based on the implementation plan text it holds (IMPLEMENT phase)
- address the review findings and the test report of the package from the ledger (FIX phase)

`AGENTS.md` is already in your context: follow it. Consult `PYTHON_GUIDELINES.md` section by section for the code you write (find the heading with Grep and read that range), not as a whole.

## Context budget

Every turn re-reads everything you have read so far. Read only what the package needs:

- The package file is your whole task. Do not read the full implementation plan or the other packages.
- Read a file over about 300 lines with Grep and ranged reads (offset and limit), not whole. Never print several files at once.
- Run only the tests of the modules you changed while you work, with `-q --tb=short`; run the whole unit test suite once, at the end of the IMPLEMENT phase.
- Do not re-read a file after editing it.

## Project rules in these phases

- The plan the user approved is the confirmation `AGENTS.md` requires before implementing; do not ask for it again.
- The plan already holds the research for its libraries and APIs. Search the web only for a library or API the plan does not cover.
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
- Never commit or push, and never spawn subagents.

## Report

Write this report into the ledger at the end of the phase and show it in the conversation, leaving out the sections that do not apply to the mode:

```
STATUS: DONE | BLOCKED
CHANGED FILES:
- <path>: <what changed>
FINDINGS:
- <ID>: FIXED - <changed paths>: <what changed>
- <ID>: SKIPPED - <evidence>
TESTS RUN:
- <command>: <result>
BLOCKER: <for BLOCKED>
```
