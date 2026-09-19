---
name: implementing-changes
description: Implements an approved plan, change request or bug fix in small work packages with review and test loops - the lead agent implements and fixes in its own context, while an independent headless reviewer and tester (separate claude -p processes, fed from handover files in the run directory) verify each round in parallel, until no CRITICAL, HIGH or MEDIUM finding with confidence >= 40 is open and the unit tests pass with 80% changed-line coverage, then one integration test run over the whole task. Use when the user asks to implement an approved plan, to implement a change or bug fix with review and test loops, to run the implementation loop, or to resume an implementation run after a context reset.
argument-hint: "[plan file or change request] | resume [run directory]"
---

# Implementing Changes

You are the lead agent. You run the IMPLEMENT and FIX phases yourself, in the main session, and keep your context across packages. The BASELINE, REVIEW and TEST phases run as headless `claude -p` processes that you launch with [scripts/run_phase.py](scripts/run_phase.py): independent agents with a fresh context, the project's system prompt, `AGENTS.md` and the skills, but none of your memory. Everything they need comes from files in the run directory, and everything they learn goes back there. Never spawn subagents or other background agents. You require git, `uv` and the `claude` CLI on the PATH.

Copy this checklist and track progress:

```
- [ ] 1. Intake (plan, open questions, models, baseline)
- [ ] 2. Work packages
- [ ] 3. Package loop (implement → review ∥ test → fix, per package)
- [ ] 4. Integration check
- [ ] 5. Final report
```

## Phases

| Phase     | Instructions                                         | Runs as                        | Edits project files         |
|-----------|------------------------------------------------------|--------------------------------|-----------------------------|
| BASELINE  | [resources/tester.md](resources/tester.md)           | headless tester                | no (git-ignored files only) |
| IMPLEMENT | [resources/implementer.md](resources/implementer.md) | you                            | yes                         |
| REVIEW    | [resources/reviewer.md](resources/reviewer.md)       | headless reviewer              | no                          |
| TEST      | [resources/tester.md](resources/tester.md)           | headless tester                | no (git-ignored files only) |
| FIX       | [resources/implementer.md](resources/implementer.md) | you                            | yes                         |

Read `resources/implementer.md` when the first IMPLEMENT phase starts and follow it in every IMPLEMENT and FIX phase. Do not read `resources/reviewer.md` or `resources/tester.md`: the script appends them to the system prompt of the headless agents, and their content is not your concern.

## Context budget

Every turn re-reads the whole context, so its size is the cost. The work packages (see *2. Work packages*) keep each phase small:

- A phase works on one package: the package file, the package diff and the files they name. Never load the whole plan or the whole task diff into a phase, except the task diff in the integration check.
- Read a file over about 300 lines with Grep and ranged reads (offset and limit), not whole. Never print several files at once, and do not re-read a file after editing it.
- From a headless phase read only its report file, never its log or its raw JSON output. The script prints one summary line; that is all that enters your context.
- Keep test output out of the context: redirect it to a log file in the run directory and read only the summary and the failure blocks.

When your context has grown large between packages, you may run `/compact "keep only the ledger path and the next phase"`; the ledger holds everything a phase needs.

## Headless phases

A headless phase is launched from the repository root:

```bash
uv run --no-project <skill dir>/scripts/run_phase.py <reviewer|tester> <run dir> <brief file> --model <model> --effort <effort>
```

The script strips the variables that stop `claude` from starting inside a running session, pipes the brief as the prompt, appends `resources/<role>.md` to the system prompt, and confines the process: it may edit only files under the run directory, the tester may run `uv run ...`, and the reviewer `uv run ruff ...`; anything else that would prompt is denied. It writes the raw output to `<run dir>/logs/<brief name>.json` (and `.stderr`) and prints one line: `<role> exit=<code> turns=<n> cost=$<x>: <the agent's closing line>`. Its exit code is the one of `claude`. There is no turn cap: the round cap of the package loop bounds the run.

Run every headless phase with the Bash tool in the background (`run_in_background`) so that the reviewer and the tester of a round run in parallel; continue when both have finished. Then:

1. Read the report file the brief named. When it is missing or the exit code is not 0, read the `.stderr` file and the last lines of the `.json` file, and show the user what happened before anything else.
2. Take a snapshot and compare its tree ID with the round's tree ID. When they differ, a headless agent changed a project file: show the user the diff and stop.
3. Record the report and the printed cost in the ledger.

The brief is a Markdown file you write, with absolute paths, since the headless agent has no other context. Reviewer brief, `<run dir>/review/P<n>R<r>-brief.md`:

