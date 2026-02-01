---
name: prepare-pr
description: Prepares code for a pull request by running linting (ruff), tests, security scans (bandit), and dependency checks (pip-audit). Use when ready to create a PR or before committing changes.
---

// turbo-all

# Prepare Pull Request

This skill provides a comprehensive workflow to prepare your code for a pull request. It runs all CI checks locally, fixes any issues, and
creates a well-documented pull request.

## ⚠️ User Intervention Policy

Proceed **autonomously** when steps complete successfully. Only stop and involve the user when:

- **Blockers occur**: Unfixable errors, failing tests, unresolvable security issues
- **Manual decisions are needed**: Ambiguous situations with multiple valid approaches
- **Approval is required**: Before committing or creating the PR

**Intervention Pattern** (referenced throughout this document):

1. **STOP** execution and **PRESENT** the issue with context
2. **ASK** the user for the specific action needed
3. **WAIT** for response, then apply guidance and re-run checks until passing

## ⚡ Auto-Run Policy

This skill is designed to run with minimal interruption.

- **Always set `SafeToAutoRun: true`** for all `run_command` calls.
- **Exceptions:** Only set `SafeToAutoRun: false` if a step specifically instructs you to "Ask" the user, "Wait" for approval, or "Verify" a destructive action before proceeding (e.g., Step 6: Review Changes with User).
- **Restricted Symbols:** Never use the redirection operator (`>`) or `2>` in commands. Use alternatives (e.g., `Set-Content`, `Out-File`, or ignoring errors explicitly).

## Overview

1. Run linting (ruff) and auto-fix issues
2. Verify new files have SPDX license headers
3. Run unit tests and fix failures
4. Run security scan (bandit) and dependency check (pip-audit)
5. Analyze changes and update documentation (README, skills)
6. Present changes for user review
7. Commit and push changes
8. Create clean `temp` branch from `main` with squashed changes
9. Create pull request

## Prerequisites

Ensure installed: `ruff`, `bandit`, `pip-audit`, `pytest`, `gh` (GitHub CLI)

## Step-by-Step Instructions

### Step 1: Run Ruff Linter

```powershell
ruff check . --output-format=github
ruff check . --fix
ruff format .
```

If unfixable issues remain, follow the **Intervention Pattern**.

### Step 2: Verify License Headers

All new Python files must include the SPDX license header.

#### 2.1: Find New Python Files

```powershell
git fetch origin main
git diff --name-only --diff-filter=A origin/main -- "*.py"
```

#### 2.2: Check and Add Missing Headers

For each new `.py` file, verify it starts with:

```python
# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0
```

**Auto-add** the header (with trailing blank line) to files missing it. Log which files were updated.

**Skip**: Empty `__init__.py`, files in `.venv/`/`node_modules/`, files with existing headers.

For unclear cases (generated files, third-party code), follow the **Intervention Pattern**.

### Step 3: Run Unit Tests

```powershell
pytest tests/ -v
```

If tests fail, analyze the output and follow the **Intervention Pattern** with suggestions:

- Bug in new code → Fix the code
- Outdated test → Update the test
- Missing dependencies → Install them

For coverage (as in CI): `pytest tests/ --cov=. --cov-report=term-missing -v`

### Step 4: Run Security and Dependency Checks

#### 4.1: Security Scan (Bandit)

```powershell
bandit -r . -x "./tests,./orchestrator/ui,./.venv" -f txt
```

- **High/Medium severity**: Follow the **Intervention Pattern**
- **Low severity**: Fix if reasonable

Common fixes: Use env vars for secrets, parameterized queries for SQL, `secrets` module instead of `random`.

#### 4.2: Dependency Vulnerability Check (pip-audit)

```powershell
pip-audit --desc
```

If vulnerabilities found, follow the **Intervention Pattern** with options:

- Update to patched version
- Document in PR if no fix exists
- Accept risk with justification

### Step 5: Analyze Changes and Update Documentation

#### 5.1: Get Diff Against Main

```powershell
git diff origin/main
```

#### 5.2: Categorize Changes

Review and categorize into: **Features**, **Bug Fixes**, **Refactoring**, **Tests**, **Documentation**, **Dependencies**, **Configuration**.
This analysis feeds both README updates and PR description.

#### 5.3: Update README

Update `README.md` to reflect current code state:

- Update feature descriptions, usage examples, configuration sections
- Add sections for significant new functionality
- Remove outdated information

Only follow the **Intervention Pattern** for complex documentation decisions.

#### 5.4: Update Relevant Skills

Check if changes affect skills in `.agent/skills/` based on their content:

```powershell
Get-ChildItem -Path ".agent/skills" -Directory | Select-Object Name
```

For affected skills, update: **SKILL.md** (workflow steps), **resources/** (templates), **scripts/** (automation), **examples/** (code
patterns).

### Step 6: Review Changes with User

```powershell
git status
git diff
git diff --cached
```

Present summary:
> "I've made the following changes: [linting fixes], [test fixes], [security fixes], [documentation updates]. Proceeding to commit."

If user requests modifications, apply them and re-run relevant checks.

### Step 7: Commit and Push

```powershell
git add -A
git commit -m "chore: fix linting errors and update code quality"
git push -u origin HEAD
```

Use appropriate commit prefixes: `chore:`, `fix:`, `docs:` for different change types.

### Step 8: Create Clean Temp Branch

#### 8.1: Store Branch and Create Temp

```powershell
$currentBranch = git branch --show-current
git fetch origin main
git checkout -b temp origin/main
```

#### 8.2: Squash Merge and Push

```powershell
git merge --squash $currentBranch
git commit -m "PR preparation"
git push -u origin temp
```

#### 8.3: Clean Up Original Branch

```powershell
git branch -D $currentBranch
git push origin --delete $currentBranch
```


### Step 9: Create Pull Request

```powershell
git branch --show-current  # Verify on temp branch
gh pr create --title "<short summary>" --body "<detailed description>"
```

**Title**: Use conventional prefixes (`feat:`, `fix:`, `refactor:`, `chore:`, `docs:`), max ~72 chars.

**Body**: Use template 📄 [resources/pr_body_template.md](resources/pr_body_template.md)


## Verification Checklist

- [ ] `ruff check .` and `ruff format . --check` pass
- [ ] All new Python files have SPDX license header
- [ ] `pytest tests/ -v` passes
- [ ] `bandit` has no unaddressed high/medium issues
- [ ] `pip-audit` has no unaddressed critical vulnerabilities
- [ ] README.md reflects current code state
- [ ] User has reviewed and approved changes
- [ ] Changes squashed into temp branch, original branch deleted
- [ ] PR has descriptive title and comprehensive description
