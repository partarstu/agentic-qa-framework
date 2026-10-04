---
name: preparing-pull-requests
description: Prepares the current branch of the QuAIA repository for a pull request by running the CI checks locally (ruff, pytest, bandit, uv audit, CALM validation), checking compliance with PYTHON_GUIDELINES.md, license headers, documentation and smoke-suite coverage, then committing, pushing and opening the PR once the user approves. Use when the user wants to open a PR or get a branch ready for review.
---

# Preparing Pull Requests

The checks mirror `.github/workflows/ci.yml`. Commits, pushes and pull requests happen only after the user approves them in step 8.

Copy this checklist and track progress:

```
- [ ] 1. Determine the scope
- [ ] 2. Lint, format and Python guidelines
- [ ] 3. License headers
- [ ] 4. Unit tests
- [ ] 5. Security and dependency checks
- [ ] 6. CALM validation
- [ ] 7. Documentation, skills and smoke coverage
- [ ] 8. Review with the user and get approval
- [ ] 9. Commit, push and open the PR
```

## 1. Determine the scope

If the current branch is `main`, stop and ask the user to create a feature branch.

```bash
git fetch origin main
git diff --name-only $(git merge-base origin/main HEAD)
git ls-files --others --exclude-standard
```

The union of both lists (committed, uncommitted and untracked changes) is the scope of every following step. Ask the user about untracked files that look unrelated to the change.

## 2. Lint, format and Python guidelines

```bash
uv run ruff check --fix <changed .py files>
uv run ruff format <changed .py files>
uv run ruff check .
```

Fix and format only files in scope; formatting the whole repository rewrites code this change does not touch. The final `ruff check .` must pass. Fix remaining findings by hand and ask the user only when a fix would change behaviour.

ruff enforces only part of `PYTHON_GUIDELINES.md`. Read the changed Python code against the whole document and fix violations in the lines this change touches; report the ones whose fix would change behaviour to the user. Compact every docstring and comment in those lines that violates *Comments and docstrings* in `AGENTS.md`.

## 3. License headers

Add the SPDX header (*Project conventions* in `AGENTS.md`) to new `.py` files in scope that lack it. Ask the user about generated or third-party code.

## 4. Unit tests

Run the unit tests with coverage (*Commands* in `AGENTS.md`). If tests fail, fix them with the `running-unit-tests` skill before continuing.

## 5. Security and dependency checks

```bash
uv run bandit -r . -x "./tests,./orchestrator/ui,./.venv,./.uv-cache" -f txt
uv audit --preview-features audit-command --frozen --no-dev
```

- **bandit**: fix high and medium findings in files in scope, or present them to the user with a proposed fix. Fix low findings when the fix is trivial. Findings in untouched files are reported, not fixed.
- **uv audit**: for a vulnerable package, propose upgrading to a fixed version. If none exists, ask the user and note the vulnerability in the PR description.

## 6. CALM validation

Validate `calm/` (*Commands* in `AGENTS.md`). Then stop and tell the user when the branch contains an architecture change (*Architecture first (CALM)* in `AGENTS.md`) without the matching CALM update, or without the approval line in its plan, or when the CALM update differs from the elements the plan's *Architecture* section lists.

## 7. Documentation, skills and smoke coverage

Compare the scope from step 1 with:

- **`README.md`**: sections describing changed endpoints, environment variables, setup or features. Remove statements that are no longer true.
- **Versions**: every bump *Versioning* in `AGENTS.md` requires for the branch. Add a missing bump and list every bump in the PR description.
- **Skills in `.agents/skills/` and `AGENTS.md`**: any instruction, template or referenced code path the change made inaccurate.
- **Smoke suite**: the coverage *Smoke suite* in `AGENTS.md` requires for the branch. If it is missing, stop and tell the user.

## 8. Review with the user and get approval

Present:

- the result of every check (pass, fixed, or open issue)
- the files this skill changed (lint fixes, headers, documentation)
- the proposed commit message, PR title and PR description

Ask for explicit approval to commit, push and create the PR, then wait. Apply requested changes and re-run the affected checks.

## 9. Commit, push and open the PR

Only after approval:

```bash
git add <files in scope>
git commit -m "<type>: <summary>"
git push -u origin HEAD
gh pr create --base main --title "<type>: <summary>" --body-file <path to PR description file>
```

- Stage files by name; `git add -A` also picks up unrelated local files.
- Write the description from [resources/pr_body_template.md](resources/pr_body_template.md) into a temporary file and pass it with `--body-file`; multi-line `--body` arguments break in some shells.
- Report the PR URL to the user.