```
Phase: REVIEW of an implementing-changes run, package P<n>, round <r>, mode <FULL | FOLLOW_UP>. Follow your role instructions.
- Repository root: <path>
- Package file: <run dir>/packages/P<n>.md
- Changes file: <run dir>/rounds/P<n>R<r>-changes.md
- Package diff: <run dir>/P<n>.diff; changed paths: <paths>
- Round diff (FOLLOW_UP): <run dir>/P<n>-round.diff; changed paths: <paths>
- Notes file: <run dir>/review/P<n>-notes.md (FULL: does not exist yet, create it)
- Report file: <run dir>/review/P<n>R<r>-report.md
- Open findings: <ID, severity, confidence, location, title, one per line>, or: none
- Skipped findings: <ID, title, skip reason, one per line>, or: none
```

Tester brief, `<run dir>/test/P<n>R<r>-brief.md` (`baseline-brief.md` and `integration-brief.md` for the BASELINE phase and the integration check):

```
Phase: <BASELINE | TEST> of an implementing-changes run, mode <BASELINE | VERIFY>, package P<n>, round <r>. Follow your role instructions.
- Repository root: <path of the main checkout, or of the baseline worktree>
- Main checkout (worktree runs only): <path>
- Skill directory: <skill dir>
- State file: <run dir>/test/state.md (BASELINE: does not exist yet, create it)
- Diff file (VERIFY): <run dir>/P<n>.diff, or task.diff in the integration check
- Changes file (VERIFY): <run dir>/rounds/P<n>R<r>-changes.md
- Log file: <run dir>/logs/P<n>R<r>_pytest.log
- Report file: <run dir>/test/P<n>R<r>-report.md
```

## Resume

`resume [<run dir>]` continues a run after `/clear`, `/compact` or in a new session. Without a run directory, take the newest one under `<system temp>/implementing-changes/`. Read `ledger.md`, restate `Next phase` in one line and continue with that phase and its inputs from the ledger. Do not re-read results that the ledger already holds; do not redo a phase the ledger marks as done. A headless phase that was running when the context was reset has to be launched again.

## Run directory

Create the run directory `<system temp>/implementing-changes/<yyyyMMdd-HHmmss>`, outside the repository, with the subdirectories `packages`, `rounds`, `review`, `test` and `logs`:

```
ledger.md                         your memory: update it at the end of every phase
packages/P<n>.md                  the plan text of one package
rounds/P<n>R<r>-changes.md        your handover per round: what changed, where and why (see resources/implementer.md)
review/P<n>R<r>-brief.md          brief for the reviewer          review/P<n>R<r>-report.md   its findings
review/P<n>-notes.md              the reviewer's own notes across the rounds of a package; never read or edit it
test/P<n>R<r>-brief.md            brief for the tester            test/P<n>R<r>-report.md     its verdict
test/state.md                     the tester's own state across the run; never read or edit it
P<n>.diff, P<n>-round.diff        package diff and round diff     task.diff                   diff of the whole task
logs/                             pytest logs and the raw output of the headless runs
```

The ledger holds:

- the plan or its path, the run directory, the skill directory, the repository root
- the model and effort chosen for the reviewer and the tester
- the baseline tree ID and the baseline report
- the package list with the status, the start tree ID and the round count of every package, and the tree ID of every round
- every finding: ID, severity, confidence, location, title, status `OPEN`, `FIXED`, `SKIPPED` or `DISPUTED`, and the reason for a skip
- the latest review report and the latest test report of the current package, copied from the report files
- the cost printed for every headless run
- the A/B baselines left for the user to refresh
- `Next phase: <PHASE> (package P<n>, round <r>)`, with the inputs the phase needs (package file, diff file names, changes file, open finding IDs)

[scripts/task_diff.py](scripts/task_diff.py) snapshots the working tree, untracked files included, into a separate git index in the run directory. The real index, the working tree and the user's uncommitted work stay untouched, and a diff holds only what changed since the given snapshot:

```bash
uv run --no-project <skill dir>/scripts/task_diff.py <repo root> <run dir>                            # prints the tree ID of the working tree
uv run --no-project <skill dir>/scripts/task_diff.py <repo root> <run dir> <tree ID> [<diff name>]    # writes <run dir>/<diff name> (default task.diff), prints changed paths
```

The tree IDs are ordinary git tree objects, so `git diff <tree ID> <tree ID> -- <paths>` restricts a diff to the paths of one package.

Coverage is measured by the tester with [scripts/coverage.py](scripts/coverage.py), as `resources/tester.md` describes.

## 1. Intake

1. The input is an implementation plan, a change request or a request for a bug fix. Without a plan the user has approved, write one with the `architecting-features` skill and get the user's approval. The approval covers the whole loop, including the fixes the review and test phases request.
2. Every open question in the plan or the change request must be answered by the user before anything else starts. Ask them now, write the answers into the plan, and do not take the baseline while a question is unanswered.
3. Ask the user with one `AskUserQuestion` call of four single-select questions: the reviewer's model, the reviewer's effort, the tester's model and the tester's effort. Offer the model aliases `opus`, `sonnet`, `haiku` and `fable` as the options and `low`, `medium`, `high` and `xhigh` as the effort options. Put the recommended option first and label it: for the reviewer a model that differs from yours, so that the two do not share blind spots, at `high`; for the tester, whose work is mechanical, `sonnet` at `low`. Record the answers in the ledger.
4. Create the run directory, take the baseline snapshot and record its tree ID.
5. Run the BASELINE phase headless with the tester's brief and record its report.

