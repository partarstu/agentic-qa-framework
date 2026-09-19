---
name: implementing-changes
description: Implements an approved plan, change request or bug fix in small work packages with review and test loops, all run sequentially by the main agent (no subagents) - per package an implement phase, then a review phase and a test phase per round, whose findings the fix phase resolves until no CRITICAL, HIGH or MEDIUM finding with confidence >= 40 is open and the unit tests pass with 80% changed-line coverage, then one integration test run over the whole task. Use when the user asks to implement an approved plan, to implement a change or bug fix with review and test loops, to run the implementation loop, or to resume an implementation run after a context reset.
argument-hint: "[plan file or change request] | resume [run directory]"
---

# Implementing Changes

You run every phase of this skill yourself, in the main session, one after the other. Never spawn a subagent, a background agent or a headless `claude -p` process: the loop is designed to stay cheap by running sequentially in one small context. You require git and `uv`.

Copy this checklist and track progress:

```
- [ ] 1. Intake (plan, open questions, models, baseline)
- [ ] 2. Work packages
- [ ] 3. Package loop (implement → review → test → fix, per package)
- [ ] 4. Integration check
- [ ] 5. Final report
```

## Phases

| Phase     | Instructions                                         | Edits project files         | Fresh context recommended |
|-----------|------------------------------------------------------|-----------------------------|---------------------------|
| BASELINE  | [resources/tester.md](resources/tester.md)           | no (git-ignored files only) | no                        |
| IMPLEMENT | [resources/implementer.md](resources/implementer.md) | yes                         | yes, per package          |
| REVIEW    | [resources/reviewer.md](resources/reviewer.md)       | no                          | **yes**                   |
| TEST      | [resources/tester.md](resources/tester.md)           | no (git-ignored files only) | no                        |
| FIX       | [resources/implementer.md](resources/implementer.md) | yes                         | no                        |

Read the phase's instruction file when the phase starts and follow it. The instruction files are written for the main agent: where they need a decision, ask the user directly.

## Context budget

Every turn re-reads the whole context, so its size is the cost. The work packages (see *2. Work packages*) keep each phase small, and the phase handover lets the user reset the context between them:

- A phase works on one package: the package file, the package diff and the files they name. Never load the whole plan or the whole task diff into a phase, except the task diff in the integration check.
- Read a file over about 300 lines with Grep and ranged reads (offset and limit), not whole. Never print several files at once, and do not re-read a file after editing it.
- Keep test output out of the context: redirect it to a log file in the run directory and read only the summary, the failure blocks and the coverage script output.

## Phase handover

The agent cannot change its own model or effort; only the user can, with `/model <alias>` and `/effort <low|medium|high|xhigh|max>`. Switching either re-prefills the whole context at full price, which is only cheap when the context is small. That is why the loop hands over between phases as follows:

1. Write the ledger first (see *Run directory*): the phase that just ended, its result, and `Next phase: <PHASE> (package P<n>, round <r>)`.
2. Print a phase card and end your turn:

   ```
   Next phase: REVIEW (package P2, round 1)
   Run directory: <run dir>
   Model / effort for this role: <last choice for the role, from the ledger>  (recommended: <see below>)
   Set them with /model and /effort if you want to change them, then reply "go".
   Fresh context recommended: run /clear, then /implementing-changes resume <run dir>.
   Otherwise reply "go" to continue here (optionally after /compact "keep only the ledger path and the next phase").
   ```

   Recommendations: use a reviewer model that differs from the implementer's, so that the two do not share blind spots; use a cheap model at low effort for BASELINE and TEST, which are mechanical; use the implementer's model for FIX.
3. Continue only when the user replies. Record in the ledger the model and effort the user names (or "kept").

Print the card before every REVIEW and before the IMPLEMENT phase of every package; before the other phases only when the user asked in intake to be prompted at every phase. Otherwise continue those phases directly in the current context.

A REVIEW that runs without a context reset must still judge the code as it is: read the changed files fresh and do not rely on the memory of writing them.

## Resume

`resume [<run dir>]` continues a run after `/clear` or in a new session. Without a run directory, take the newest one under `<system temp>/implementing-changes/`. Read `ledger.md`, restate `Next phase` in one line and continue with that phase and its inputs from the ledger. Do not re-read results that the ledger already holds; do not redo a phase the ledger marks as done.

## Run directory

Create the run directory `<system temp>/implementing-changes/<yyyyMMdd-HHmmss>`, outside the repository. Keep `ledger.md` in it and update it at the end of every phase, before the phase card; after a context reset, it is the only memory of the run. The ledger holds:

- the plan or its path, the run directory, the skill directory
- the model and effort chosen for each role, and whether the user wants a phase card before every phase
- the baseline tree ID and the baseline test results
- the package list with the status, the start tree ID and the round count of every package, and the tree ID of every round
- every finding: ID, severity, confidence, location, title, status `OPEN`, `FIXED`, `SKIPPED` or `DISPUTED`, and the reason for a skip
- the latest review report and the latest test verdict, in the formats of the instruction files
- the A/B baselines left for the user to refresh
- `Next phase: <PHASE> (package P<n>, round <r>)`, with the inputs the phase needs (package file, diff file names, open finding IDs)

[scripts/task_diff.py](scripts/task_diff.py) snapshots the working tree, untracked files included, into a separate git index in the run directory. The real index, the working tree and the user's uncommitted work stay untouched, and a diff holds only what changed since the given snapshot:

```bash
uv run --no-project <skill dir>/scripts/task_diff.py <repo root> <run dir>                            # prints the tree ID of the working tree
uv run --no-project <skill dir>/scripts/task_diff.py <repo root> <run dir> <tree ID> [<diff name>]    # writes <run dir>/<diff name> (default task.diff), prints changed paths
```

