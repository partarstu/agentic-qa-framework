---
name: implementing-changes
description: Implements an approved plan, change request or bug fix completely in one run (the whole plan, or only the parts the user names) with review and test loops - the lead agent implements and fixes in its own context, while an independent headless reviewer and tester (separate claude -p processes, fed from handover files in the run directory) verify each round in parallel, until no CRITICAL, HIGH or MEDIUM finding with confidence >= 40 is open and the unit tests pass with 80% changed-line coverage. Use when the user asks to implement an approved plan, to implement a change or bug fix with review and test loops, to run the implementation loop, or to resume an implementation run after a context reset.
argument-hint: "[plan file or change request] | resume [run directory]"
---

# Implementing Changes

You are the lead agent. You run the IMPLEMENT and FIX phases yourself, in the main session, and keep your context across the rounds. The BASELINE, REVIEW and TEST phases run as headless `claude -p` processes that you launch with [scripts/run_phase.py](scripts/run_phase.py): independent agents with a fresh context, the project's system prompt, `AGENTS.md` and the skills, but none of your memory. Everything they need comes from files in the run directory, and everything they learn goes back there. Never spawn subagents or other background agents. You require git, `uv` and the `claude` CLI on the PATH.

Copy this checklist and track progress:

```
- [ ] 1. Intake (plan, open questions, scope, models, baseline)
- [ ] 2. Implement
- [ ] 3. Verification loop (review ∥ test → fix, per round)
- [ ] 4. Final report
```

## Phases

| Phase     | Instructions                                         | Runs as           | Edits project files         |
|-----------|------------------------------------------------------|-------------------|-----------------------------|
| BASELINE  | [resources/tester.md](resources/tester.md)           | headless tester   | no (git-ignored files only) |
| IMPLEMENT | [resources/implementer.md](resources/implementer.md) | you               | yes                         |
| REVIEW    | [resources/reviewer.md](resources/reviewer.md)       | headless reviewer | no                          |
| TEST      | [resources/tester.md](resources/tester.md)           | headless tester   | no (git-ignored files only) |
| FIX       | [resources/implementer.md](resources/implementer.md) | you               | yes                         |

Read `resources/implementer.md` when the IMPLEMENT phase starts and follow it in every IMPLEMENT and FIX phase. Do not read `resources/reviewer.md` or `resources/tester.md`: the script appends them to the system prompt of the headless agents, and their content is not your concern.

## Context budget

*Context budget* in `AGENTS.md` applies; test logs go into the run directory. From a headless phase read only its report file, never its log or its raw JSON output: the script prints one summary line, and that is all that enters your context.

When your context has grown large between rounds, you may run `/compact "keep only the ledger path and the next phase"`; the ledger holds everything a phase needs.

## Headless phases

A headless phase is launched from the repository root:

```bash
uv run --no-project <skill dir>/scripts/run_phase.py <reviewer|tester> <run dir> <brief file> --model <model> --effort <effort>
```

The script strips the variables that stop `claude` from starting inside a running session, pipes the brief as the prompt, appends `resources/<role>.md` to the system prompt, and confines the process: it may edit only files under the run directory, the tester may run `uv run ...`, and the reviewer `uv run ruff ...`; anything else that would prompt is denied. It writes the raw output to `<run dir>/logs/<brief name>.json` (and `.stderr`) and prints one line: `<role> exit=<code> turns=<n> cost=$<x>: <the agent's closing line>`. Its exit code is the one of `claude`. There is no turn cap: the round limit of the verification loop bounds the run.

Run every headless phase with the Bash tool in the background (`run_in_background`) so that the reviewer and the tester of a round run in parallel; continue when both have finished. Then:

1. Read the report file the brief named. When it is missing or the exit code is not 0, read the `.stderr` file and the last lines of the `.json` file, and show the user what happened before anything else.
2. Take a snapshot and compare its tree ID with the round's tree ID. When they differ, a headless agent changed a project file: show the user the diff and stop.
3. Record the report and the printed cost in the ledger.

The brief is a Markdown file you write, with absolute paths, since the headless agent has no other context. Reviewer brief, `<run dir>/review/R<r>-brief.md`:

```
Phase: REVIEW of an implementing-changes run, round <r>, mode <FULL | FOLLOW_UP>. Follow your role instructions.
- Repository root: <path>
- Plan file: <path>
- Scope: everything | <the parts the user named>
- Changes file: <run dir>/rounds/R<r>-changes.md
- Task diff: <run dir>/task.diff; changed paths: <paths>
- Round diff (FOLLOW_UP): <run dir>/round.diff; changed paths: <paths>
- Notes file: <run dir>/review/notes.md (FULL: does not exist yet, create it)
- Report file: <run dir>/review/R<r>-report.md
- Open findings: <ID, severity, confidence, location, title, one per line>, or: none
- Skipped findings: <ID, title, skip reason, one per line>, or: none
```

