---
name: prepare-pr
description: Prepares code for a pull request by running linting (ruff), tests, security scans (bandit), and dependency checks (uv audit). Use when ready to create a PR or before committing changes.
---

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
4. Run security scan (bandit) and dependency check (uv audit)
5. Validate the CALM architecture model
6. Analyze changes and update documentation (README, skills)
7. Present changes for user review
8. Commit and push changes
9. Create pull request

## Prerequisites

Ensure installed: `ruff`, `bandit`, `pytest`, `gh` (GitHub CLI), and `node`/`npx` (Node.js 20+, for CALM validation).
Dependency auditing uses `uv audit` (built into uv).

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
# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only
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

#### 4.2: Dependency Vulnerability Check (uv audit)

```powershell
uv audit --preview-features audit-command --no-dev
```

If vulnerabilities found, follow the **Intervention Pattern** with options:

- Update to patched version
- Document in PR if no fix exists
- Accept risk with justification

### Step 5: Validate the CALM Architecture Model

The `Architecture (CALM)` CI job is **blocking**, so run the same validation locally. From the `calm/` directory:

```powershell
npx -y "@finos/calm-cli@1.46.0" validate -p patterns/quaia.pattern.json -a architecture/quaia.arch.json -u url-mapping.json --strict -f pretty
```

A clean run prints `No issues found.` and exits `0`. If it fails because the change added or removed a service, an
integration edge or a security control, update `calm/architecture/quaia.arch.json` (and `calm/patterns/quaia.pattern.json`
when the element is part of the enforced contract), then re-run. For unfixable failures, follow the **Intervention
Pattern**.

### Step 6: Analyze Changes and Update Documentation

#### 6.1: Get Diff Against Main

```powershell
git diff origin/main
```

#### 6.2: Categorize Changes

Review and categorize into: **Features**, **Bug Fixes**, **Refactoring**, **Tests**, **Documentation**, **Dependencies**, **Configuration**.
This analysis feeds both README updates and PR description.

#### 6.3: Update README

Update `README.md` to reflect current code state:

- Update feature descriptions, usage examples, configuration sections
- Add sections for significant new functionality
- Remove outdated information

Only follow the **Intervention Pattern** for complex documentation decisions.

#### 6.4: Update Relevant Skills

Check if changes affect skills in `.agents/skills/` based on their content:

```powershell
Get-ChildItem -Path ".agents/skills" -Directory | Select-Object Name
```

For affected skills, update: **SKILL.md** (workflow steps), **resources/** (templates), **scripts/** (automation), **examples/** (code
patterns).

#### 6.5: Verify Smoke Suite Coverage

The hermetic smoke suite (`tests/smoke/`) is a mandatory layer (see *Hermetic smoke suite* in `AGENTS.md`). From the diff
in 6.2, check whether the change adds a new end-to-end capability or alters what an existing flow produces — a new agent,
a new orchestrator workflow/endpoint, a new external integration, or a change to a flow's output.

If so, confirm the same PR extends `tests/smoke/` (a test in `tests/smoke/test_smoke.py`, plus any fixtures, mocks under
`tests/smoke/mocks/`, or `docker-compose.smoke.yml` service entries it needs). If that coverage is missing, follow the
**Intervention Pattern** before continuing — do not proceed with a PR that adds or extends a flow but leaves the smoke
suite untouched. The suite makes real, billed Gemini calls, so do not run it as part of this skill; it runs in the
`smoke` CI job. A pure internal refactor with no observable end-to-end change is exempt.

### Step 7: Review Changes with User

```powershell
git status
git diff
git diff --cached
```

Present summary:
> "I've made the following changes: [linting fixes], [test fixes], [security fixes], [documentation updates]. Proceeding to commit."

If user requests modifications, apply them and re-run relevant checks.

### Step 8: Commit and Push

```powershell
git add -A
git commit -m "chore: fix linting errors and update code quality"
git push -u origin HEAD
```

Use appropriate commit prefixes: `chore:`, `fix:`, `docs:` for different change types.

### Step 9: Create Pull Request

```powershell
git branch --show-current
gh pr create --title "<short summary>" --body "<detailed description>"
```

**Title**: Use conventional prefixes (`feat:`, `fix:`, `refactor:`, `chore:`, `docs:`), max ~72 chars.

**Body**: Use template 📄 [resources/pr_body_template.md](resources/pr_body_template.md)


## Verification Checklist

- [ ] `ruff check .` and `ruff format . --check` pass
- [ ] All new Python files have SPDX license header
- [ ] `pytest tests/ -v` passes
- [ ] `bandit` has no unaddressed high/medium issues
- [ ] `uv audit` has no unaddressed critical vulnerabilities
- [ ] CALM validation passes (`Architecture (CALM)` gate): `npx -y @finos/calm-cli@1.46.0 validate -p patterns/quaia.pattern.json -a architecture/quaia.arch.json -u url-mapping.json --strict` from `calm/`
- [ ] README.md reflects current code state
- [ ] Smoke suite (`tests/smoke/`) extended if the change adds or extends an end-to-end flow (see *Hermetic smoke suite* in `AGENTS.md`)
- [ ] User has reviewed and approved changes
- [ ] PR has descriptive title and comprehensive description
