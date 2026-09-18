---
name: implementing-changes
description: Implements an approved plan, change request or bug fix in small work packages with review and test loops - a fresh implementer subagent per package fixes what a fresh reviewer and tester report each round until no CRITICAL, HIGH or MEDIUM finding is open and the unit tests pass with 80% changed-line coverage, then the smoke suite runs once if the user agrees. Use when the user asks to implement an approved plan, to implement a change or bug fix with review and test loops, or to run the implementation loop.
argument-hint: "[plan file or change request]"
---

# Implementing Changes

You are the lead: you coordinate three subagents and act on their reports. You never implement or fix anything yourself, and you are the only one who talks to the user.

You require a tool that can spawn subagents, plus git and `uv`, and Docker for the smoke tests. Without subagents, tell the user that they are absent and stop: the loop relies on a reviewer and a tester that did not write the code.

Copy this checklist and track progress:

```
- [ ] 1. Intake
- [ ] 2. Work packages
- [ ] 3. Package loop
- [ ] 4. Integration check
- [ ] 5. Smoke tests
- [ ] 6. Final report
```

## Token budget

The cost of a subagent is its number of turns multiplied by the size of its context on every turn, and nothing else. A single implementer that works through a whole plan runs for hundreds of turns with a context of several hundred thousand tokens, and exhausts the usage limit before it finishes. Therefore:

- Every subagent works on one work package (see *2. Work packages*), and its brief holds only that package. Never pass the whole plan, the whole scope, the ledger or a diff larger than the package to a subagent.
- Every agent type has a turn limit (`maxTurns` in `.claude/agents/`). A subagent that hits it returns a partial result. Do not resume it: record what its report says is done, take a snapshot, and spawn a fresh agent for the rest, split into smaller packages if the rest is still large.
- Reviews and tests run on package diffs of a few files. The whole task diff is used only by the tester in the integration check and in the smoke run, never by a reviewer.

## Subagents

| Role        | Instructions                                         | Claude Code agent type             | Lifetime                                                     | Edits files |
|-------------|------------------------------------------------------|------------------------------------|--------------------------------------------------------------|-------------|
| Implementer | [resources/implementer.md](resources/implementer.md) | `implementing-changes-implementer` | a fresh agent per package, resumed for the fixes of that package | yes         |
| Reviewer    | [resources/reviewer.md](resources/reviewer.md)       | `implementing-changes-reviewer`    | a fresh agent for every round                                | no          |
| Tester      | [resources/tester.md](resources/tester.md)           | `implementing-changes-tester`      | a fresh agent for every round                                | no          |

- Before spawning any subagent, ask the user in one prompt which model each role (implementer, reviewer, tester) should use, with a selection list per role built from the models currently available to the CLI. When the newest ledger under `<system temp>/implementing-changes/` records the models of a previous run, offer them first as the last run's choice. Recommend a reviewer model that differs from the implementer's, so that the two do not share blind spots. Record the choice in the ledger and pass it on every spawn and resume of that role. When the user declines to choose, spawn without a model and let the CLI's default apply.
- Spawn every subagent yourself, without your conversation history. In Claude Code use the agent type from the table, which enforces the role's tool limits and turn limit; where that type is missing, and in other tools, use a general-purpose agent (in Codex a new agent without forked turns). Subagents do not spawn subagents.
- The implementer never runs at the same time as a reviewer or a tester: they share the working tree. The reviewer and the tester of a round run in parallel: the reviewer only reads, and the tester writes only git-ignored files, such as the coverage report and the test caches.
- Brief a subagent with the absolute paths of its role file and of the skill directory, its mode, the package file and the inputs its step lists. Pass no other earlier results: a reviewer that knows earlier conclusions stops looking.
- Resume the implementer of a package for the fixes of that package so it keeps its context: `SendMessage` to its agent ID in Claude Code, a follow-up in its thread in Codex. Where resuming is impossible, or the implementer hit its turn limit, spawn a new implementer with the package file and the findings.
- A subagent that needs a decision returns `NEEDS_INPUT` with a question. Ask the user, then resume or re-brief it with the answer. On `BLOCKED`, tell the user the reason and stop.

## Run directory

Create the run directory `<system temp>/implementing-changes/<yyyyMMdd-HHmmss>`, outside the repository. Keep `ledger.md` in it and update it after every report; after a context reset, re-read it before continuing. The ledger holds the plan or its path, the model of each role, the baseline tree ID, the package list with the status, the start tree ID and the round count of every package, the baseline test results, every finding (ID, severity, confidence, location, title, status `OPEN`, `FIXED`, `SKIPPED` or `DISPUTED`, and the reason for a skip), the latest test verdict, the smoke verdict and the A/B baselines left for the user to refresh.

[scripts/task_diff.py](scripts/task_diff.py) snapshots the working tree, untracked files included, into a separate git index in the run directory. The real index, the working tree and the user's uncommitted work stay untouched, and a diff holds only what changed since the given snapshot:

```bash
uv run --no-project <skill dir>/scripts/task_diff.py <repo root> <run dir>                            # prints the tree ID of the working tree
uv run --no-project <skill dir>/scripts/task_diff.py <repo root> <run dir> <tree ID> [<diff name>]    # writes <run dir>/<diff name> (default task.diff), prints changed paths
```

The tree IDs are ordinary git tree objects, so `git diff <tree ID> <tree ID> -- <paths>` restricts a diff to the paths of one package.

