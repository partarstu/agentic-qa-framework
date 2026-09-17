---
name: implementing-changes
description: Implements an approved plan, change request or bug fix with review and test loops - an implementer subagent fixes what a fresh reviewer and tester report each round until no CRITICAL, HIGH or MEDIUM finding is open and the unit tests pass with 80% changed-line coverage, then the smoke suite runs once if the user agrees. Use when the user asks to implement an approved plan, to implement a change or bug fix with review and test loops, or to run the implementation loop.
argument-hint: "[plan file or change request]"
---

# Implementing Changes

You are the lead: you coordinate three subagents and act on their reports. You never implement or fix anything yourself, and you are the only one who talks to the user.

You require a tool that can spawn subagents, plus git and `uv`, and Docker for the smoke tests. Without subagents, tell the user that they are absent and stop: the loop relies on a reviewer and a tester that did not write the code.

Copy this checklist and track progress:

```
- [ ] 1. Intake
- [ ] 2. Implement
- [ ] 3. Verification loop
- [ ] 4. Smoke tests
- [ ] 5. Final report
```

## Subagents

| Role        | Instructions                                         | Claude Code agent type             | Lifetime                         | Edits files |
|-------------|------------------------------------------------------|------------------------------------|----------------------------------|-------------|
| Implementer | [resources/implementer.md](resources/implementer.md) | `implementing-changes-implementer` | one agent, resumed for every fix | yes         |
| Reviewer    | [resources/reviewer.md](resources/reviewer.md)       | `implementing-changes-reviewer`    | a fresh agent for every round    | no          |
| Tester      | [resources/tester.md](resources/tester.md)           | `implementing-changes-tester`      | a fresh agent for every round    | no          |

- Before spawning any subagent, ask the user in one prompt which model each role (implementer, reviewer, tester) should use, with a selection list per role built from the models currently available to the CLI. When the newest ledger under `<system temp>/implementing-changes/` records the models of a previous run, offer them first as the last run's choice. Recommend a reviewer model that differs from the implementer's, so that the two do not share blind spots. Record the choice in the ledger and pass it on every spawn and resume of that role. When the user declines to choose, spawn without a model and let the CLI's default apply.
- Spawn every subagent yourself, without your conversation history. In Claude Code use the agent type from the table, which enforces the role's tool limits; where that type is missing, and in other tools, use a general-purpose agent (in Codex a new agent without forked turns). Subagents do not spawn subagents.
- The implementer never runs at the same time as a reviewer or a tester: they share the working tree. The reviewer and the tester of a round run in parallel: the reviewer only reads, and the tester writes only git-ignored files, such as the coverage report and the test caches.
- Brief a subagent with the absolute paths of its role file and of the skill directory, its mode, the plan and the inputs its step lists. Pass no other earlier results: a reviewer that knows earlier conclusions stops looking.
- Resume the implementer for every fix so it keeps its context: `SendMessage` to its agent ID in Claude Code, a follow-up in its thread in Codex. Where resuming is impossible, spawn a new implementer with the plan and the ledger.
- A subagent that needs a decision returns `NEEDS_INPUT` with a question. Ask the user, then resume or re-brief it with the answer. On `BLOCKED`, tell the user the reason and stop.

## Run directory

Create the run directory `<system temp>/implementing-changes/<yyyyMMdd-HHmmss>`, outside the repository. Keep `ledger.md` in it and update it after every report; after a context reset, re-read it before continuing. The ledger holds the plan or its path, the model of each role, the baseline tree ID, the tree ID of every round, the round count of the verification loop, the baseline test results, every finding (ID, severity, confidence, location, title, status `OPEN`, `FIXED`, `SKIPPED` or `DISPUTED`, and the reason for a skip), the latest test verdict, the smoke verdict and the A/B baselines left for the user to refresh.

[scripts/task_diff.py](scripts/task_diff.py) snapshots the working tree, untracked files included, into a separate git index in the run directory. The real index, the working tree and the user's uncommitted work stay untouched, and a diff holds only what changed since the given snapshot:

```bash
uv run --no-project <skill dir>/scripts/task_diff.py <repo root> <run dir>                            # prints the tree ID of the working tree
uv run --no-project <skill dir>/scripts/task_diff.py <repo root> <run dir> <tree ID> [<diff name>]    # writes <run dir>/<diff name> (default task.diff), prints changed paths
```

The tester measures coverage with [scripts/coverage.py](scripts/coverage.py), as `resources/tester.md` describes.

## 1. Intake