Tester brief, `<run dir>/test/R<r>-brief.md` (`baseline-brief.md` for the BASELINE phase):

```
Phase: <BASELINE | TEST> of an implementing-changes run, mode <BASELINE | VERIFY>, round <r>. Follow your role instructions.
- Repository root: <path of the main checkout, or of the baseline worktree>
- Main checkout (worktree runs only): <path>
- Skill directory: <skill dir>
- State file: <run dir>/test/state.md (BASELINE: does not exist yet, create it)
- Diff file (VERIFY): <run dir>/task.diff
- Changes file (VERIFY): <run dir>/rounds/R<r>-changes.md
- Log file: <run dir>/logs/R<r>_pytest.log
- Report file: <run dir>/test/R<r>-report.md
```

## Resume

`resume [<run dir>]` continues a run after `/clear`, `/compact` or in a new session. Without a run directory, take the newest one under `<system temp>/implementing-changes/`. Read `ledger.md`, restate `Next phase` in one line and continue with that phase and its inputs from the ledger. Do not re-read results that the ledger already holds; do not redo a phase the ledger marks as done. A headless phase that was running when the context was reset has to be launched again.

## Run directory

Create the run directory `<system temp>/implementing-changes/<yyyyMMdd-HHmmss>`, outside the repository, with the subdirectories `rounds`, `review`, `test` and `logs`:

```
ledger.md                your memory: update it at the end of every phase
rounds/R<r>-changes.md   your handover per round: what changed, where and why (see resources/implementer.md)
review/R<r>-brief.md     brief for the reviewer     review/R<r>-report.md   its findings
review/notes.md          the reviewer's own notes across the rounds; never read or edit it
test/R<r>-brief.md       brief for the tester       test/R<r>-report.md     its verdict
test/state.md            the tester's own state across the run; never read or edit it
task.diff, round.diff    diff of the whole task and of the last round
logs/                    pytest logs and the raw output of the headless runs
```

The ledger holds:

- the plan or its path, the run directory, the skill directory, the repository root
- the scope: `everything`, or the parts the user named
- the model and effort chosen for the reviewer and the tester
- the baseline tree ID, the tree ID of every round and the round count
- the baseline report
- every finding: ID, severity, confidence, location, title, status `OPEN`, `FIXED`, `SKIPPED` or `DISPUTED`, and the reason for a skip
- the latest review report and the latest test report, copied from the report files
- the cost printed for every headless run
- the A/B baselines left for the user to refresh
- `Next phase: <PHASE> (round <n>)`, with the inputs the phase needs (diff file names, changes file, open finding IDs)

[scripts/task_diff.py](scripts/task_diff.py) snapshots the working tree, untracked files included, into a separate git index in the run directory. The real index, the working tree and the user's uncommitted work stay untouched, and a diff holds only what changed since the given snapshot:

```bash
uv run --no-project <skill dir>/scripts/task_diff.py <repo root> <run dir>                            # prints the tree ID of the working tree
uv run --no-project <skill dir>/scripts/task_diff.py <repo root> <run dir> <tree ID> [<diff name>]    # writes <run dir>/<diff name> (default task.diff), prints changed paths
```

Coverage is measured by the tester with [scripts/coverage.py](scripts/coverage.py), as `resources/tester.md` describes.

## 1. Intake

