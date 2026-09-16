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

The smoke suite is not part of the loop: it needs the `docker-compose.smoke.yml` stack and makes billed LLM calls.

## Left for the user

- Running the smoke suite when the change affects an end-to-end flow (*Hermetic smoke suite* in `AGENTS.md`).
- CALM validation and the other pull request checks, with the `preparing-pull-requests` skill.
