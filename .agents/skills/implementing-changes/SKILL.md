---
name: implementing-changes
description: Implements an approved plan or a change request (feature, extension or bug fix) through three subagents - an implementer, a fresh reviewer per round and a fresh tester per round - looping until the review has no CRITICAL, HIGH or MEDIUM findings and the unit tests pass with at least 80% coverage of the changed lines and no drop in total coverage, then reports skipped and disputed findings. Use when the user asks to implement something with review and test loops, or to run the implementation loop.
---

# Implementing Changes

You are the lead: you coordinate three subagents and act on their reports. You never implement or fix anything
yourself, and you are the only one who talks to the user.

Requires a tool that can spawn subagents, plus git and `uv`. Without subagents, tell the user and stop: the loop relies
on a reviewer and a tester that did not write the code.

Copy this checklist and track progress:

```
- [ ] 1. Intake
- [ ] 2. Implement
- [ ] 3. Review loop
- [ ] 4. Test loop
- [ ] 5. Final report
```

## Subagents

| Role        | Instructions                                         | Lifetime                             | Edits files |
|-------------|------------------------------------------------------|--------------------------------------|-------------|
| Implementer | [resources/implementer.md](resources/implementer.md) | one agent, resumed for every fix     | yes         |
| Reviewer    | [resources/reviewer.md](resources/reviewer.md)       | a fresh agent for every review round | no          |
| Tester      | [resources/tester.md](resources/tester.md)           | a fresh agent for every test round   | no          |

[resources/project.md](resources/project.md) lists this project's rules, skills and commands for all roles.

- Before spawning any subagent, ask the user which model each role (implementer, reviewer, tester) should use. Build
  the selection list from the models currently available to the CLI's configured providers (in Jcode: `swarm
  action=list_models`), then ask in the form of selection list for each role, so that user won't have to type anything but simply select. Pass the chosen 
  model on every spawn and re-spawn of that role. When the user declines to choose, spawn without a model and let the CLI's default apply.
- Spawn every subagent yourself, without your conversation history: in Claude Code a `general-purpose` agent, in Codex
  a new agent without forked turns, elsewhere the tool's equivalent. Subagents do not spawn subagents.
- Run one subagent at a time; they share the working tree.
- Brief a subagent with the absolute paths of its role file and of `resources/project.md`, its mode, the plan and the
  inputs its step lists. Pass no other earlier results: a reviewer that knows earlier conclusions stops looking.
- Resume the implementer for every fix so it keeps its context: `SendMessage` to its agent ID in Claude Code, a
  follow-up in its thread in Codex. Where resuming is impossible, spawn a new implementer with the plan and the ledger.
- A subagent that needs a decision returns `NEEDS_INPUT` with a question. Ask the user, then resume or re-brief it with
  the answer. On `BLOCKED`, tell the user the reason and stop.

## Run directory

Create a run directory in the system temp directory, outside the repository. Keep `ledger.md` in it and update it
after every report; after a context reset, re-read it before continuing. The ledger holds the plan or its path, the
baseline tree ID, the tree ID of the last passed review, the round count of both loops, the baseline test results,
every finding (ID, severity, location, title, status `OPEN`, `FIXED`, `SKIPPED` or `DISPUTED`, and the reason for a
skip) and the latest test verdict.

[scripts/task_diff.py](scripts/task_diff.py) snapshots the working tree, untracked files included, into a separate git
index in the run directory. The real index, the working tree and the user's uncommitted work stay untouched, and the
diff holds only what changed since the given snapshot:

```bash
uv run --no-project <skill dir>/scripts/task_diff.py <run dir>             # prints the tree ID of the working tree
uv run --no-project <skill dir>/scripts/task_diff.py <run dir> <tree ID>   # writes <run dir>/task.diff, prints changed paths
```

## 1. Intake

1. The input is an implementation plan or a change request. Without a plan the user has approved, write one with the
   planning skill in `resources/project.md` and get the user's approval. The approval covers the whole loop, including
   the fixes the reviewer and the tester request.
2. Clarify open questions with the user now, so the loops can run without stopping.
3. Create the run directory, take the baseline snapshot and record its tree ID.
4. Spawn a tester in `BASELINE` mode. Record the total coverage and the tests that already fail.

When the change already exists as uncommitted work (e.g. a previous session implemented it), the working tree is not
the "before" state:

- Use `git rev-parse HEAD^{tree}` as the baseline tree ID, so the diff covers the existing work.
- Run the baseline tester in a detached worktree at `HEAD` inside the run directory
  (`git worktree add --detach <run dir>/baseline-worktree HEAD`), with the environment rule from
  `resources/project.md`. Remove the worktree (`git worktree remove`) after the final report.
- Skip step 2 and start with the review loop.

## 2. Implement

Spawn the implementer in `IMPLEMENT` mode with the plan. Continue when it returns `DONE`.

## 3. Review loop

At most 5 rounds over the whole task. In each round:

1. Write the diff against the baseline tree, or against the tree of the last passed review when the test loop reopened
   the review. Spawn a reviewer with the diff file, the changed paths and all `SKIPPED` findings with their reasons.
2. Record every finding with an ID `R<round>-<number>`. LOW findings are recorded but never sent for fixing.
3. When the reviewer re-raises a `SKIPPED` finding with new evidence, set it back to `OPEN`. If the implementer skips it
   again, mark it `DISPUTED`: it stops blocking and goes to the final report for the user to decide.
4. If no CRITICAL, HIGH or MEDIUM finding is `OPEN`, take a snapshot, record its tree ID as the last passed review and
   continue with the test loop.
5. Otherwise resume the implementer in `FIX_FINDINGS` mode with the open CRITICAL, HIGH and MEDIUM findings. It answers
   each with `FIXED`, or with `SKIPPED` and evidence; send a skip without concrete evidence back to it. Then start the
   next round.

## 4. Test loop

At most 5 rounds over the whole task. In each round:

1. Write the diff against the baseline tree and spawn a tester in `VERIFY` mode with the diff file and the baseline test
   results.
2. On `FAIL`, resume the implementer in `FIX_TESTS` mode with the tester's report and start the next round.
3. On `PASS`, take a snapshot. If its tree ID differs from the last passed review, the test fixes are unreviewed: run
   the review loop for the changes since that tree, then the test loop again. Otherwise the task is done.

When a loop reaches its limit, stop and write the final report with everything still open.

## 5. Final report

Report in the conversation:

- the changed files and the number of rounds of each loop
- the fixed findings by severity
- every `SKIPPED` and `DISPUTED` finding with the implementer's reason
- the LOW findings
- the test result, the changed-line coverage and the total coverage against the baseline
- the steps left for the user, listed in `resources/project.md`

Never commit, push or open a pull request.