The tester measures coverage with [scripts/coverage.py](scripts/coverage.py), as `resources/tester.md` describes.

## 1. Intake

1. The input is an implementation plan, a change request or a request for a bug fix. Without a plan the user has approved, write one with the `architecting-features` skill and get the user's approval. The approval covers the whole loop, including the fixes the reviewer and the tester request.
2. Every open question in the plan or the change request must be answered by the user before anything else starts. Ask them now, write the answers into the plan, and do not take the baseline or spawn any subagent while a question is unanswered.
3. Ask for the models of the roles, create the run directory, take the baseline snapshot and record its tree ID.
4. Spawn a tester in `BASELINE` mode. Record the total coverage and the tests that already fail.

When the change already exists as uncommitted work (e.g. a previous session implemented it), the working tree is not the "before" state:

- Use `git rev-parse HEAD^{tree}` as the baseline tree ID, so the diff covers the existing work.
- Run the baseline tester in a detached worktree at `HEAD` inside the run directory (`git worktree add --detach <run dir>/baseline-worktree HEAD`), with the worktree rule from `resources/tester.md`. Remove the worktree (`git worktree remove`) after the final report.
- Cut the existing work into packages by the paths it changed, as *2. Work packages* describes, write each package diff with `git diff <baseline tree> <snapshot tree> -- <paths>`, and run every package through *3. Package loop* from step 2 on, without implementing.

## 2. Work packages

Split the plan into work packages and write them into the ledger. A package is:

- one plan phase, work stream or requirement group that can be implemented and tested on its own, of at most about five source files plus their tests, and their documentation, CALM and smoke-suite updates
- ordered so that every package depends only on earlier ones
- described in its own file `<run dir>/packages/P<n>.md` that holds only the plan text of that package, verbatim, plus the few lines of context it needs from earlier packages (e.g. a signature or a model another package introduced)

A bug fix or a small change request is one package. When a plan is too vague to cut, ask the user. Never cut a package so large that an implementer needs more than its turn limit: when in doubt, cut smaller.

## 3. Package loop

Run the packages in order. For each package:

1. Take a snapshot and record it as the package's start tree ID.
2. Spawn a fresh implementer in `IMPLEMENT` mode with the package file. Continue when it returns `DONE`.
3. Verify the package, at most 3 rounds:
   1. Take a snapshot. Write the package diff (`P<n>.diff`) against the package's start tree and, from the second round on, the round diff (`P<n>-round.diff`) against the tree of the previous round.
   2. Spawn a reviewer and a tester in parallel, and wait for both reports:
      - the reviewer in `FULL` mode in the first round and in `FOLLOW_UP` mode afterwards, with the package file, the package diff, the round diff, the changed paths and all `SKIPPED` findings of the package with their reasons
      - the tester in `VERIFY` mode with the package diff and the baseline test results
   3. Record every finding with an ID `P<n>R<round>-<number>`. LOW findings and findings with a confidence below 80 are recorded but never sent for fixing.
   4. Check every finding the implementer answered with `FIXED` in the previous round: if the round diff changes none of the paths it named, the fix is missing, so set the finding back to `OPEN`.
   5. When the reviewer re-raises a `SKIPPED` finding with new evidence, set it back to `OPEN`. If the implementer skips it again, mark it `DISPUTED`: it stops blocking and goes to the final report for the user to decide.
   6. If no CRITICAL, HIGH or MEDIUM finding with a confidence of at least 80 is `OPEN` and the tester's verdict is `PASS`, the package is done: continue with the next one.
   7. Otherwise resume the package's implementer with one brief: the blocking open findings in `FIX_FINDINGS` mode and, on `FAIL`, the tester's report in `FIX_TESTS` mode. It answers each finding with `FIXED`, or with `SKIPPED` and evidence; send a skip without concrete evidence back to it. Then start the next round.

When a package reaches its round limit, show the user what is still open and ask whether to continue with more rounds, and how many, or to move on and leave the findings for the final report.

## 4. Integration check

After the last package, write the task diff against the baseline tree and spawn a tester in `VERIFY` mode with the task diff and the baseline test results. This is the only unit test run over the whole task; the packages were reviewed one by one, so no reviewer runs here.

On `FAIL`, spawn a fresh implementer in `FIX_TESTS` mode with the tester's report, then repeat the check, at most 2 times. When it still fails, show the user the report and ask whether to continue or to stop and write the final report.

## 5. Smoke tests

The smoke suite needs the Docker stack and makes billed Gemini calls, so it runs at most once per task, only after the integration check has passed and only when the user explicitly agrees:

1. Ask the user whether to run the smoke suite now, and wait for the answer. When the user declines, continue with the final report.
2. Write the task diff against the baseline tree and spawn a tester in `SMOKE` mode with the plan and the task diff.
3. On `PASS`, the task is done.
4. On `FAIL`, ask the user about every failure with the likely cause `unrelated`, and about every A/B comparison failure with the likely cause `intended change`, before sending it for fixing. An intended change the user confirms is never sent for fixing: record its A/B baseline for the user to refresh. If no failure is left to fix, the task is done.
5. Otherwise spawn a fresh implementer in `FIX_SMOKE` mode with the failures to fix. Its fixes are unreviewed and untested: treat them as one more package, verify it with step 3 of the package loop and repeat the integration check. Once both pass, the task is done without another smoke run.

## 6. Final report

Report in the conversation:

- the changed files, the packages and the number of verification rounds of each
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
