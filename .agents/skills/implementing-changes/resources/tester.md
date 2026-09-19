# Tester (BASELINE and TEST phases)

In these phases you run the tests and give a verdict. You do not edit project files: only git-ignored files, such as the coverage report and the test caches, and the run directory are written.

## Commands

Run the commands from the repository root.

Unit tests with coverage (see the `running-unit-tests` skill):

```bash
uv run pytest --cov=. --cov-report=xml
```

`pytest.ini` deselects the smoke tests. pytest-cov erases the coverage data of earlier runs and writes `coverage.xml` also when tests fail, so take the test results from the pytest summary. An error during collection interrupts the run: the test suite itself broke, and the verdict is `FAIL`.

Keep the pytest output out of the context: redirect it to a log file in the run directory and read only the summary, the failure blocks and the coverage script output.

Coverage, after the unit tests, with `<skill dir>` from the ledger:

```bash
uv run --no-project <skill dir>/scripts/coverage.py <repository root>               # total coverage
uv run --no-project <skill dir>/scripts/coverage.py <repository root> <diff file>   # also the coverage of the changed lines
```

The script reads `coverage.xml` and prints the total coverage, the changed-line coverage and the uncovered changed lines. Only the changed source lines count, not the tests or the code templates of the skills. It exits with an error when a changed source file has no coverage data, e.g. because no test imports it.

Reproduce a failing test on its own with the single-test command of the `running-unit-tests` skill, without `--cov`, so that the coverage report stays intact.

Tests outside the main checkout (e.g. a baseline in a git worktree) must use the main checkout's synced environment: a fresh environment lacks the optional extras (`rag-sync`, `embedding-service`, ...) and fails with `ModuleNotFoundError`. Run them from the worktree directory, and pass the worktree directory as the repository root to the coverage script:

```bash
UV_PROJECT_ENVIRONMENT=<repository root>/.venv uv run --no-sync pytest --cov=. --cov-report=xml
```

Never drop `--no-sync`: it would re-sync the main environment to the worktree's lock file.

## BASELINE mode

Run the unit test suite with coverage before the change is made, and measure the total coverage. Report the total coverage and every failing test.

## VERIFY mode

1. Run the unit test suite with coverage.
2. Measure the total and the changed-line coverage with the diff file from the ledger (the package diff, or the task diff in the integration check).
3. Compare the total coverage with the baseline from the ledger.
4. Reproduce every failing test on its own and find its likely cause.

The verdict is `PASS` only when:

- the test run is not interrupted and no test fails, apart from tests that already failed at baseline
- the coverage script succeeds
- at least 80% of the changed lines are covered, or no changed line has coverage data
- the total coverage is not lower than at baseline

Do not fix anything in these phases, and never skip, deselect or weaken tests to reach a verdict.

## Report

Write this report into the ledger at the end of the phase and show it in the conversation. In `BASELINE` mode, report only `TESTS`, `TOTAL COVERAGE` and `FAILING TESTS`.

```
VERDICT: PASS | FAIL
TESTS: <passed> passed, <failed> failed
TOTAL COVERAGE: <x>% (baseline <y>%)
CHANGED-LINE COVERAGE: <x>% | no changed lines with coverage data
FAILING TESTS:
- <test>: <error>; likely cause: <cause>; failed at baseline: yes | no
UNCOVERED CHANGED LINES:
- <path>: <line numbers>
```
