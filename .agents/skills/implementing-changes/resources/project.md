# Project: QuAIA

Paths are relative to the repository root.

| Purpose                      | Use                                                                   |
|------------------------------|-----------------------------------------------------------------------|
| Project rules                | `AGENTS.md`, `PYTHON_GUIDELINES.md`                                   |
| Planning                     | `.agents/skills/architecting-features/SKILL.md`                       |
| Review criteria and severity | `.agents/skills/reviewing-pull-requests/resources/review_criteria.md` |
| Writing tests                | `.agents/skills/writing-unit-tests/SKILL.md`                          |
| Fixing failing tests         | `.agents/skills/running-unit-tests/SKILL.md`                          |

## Tests and coverage

Run from the repository root:

```bash
uv run pytest --cov=. --cov-report=xml --cov-report=term --cov-precision=2           # total coverage: the TOTAL line
uvx diff-cover coverage.xml --diff-file <run dir>/task.diff --fail-under=80 --show-uncovered  # changed-line coverage
```

Tests outside the main checkout (e.g. a baseline in a git worktree) must use the main checkout's synced environment.
A fresh environment lacks the optional extras (`rag-sync`, `embedding-service`, ...) and fails with
`ModuleNotFoundError` (e.g. `pymupdf`). Run them from the worktree directory with:

```bash
UV_PROJECT_ENVIRONMENT=<repository root>/.venv uv run --no-sync pytest --cov=. --cov-report=xml --cov-report=term --cov-precision=2
```

Never drop `--no-sync`: it would re-sync the main environment to the worktree's lock file.

The smoke suite is not part of the loop: it needs the `docker-compose.smoke.yml` stack and makes billed LLM calls.

## Left for the user

- Running the smoke suite when the change affects an end-to-end flow (*Hermetic smoke suite* in `AGENTS.md`).
- CALM validation and the other pull request checks, with the `preparing-pull-requests` skill.