1. The input is an implementation plan, a change request or a request for a bug fix. Without a plan the user has approved, write one with the `architecting-features` skill and get the user's approval. The approval covers the whole loop, including the fixes the review and test phases request. A plan that names an architecture change without the approval line of *Architecture first (CALM)* in `AGENTS.md` is refused: send it back to the `architecting-features` skill and do not start. The approved CALM change is applied to `calm/` in the IMPLEMENT phase.
2. Every open question in the plan or the change request must be answered by the user before anything else starts. Ask them now, write the answers into the plan, and do not take the baseline while a question is unanswered.
3. Settle the scope, the part of the plan to implement. When the user's request already names the parts to implement (phases, steps, findings or specific logic), never offer to implement everything: list those parts in a short summary and confirm them with one `AskUserQuestion` single-select question, `Implement these` (first, recommended) or `Change the selection`, whose description tells the user to type the changed parts through *Other*. Only when the request names no parts, ask with one `AskUserQuestion` single-select question: `Implement everything` (first, recommended) or `Implement specific parts`, whose description tells the user to type the parts through *Other*; when the user picks `Implement specific parts` without naming them, ask for them before going on. Record the scope in the ledger: `everything`, or the named parts verbatim. The scope is implemented completely in this run: never batch it, split it over several runs or stop after a part of it; a part outside the scope is not touched.
4. Ask the user with one `AskUserQuestion` call of four single-select questions: the reviewer's model, the reviewer's effort, the tester's model and the tester's effort. Offer the model aliases `opus`, `sonnet`, `haiku` and `fable` as the options and `low`, `medium`, `high` and `xhigh` as the effort options. Put the recommended option first and label it: for the reviewer a model that differs from yours, so that the two do not share blind spots, at `high`; for the tester, whose work is mechanical, `sonnet` at `low`. Record the answers in the ledger.
5. Create the run directory, take the baseline snapshot and record its tree ID.
6. Run the BASELINE phase headless with the tester's brief and record its report.

When the change already exists as uncommitted work (e.g. a previous session implemented it), the working tree is not the "before" state:

- Use `git rev-parse HEAD^{tree}` as the baseline tree ID, so the diff covers the existing work.
- Run the BASELINE phase in a detached worktree at `HEAD` inside the run directory (`git worktree add --detach <run dir>/baseline-worktree HEAD`), with the worktree as the repository root and the main checkout named in the brief. Remove the worktree (`git worktree remove`) after the final report.
- Skip *2. Implement*, write a round 1 changes file from the diff of the existing work, and start with the verification loop.

## 2. Implement

Run the IMPLEMENT phase with the plan, the scope from the ledger and the path of the plan file, if there is one, and write the round 1 changes file. Its report goes into the ledger.

## 3. Verification loop

At most 5 rounds over the whole task. In each round:

1. Take a snapshot and record it as the round's tree ID. Write the task diff against the baseline tree and, from the second round on, the round diff (`round.diff`) against the tree of the previous round. Record the file names and the changed paths in the ledger.
2. Write the reviewer brief (`FULL` mode in the first round, `FOLLOW_UP` afterwards, with the open findings and the `SKIPPED` findings) and the tester brief (`VERIFY` mode with the task diff). Launch both headless phases in parallel and handle their results as *Headless phases* describes.
3. Record every finding of the review report in the ledger under the ID the reviewer gave it. LOW findings and findings with a confidence below 40 are recorded but never fixed in the loop.
4. Apply the reviewer's `FIX CHECK`: a finding reported `OPEN` again goes back to `OPEN`; a `RE-RAISED` finding goes back to `OPEN`, and if the FIX phase skips it again, mark it `DISPUTED`: it stops blocking and goes to the final report for the user to decide.
5. If no CRITICAL, HIGH or MEDIUM finding with a confidence of at least 40 is `OPEN` and the test verdict is `PASS`, the task is done: continue with the final report.
6. Otherwise run the FIX phase with one brief from the ledger: the blocking open findings in `FIX_FINDINGS` mode and, on `FAIL`, the test report in `FIX_TESTS` mode. Write the changes file of the next round, whose `Findings` section answers every finding with `FIXED`, or with `SKIPPED` and concrete evidence; a skip without evidence is not accepted. Update the finding statuses in the ledger and start the next round.

When the loop reaches its limit, show the user what is still open and ask whether to continue with more rounds, and how many, or to stop and write the final report.

The smoke suite, which needs the Docker stack, and the billed A/B suite never run in this loop (*Smoke suite* and *A/B suite* in `AGENTS.md`); the user runs them after the task.

## 4. Final report

Report in the conversation, in the three parts `AGENTS.md` prescribes:

- **Blocked on me**:
  - every `DISPUTED` finding with the reason, for the user to decide
  - the steps left for the user: running the smoke suite, the A/B tests of the workflows the change touches and every baseline refresh the plan asks for (*Smoke suite* and *A/B suite* in `AGENTS.md`); CALM validation, lint, license, security and dependency checks and the other pull request checks, with the `preparing-pull-requests` skill
- **Changed**:
  - the scope implemented: everything, or the parts the user named
  - the changed files and the number of verification rounds
  - the fixed findings by severity
  - the test result, the changed-line coverage and the total coverage against the baseline
  - the total cost of the headless runs, from the ledger
- **Found**:
  - every `SKIPPED` finding with the reason
  - the LOW findings and the findings with a confidence below 40
  - the plan file, if there is one, for the user to keep or delete, and the run directory

Never open a pull request.