When the change already exists as uncommitted work (e.g. a previous session implemented it), the working tree is not the "before" state:

- Use `git rev-parse HEAD^{tree}` as the baseline tree ID, so the diff covers the existing work.
- Run the BASELINE phase in a detached worktree at `HEAD` inside the run directory (`git worktree add --detach <run dir>/baseline-worktree HEAD`), with the worktree as the repository root and the main checkout named in the brief. Remove the worktree (`git worktree remove`) after the final report.
- Cut the existing work into packages by the paths it changed, as *2. Work packages* describes, write each package diff with `git diff <baseline tree> <snapshot tree> -- <paths>`, write a round 1 changes file per package from the diff, and run every package through *3. Package loop* from step 3 on, without implementing.

## 2. Work packages

Split the plan into work packages and write them into the ledger. A package is:

- one plan phase, work stream or requirement group that can be implemented and tested on its own, of at most about five source files plus their tests, and their documentation, CALM and smoke-suite updates
- ordered so that every package depends only on earlier ones
- described in its own file `<run dir>/packages/P<n>.md` that holds only the plan text of that package, verbatim, plus the few lines of context it needs from earlier packages (e.g. a signature or a model another package introduced)

A bug fix or a small change request is one package. When a plan is too vague to cut, ask the user. When in doubt, cut smaller: a small package keeps every phase's context small.

## 3. Package loop

Run the packages in order. For each package:

1. Take a snapshot and record it as the package's start tree ID.
2. Run the IMPLEMENT phase with the package file and write the round 1 changes file. Its report goes into the ledger.
3. Verify the package, at most 5 rounds:
   1. Take a snapshot and record it as the round's tree ID. Write the package diff (`P<n>.diff`) against the package's start tree and, from the second round on, the round diff (`P<n>-round.diff`) against the tree of the previous round. Record the file names and the changed paths in the ledger.
   2. Write the reviewer brief (`FULL` mode in the first round, `FOLLOW_UP` afterwards, with the open findings and the `SKIPPED` findings of the package) and the tester brief (`VERIFY` mode with the package diff). Launch both headless phases in parallel and handle their results as *Headless phases* describes.
   3. Record every finding of the review report in the ledger under the ID the reviewer gave it. LOW findings and findings with a confidence below 40 are recorded but never fixed in the loop.
   4. Apply the reviewer's `FIX CHECK`: a finding reported `OPEN` again goes back to `OPEN`; a `RE-RAISED` finding goes back to `OPEN`, and if the FIX phase skips it again, mark it `DISPUTED`: it stops blocking and goes to the final report for the user to decide.
   5. If no CRITICAL, HIGH or MEDIUM finding with a confidence of at least 40 is `OPEN` and the test verdict is `PASS`, the package is done: continue with the next one.
   6. Otherwise run the FIX phase with one brief from the ledger: the blocking open findings in `FIX_FINDINGS` mode and, on `FAIL`, the test report in `FIX_TESTS` mode. Write the changes file of the next round, whose `Findings` section answers every finding with `FIXED`, or with `SKIPPED` and concrete evidence; a skip without evidence is not accepted. Update the finding statuses in the ledger and start the next round.

When a package reaches its round limit, show the user what is still open and ask whether to continue with more rounds, and how many, or to move on and leave the findings for the final report.

## 4. Integration check

After the last package, write the task diff against the baseline tree and run the TEST phase headless in `VERIFY` mode with the task diff as the diff file and the last changes file. This is the only unit test run over the whole task; the packages were reviewed one by one, so no REVIEW phase runs here.

On `FAIL`, run the FIX phase in `FIX_TESTS` mode with the test report, write a changes file (`rounds/integration-R<r>-changes.md`), then repeat the check, at most 2 times. When it still fails, show the user the report and ask whether to continue or to stop and write the final report.

The smoke suite, including its A/B comparison, never runs in this loop: it needs the Docker stack and makes billed Gemini calls, so the user runs it manually after the task.

## 5. Final report

Report in the conversation:

- the changed files, the packages and the number of verification rounds of each
- the fixed findings by severity
- every `SKIPPED` and `DISPUTED` finding with the reason
- the LOW findings and the findings with a confidence below 40
- the test result, the changed-line coverage and the total coverage against the baseline
- the total cost of the headless runs, from the ledger
- the plan file, if there is one, for the user to keep or delete, and the run directory
- the steps left for the user:
  - running the smoke suite, including the A/B comparison (*Hermetic smoke suite* in `AGENTS.md`)
  - refreshing the recorded A/B baselines and every baseline refresh the plan asks for, with the capture command in `AGENTS.md`
  - CALM validation, lint, license, security and dependency checks and the other pull request checks, with the `preparing-pull-requests` skill

Never commit, push or open a pull request.