The tree IDs are ordinary git tree objects, so `git diff <tree ID> <tree ID> -- <paths>` restricts a diff to the paths of one package.

Coverage is measured with [scripts/coverage.py](scripts/coverage.py), as `resources/tester.md` describes.

## 1. Intake

1. The input is an implementation plan, a change request or a request for a bug fix. Without a plan the user has approved, write one with the `architecting-features` skill and get the user's approval. The approval covers the whole loop, including the fixes the review and test phases request.
2. Every open question in the plan or the change request must be answered by the user before anything else starts. Ask them now, write the answers into the plan, and do not take the baseline while a question is unanswered.
3. Ask the user in one prompt: the model and effort for each role (implementer, reviewer, tester), and whether to print a phase card before every phase or only before every REVIEW and every package's IMPLEMENT. When the newest ledger under `<system temp>/implementing-changes/` records the choices of a previous run, offer them first as the last run's choice. Recommend a reviewer model that differs from the implementer's. Record the answers in the ledger.
4. Create the run directory, take the baseline snapshot and record its tree ID.
5. Run the BASELINE phase. Record the total coverage and the tests that already fail.

When the change already exists as uncommitted work (e.g. a previous session implemented it), the working tree is not the "before" state:

- Use `git rev-parse HEAD^{tree}` as the baseline tree ID, so the diff covers the existing work.
- Run the BASELINE phase in a detached worktree at `HEAD` inside the run directory (`git worktree add --detach <run dir>/baseline-worktree HEAD`), with the worktree rule from `resources/tester.md`. Remove the worktree (`git worktree remove`) after the final report.
- Cut the existing work into packages by the paths it changed, as *2. Work packages* describes, write each package diff with `git diff <baseline tree> <snapshot tree> -- <paths>`, and run every package through *3. Package loop* from step 3 on, without implementing.

## 2. Work packages

Split the plan into work packages and write them into the ledger. A package is:

- one plan phase, work stream or requirement group that can be implemented and tested on its own, of at most about five source files plus their tests, and their documentation, CALM and smoke-suite updates
- ordered so that every package depends only on earlier ones
- described in its own file `<run dir>/packages/P<n>.md` that holds only the plan text of that package, verbatim, plus the few lines of context it needs from earlier packages (e.g. a signature or a model another package introduced)

A bug fix or a small change request is one package. When a plan is too vague to cut, ask the user. When in doubt, cut smaller: a small package keeps every phase's context small.

## 3. Package loop

Run the packages in order. For each package:

1. Take a snapshot and record it as the package's start tree ID.
2. Hand over to the IMPLEMENT phase (phase card) with the package file. Its report goes into the ledger.
3. Verify the package, at most 3 rounds:
   1. Take a snapshot. Write the package diff (`P<n>.diff`) against the package's start tree and, from the second round on, the round diff (`P<n>-round.diff`) against the tree of the previous round. Record the file names and the changed paths in the ledger.
   2. Hand over to the REVIEW phase (phase card): `FULL` mode in the first round and `FOLLOW_UP` mode afterwards, with the package file, the package diff, the round diff, the changed paths and all `SKIPPED` findings of the package with their reasons. Write its report into the ledger.
   3. Run the TEST phase in `VERIFY` mode with the package diff and the baseline test results. Write its report into the ledger.
   4. Record every finding with an ID `P<n>R<round>-<number>`. LOW findings and findings with a confidence below 40 are recorded but never fixed in the loop.
   5. Check every finding answered with `FIXED` in the previous round: if the round diff changes none of the paths it named, the fix is missing, so set the finding back to `OPEN`.
   6. When the review re-raises a `SKIPPED` finding with new evidence, set it back to `OPEN`. If the FIX phase skips it again, mark it `DISPUTED`: it stops blocking and goes to the final report for the user to decide.
   7. If no CRITICAL, HIGH or MEDIUM finding with a confidence of at least 40 is `OPEN` and the test verdict is `PASS`, the package is done: continue with the next one.
   8. Otherwise run the FIX phase with one brief from the ledger: the blocking open findings in `FIX_FINDINGS` mode and, on `FAIL`, the test report in `FIX_TESTS` mode. Every finding is answered with `FIXED`, or with `SKIPPED` and concrete evidence; a skip without evidence is not accepted. Then start the next round.

When a package reaches its round limit, show the user what is still open and ask whether to continue with more rounds, and how many, or to move on and leave the findings for the final report.

## 4. Integration check

After the last package, write the task diff against the baseline tree and run the TEST phase in `VERIFY` mode with the task diff and the baseline test results. This is the only unit test run over the whole task; the packages were reviewed one by one, so no REVIEW phase runs here.

On `FAIL`, run the FIX phase in `FIX_TESTS` mode with the test report, then repeat the check, at most 2 times. When it still fails, show the user the report and ask whether to continue or to stop and write the final report.

The smoke suite, including its A/B comparison, never runs in this loop: it needs the Docker stack and makes billed Gemini calls, so the user runs it manually after the task.

## 5. Final report

Report in the conversation:

- the changed files, the packages and the number of verification rounds of each
- the fixed findings by severity
- every `SKIPPED` and `DISPUTED` finding with the reason
- the LOW findings and the findings with a confidence below 40
- the test result, the changed-line coverage and the total coverage against the baseline
- the plan file, if there is one, for the user to keep or delete, and the run directory
- the steps left for the user:
  - running the smoke suite, including the A/B comparison (*Hermetic smoke suite* in `AGENTS.md`)
  - refreshing the recorded A/B baselines and every baseline refresh the plan asks for, with the capture command in `AGENTS.md`
  - CALM validation, lint, license, security and dependency checks and the other pull request checks, with the `preparing-pull-requests` skill

Never commit, push or open a pull request.
