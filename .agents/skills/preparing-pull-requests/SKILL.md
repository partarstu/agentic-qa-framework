---
name: preparing-pull-requests
description: Prepares the current branch of the QuAIA repository for a pull request by running the CI checks locally (ruff, pytest, bandit, uv audit, CALM validation), checking compliance with PYTHON_GUIDELINES.md, license headers, documentation and smoke-suite coverage, then committing, pushing and opening the PR once the user approves. Use when the user wants to open a PR or get a branch ready for review.
---

# Preparing Pull Requests

The checks mirror `.github/workflows/ci.yml`. Run commands from the repository root unless noted.

Commits, pushes and pull requests are visible to others: perform them only after the user explicitly approves them in step 8.

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

Fix and format only files in scope; formatting the whole repository rewrites code this change does not touch. The final `ruff check .` is the CI gate and must pass. Fix remaining findings by hand and ask the user only when a fix would change behaviour.

ruff enforces only part of `PYTHON_GUIDELINES.md`. Read the changed Python code against the whole document and fix violations in the lines this change touches; report the ones whose fix would change behaviour to the user.

Check every docstring and comment in scope against the *Comments and docstrings* rule of `AGENTS.md` and compact the ones that violate it (a function docstring longer than one sentence, a class or module docstring longer than two, `Args`/`Returns` that repeat names and types outside LLM tools, a comment that restates the code or records history).

## 3. License headers

New `.py` files must start with the SPDX header that existing files use (copy the first three lines of `config.py`). Add it where missing, except for empty `__init__.py` files. Ask the user about generated or third-party code.

## 4. Unit tests

```bash
uv run pytest --cov=. --cov-report=term-missing
```

If tests fail, fix them with the `running-unit-tests` skill before continuing.

## 5. Security and dependency checks

```bash
uv run bandit -r . -x "./tests,./orchestrator/ui,./.venv,./.uv-cache" -f txt
uv audit --preview-features audit-command --frozen --no-dev
```

- **bandit**: fix high and medium findings in files in scope, or present them to the user with a proposed fix. Fix low findings when the fix is trivial. Findings in untouched files are reported, not fixed.
- **uv audit**: for a vulnerable package, propose upgrading to a fixed version. If none exists, ask the user and note the vulnerability in the PR description.

## 6. CALM validation

From the `calm/` directory:

```bash
npx -y "@finos/calm-cli@1.46.0" validate -p patterns/quaia.pattern.json -a architecture/quaia.arch.json -u url-mapping.json --strict -f pretty
```

It must print `No issues found.` If the change added, removed or renamed a service, integration edge or security control without updating `calm/architecture/quaia.arch.json` (and the pattern when enforced), the branch violates *Architecture first* in `AGENTS.md`: stop and tell the user, because the architecture has to be modelled, validated and approved before such a change is implemented, and a CALM update bolted on now does not count. When the plan of the change exists, its *Architecture* section must carry the line `CALM updated, validated and approved by the user on <date>`.

## 7. Documentation, skills and smoke coverage

Compare the scope from step 1 with:

- **`README.md`**: sections describing changed endpoints, environment variables, setup or features. Remove statements that are no longer true.
- **Versions**: for every agent and the orchestrator whose logic the branch alters (prompts, tools, workflow, routing, output content, integration behaviour), the `VERSION` default in `config.py` and the README *Environment Variables* block is bumped at the level *Versioning of agents and the orchestrator* in `AGENTS.md` prescribes. Add a missing bump and list every bump in the PR description.
- **Skills in `.agents/skills/`**: any instruction, template or referenced code path the change made inaccurate.
- **Smoke suite**: a new agent, endpoint or integration, or changed agent output, must be covered in `tests/smoke/` by this branch, including a refreshed A/B baseline when outputs changed intentionally. If coverage is missing, stop and tell the user. Do not run the smoke suite unless the user asks: it needs the docker-compose stack and makes billed LLM calls, and CI runs it on the PR. A pure refactor needs no smoke change; say so explicitly.

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
- Use Conventional Commits types (`feat`, `fix`, `refactor`, `test`, `docs`, `chore`); keep the title under 72 characters.
- Write the description from [resources/pr_body_template.md](resources/pr_body_template.md) into a temporary file outside the repository and pass it with `--body-file`; multi-line `--body` arguments break in some shells.
- Report the PR URL to the user.