1. The input is an implementation plan, a change request or a request for a bug fix. Without a plan the user has approved, write one with the `architecting-features` skill and get the user's approval. The approval covers the whole loop, including the fixes the reviewer and the tester request.
2. Every open question in the plan or the change request must be answered by the user before anything else starts. Ask them now, write the answers into the plan, and do not take the baseline or spawn any subagent while a question is unanswered.
3. Ask for the models of the roles, create the run directory, take the baseline snapshot and record its tree ID.
4. Spawn a tester in `BASELINE` mode. Record the total coverage and the tests that already fail.

When the change already exists as uncommitted work (e.g. a previous session implemented it), the working tree is not the "before" state:

- Use `git rev-parse HEAD^{tree}` as the baseline tree ID, so the diff covers the existing work.
- Run the baseline tester in a detached worktree at `HEAD` inside the run directory (`git worktree add --detach <run dir>/baseline-worktree HEAD`), with the worktree rule from `resources/tester.md`. Remove the worktree (`git worktree remove`) after the final report.
- Skip *2. Implement* and start with the verification loop.

## 2. Implement

Spawn the implementer in `IMPLEMENT` mode with the plan and the path of the plan file, if there is one. Continue when it returns `DONE`.

## 3. Verification loop

At most 5 rounds over the whole task. In each round:

1. Take a snapshot and record its tree ID. Write the task diff against the baseline tree and, from the second round on, the round diff (`round.diff`) against the tree of the previous round.
2. Spawn a reviewer and a tester in parallel, and wait for both reports:
   - the reviewer in `FULL` mode in the first round and in `FOLLOW_UP` mode afterwards, with the task diff, the round diff, the changed paths and all `SKIPPED` findings with their reasons
   - the tester in `VERIFY` mode with the task diff and the baseline test results
3. Record every finding with an ID `R<round>-<number>`. LOW findings and findings with a confidence below 80 are recorded but never sent for fixing.
4. Check every finding the implementer answered with `FIXED` in the previous round: if the round diff changes none of the paths it named, the fix is missing, so set the finding back to `OPEN`.
5. When the reviewer re-raises a `SKIPPED` finding with new evidence, set it back to `OPEN`. If the implementer skips it again, mark it `DISPUTED`: it stops blocking and goes to the final report for the user to decide.
6. If no CRITICAL, HIGH or MEDIUM finding with a confidence of at least 80 is `OPEN` and the tester's verdict is `PASS`, continue with the smoke tests.
7. Otherwise resume the implementer with one brief: the blocking open findings in `FIX_FINDINGS` mode and, on `FAIL`, the tester's report in `FIX_TESTS` mode. It answers each finding with `FIXED`, or with `SKIPPED` and evidence; send a skip without concrete evidence back to it. Then start the next round.

When the loop reaches its limit, show the user what is still open and ask whether to continue with more rounds, and how many, or to stop and write the final report.

## 4. Smoke tests

The smoke suite needs the Docker stack and makes billed Gemini calls, so it runs at most once per task, only after a round of the verification loop has passed and only when the user explicitly agrees:

1. Ask the user whether to run the smoke suite now, and wait for the answer. When the user declines, continue with the final report.
2. Write the task diff against the baseline tree and spawn a tester in `SMOKE` mode with the plan and the task diff.
3. On `PASS`, the task is done.
4. On `FAIL`, ask the user about every failure with the likely cause `unrelated`, and about every A/B comparison failure with the likely cause `intended change`, before sending it for fixing. An intended change the user confirms is never sent for fixing: record its A/B baseline for the user to refresh. If no failure is left to fix, the task is done.
5. Otherwise resume the implementer in `FIX_SMOKE` mode with the failures to fix. Its fixes are unreviewed and untested: start the next round of the verification loop. Once it passes, the task is done without another smoke run.

## 5. Final report

Report in the conversation:

- the changed files and the number of verification rounds
- the fixed findings by severity
- every `SKIPPED` and `DISPUTED` finding with the implementer's reason
- the LOW findings and the findings with a confidence below 80
- the test result, the changed-line coverage and the total coverage against the baseline
- the smoke test result, or that the user declined the smoke run, and every smoke test adapted with the plan requirement that changed it
- the plan file, if there is one, for the user to keep or delete, and the run directory
- the steps left for the user:
  - running the smoke suite, when it did not run or smoke failures were fixed after it (*Hermetic smoke suite* in `AGENTS.md`)
  - refreshing the recorded A/B baselines and every baseline refresh the plan asks for, with the capture command in `AGENTS.md`
  - CALM validation, lint, license, security and dependency checks and the other pull request checks, with the `preparing-pull-requests` skill

Never commit, push or open a pull request.
