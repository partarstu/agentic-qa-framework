---
name: prepare-pr
description: Prepares code for a pull request by running linting (ruff), tests, security scans (bandit), and dependency checks (pip-audit). Use when ready to create a PR or before committing changes.
---

# Prepare Pull Request

This skill provides a comprehensive workflow to prepare your code for a pull request. It runs all CI checks locally, fixes any issues, and
creates a well-documented pull request.

## ⚠️ CRITICAL: User Intervention Policy

**IMPORTANT**: This workflow should proceed **autonomously** when steps complete successfully. Only stop and involve the user when:

- **Blockers occur**: Unfixable errors, failing tests, security issues that cannot be auto-resolved
- **Manual decisions are needed**: Ambiguous situations where multiple valid approaches exist
- **Approval is required**: Before committing changes or creating the PR

When user intervention IS needed, you MUST:

1. **STOP** the workflow execution immediately
2. **PRESENT** the issue clearly to the user with all relevant context
3. **ASK** the user for the specific action or decision needed
4. **WAIT** for user response before continuing

Do NOT ask for confirmation on routine steps that complete successfully (e.g., linting fixes applied, tests passing).

## Overview

The workflow:

1. Runs linting (ruff) and auto-fixes issues
2. Verifies new files have the required license header
3. Runs unit tests and assists with fixing failures
4. Runs security scan (bandit) and dependency vulnerability check (pip-audit)
5. Analyzes changes against `main` branch and updates README documentation
6. Presents all changes for user review and approval
7. Commits approved changes
8. Creates a clean `temp` branch from `main` with all changes squashed into a single commit
9. Creates a descriptive pull request from the `temp` branch

## Prerequisites

Ensure the following tools are installed:

- `ruff` - Python linter
- `bandit` - Security scanner
- `pip-audit` - Dependency vulnerability checker
- `pytest` - Test runner
- `gh` - GitHub CLI (for creating PRs)

## Step-by-Step Instructions

### Step 1: Run Ruff Linter and Auto-Fix Issues

Run the ruff linter to check for code style and quality issues:

```powershell
# First, check for issues
ruff check . --output-format=github

# Auto-fix all fixable issues
ruff check . --fix

# Also run the formatter
ruff format .
```

If there are unfixable issues that ruff reports:

1. **STOP** and present the issues to the user
2. **ASK** the user how they would like to fix each issue
3. Apply fixes based on user guidance
4. Re-run `ruff check .` until no issues remain

### Step 2: Verify License Headers on New Files

All new Python files must include the SPDX license header at the top. This step identifies new files and ensures they have the required header.

#### 2.1: Identify New Python Files

Find all new Python files added in the current branch compared to `main`:

```powershell
# Fetch latest main branch
git fetch origin main

# List new Python files (Added files only)
git diff --name-only --diff-filter=A origin/main...HEAD -- "*.py"
```

#### 2.2: Check Each File for License Header

For each new `.py` file, verify it starts with the SPDX license header:

```
# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0
```

Check the first few lines of each file:

```powershell
# For each new file, check if it has the license header
# Example: Get-Content -Path "path/to/file.py" -Head 3
```

#### 2.3: Auto-Add Missing License Headers

If any new Python files are missing the license header:

1. **Automatically prepend** the license header to the file
2. The header format is:
   ```python
   # SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
   #
   # SPDX-License-Identifier: Apache-2.0
   ```
3. Add an empty line after the header before any existing content
4. Log which files were updated

**Files to Skip:**
- `__init__.py` files that are empty
- Files in `.venv/`, `node_modules/`, or other dependency directories
- Files that already have the header

If there are issues determining whether a file should have a header (e.g., generated files, third-party code):

1. **STOP** and present the file list to the user
2. **ASK** the user which files should receive the license header
3. Apply headers based on user guidance

### Step 3: Run Unit Tests and Fix Any Failures

Run the complete test suite:

```powershell
pytest tests/ -v
```

If any tests fail:

1. **STOP** and present the failure details to the user
2. Analyze the failure output and explain the likely cause:
    - A bug in the new code → Suggest fixing the code
    - An outdated test → Suggest updating the test
    - Missing test dependencies → Suggest installing them
3. **ASK** the user which approach they prefer
4. Apply fixes based on user guidance
5. Re-run `pytest tests/ -v` until all tests pass

For running tests with coverage (as in CI):

```powershell
pytest tests/ --cov=. --cov-report=term-missing -v
```

### Step 4: Run Security and Dependency Checks

#### 3.1: Run Security Scan (Bandit)

Run the bandit security scanner:

```powershell
bandit -r . -x ./tests,./orchestrator/ui,./.venv -f txt
```

Review any security findings:

- **High severity**: Must be fixed before PR
- **Medium severity**: Should be fixed or explicitly justified
- **Low severity**: Review and fix if reasonable

If any High or Medium severity issues are found:

1. **STOP** and present the findings to the user
2. **ASK** the user how they would like to address each issue
3. Apply fixes or add `# nosec` comments based on user guidance

Common fixes:

- Hardcoded passwords → Use environment variables
- SQL injection risks → Use parameterized queries
- Insecure random → Use `secrets` module instead of `random`

#### 3.2: Run Dependency Vulnerability Check (pip-audit)

Check for known vulnerabilities in dependencies:

```powershell
pip-audit --desc
```

If vulnerabilities are found:

1. **STOP** and present the vulnerabilities to the user
2. **ASK** the user how to proceed:
    - Update to a patched version if available
    - Document in PR description if no fix exists
    - Accept the risk with justification
3. If updating, modify `requirements.txt` and re-run `pip-audit --desc`

### Step 5: Analyze Changes and Update Documentation

This step ensures the README and other documentation accurately reflect the current state of the code.

#### 4.1: Get the Full Diff Against Main Branch

```powershell
# Fetch latest main branch
git fetch origin main

# Get the current branch name
git branch --show-current

# Generate comprehensive diff against main
git diff origin/main...HEAD
```

#### 4.2: Analyze and Categorize Changes

Review the diff thoroughly and categorize all changes into:

| Category          | Description                                | Examples                                |
|-------------------|--------------------------------------------|-----------------------------------------|
| **Features**      | New functionality added                    | New endpoints, new agents, new commands |
| **Bug Fixes**     | Issues that were resolved                  | Error handling fixes, logic corrections |
| **Refactoring**   | Code improvements without behavior changes | Renaming, restructuring, optimization   |
| **Tests**         | New or updated tests                       | Unit tests, integration tests           |
| **Documentation** | README, docstrings, comments               | Updated docs, new examples              |
| **Dependencies**  | Added, removed, or updated packages        | requirements.txt changes                |
| **Configuration** | Changes to config files, CI/CD             | cloudbuild.yaml, ci.yml changes         |

Document this analysis - it will be used for both README updates and PR description.

#### 4.3: Update README Documentation

Based on the analysis, update the README.md to reflect the current state of the code:

1. **Review existing README sections** for accuracy
2. **Update feature descriptions** if new features were added
3. **Update usage examples** if APIs or commands changed
4. **Update configuration sections** if config options changed
5. **Add new sections** for significant new functionality
6. **Remove outdated information** that no longer applies

```powershell
# View current README
cat README.md
```

If README updates are needed:

1. Apply the necessary documentation updates
2. Continue to the next step

**Note**: Only stop and ask the user if there are complex documentation decisions (e.g., major restructuring, unclear how to document a feature).

If no README updates are needed (e.g., only internal refactoring), proceed to the next step.

#### 4.4: Identify and Update Relevant Skills

Review the changes to determine if any existing skills in `.agent/skills/` need to be updated:

```powershell
# List all available skills
Get-ChildItem -Path ".agent/skills" -Directory | Select-Object Name
```

For each skill, consider whether the changes affect:

| Skill Component     | When to Update                                              |
|---------------------|-------------------------------------------------------------|
| **SKILL.md**        | Workflow steps changed, new prerequisites, updated commands |
| **resources/**      | Templates, configuration files, or reference docs changed   |
| **scripts/**        | Helper scripts modified or new automation added             |
| **examples/**       | Code patterns changed, new examples needed                  |

**Skill Update Checklist:**

1. **Review affected skills**: Identify which skills are impacted
2. **Verify skill accuracy**: For each potentially affected skill:
   ```powershell
   # View the skill's main instruction file
   cat ".agent/skills/<skill-name>/SKILL.md"
   
   # Check if skill has supporting directories
   Get-ChildItem -Path ".agent/skills/<skill-name>" -Recurse
   ```

3. **Update skill contents** if needed:
   - Update SKILL.md instructions if workflow steps changed
   - Update resource files if templates or configs changed
   - Update example files if code patterns changed
   - Update scripts if automation logic changed

If no skill updates are needed (e.g., changes don't affect documented patterns), explicitly note this and proceed.

### Step 6: Review All Changes with User

After all checks pass and documentation is updated, show the user all modifications made:

```powershell
# Show summary of changed files
git status

# Show detailed diff of all changes
git diff

# Show diff with staging area if files are already staged
git diff --cached
```

Present a summary of the changes made:

> "I've made the following changes:
> - [List of linting fixes]
> - [List of test fixes, if any]
> - [List of security fixes, if any]
> - [List of documentation updates, if any]
>
> Proceeding to commit these changes."

If the user requests modifications:

1. Apply the requested changes
2. Re-run any relevant checks (linting, tests, etc.)
3. Present the updated changes for approval again

### Step 7: Commit and Push All Changes

After all checks pass, stage, commit, and push all changes:

```powershell
# Stage all changes
git add -A

# Commit with a descriptive message
git commit -m "chore: fix linting errors and update code quality"

# Push the branch to remote (backup before branch manipulation)
git push -u origin HEAD
```

You may need separate commits for different types of changes:

- `chore: fix ruff linting errors` - For pure formatting/linting fixes
- `fix: resolve security issues detected by bandit` - For security fixes
- `chore: update dependencies for security patches` - For dependency updates
- `fix: resolve failing unit tests` - For test fixes
- `docs: update README with latest changes` - For documentation updates

### Step 8: Create Clean Temp Branch with Squashed Changes

This step creates a clean branch from `main` with all your changes squashed into a single commit. This ensures a clean PR history.

#### 7.1: Store Current Branch Name and Create Temp Branch

```powershell
# Store the current branch name for later deletion
$currentBranch = git branch --show-current

# Fetch latest main branch
git fetch origin main

# Create and switch to a new temp branch from main
git checkout -b temp origin/main
```

#### 7.2: Squash Merge All Changes from Current Branch

```powershell
# Squash merge all changes from the original branch
git merge --squash $currentBranch

# Commit with the standard PR preparation message (no description)
git commit -m "PR preparation"
```

#### 7.3: Push Temp Branch and Clean Up

```powershell
# Push the temp branch to remote
git push -u origin temp

# Delete the original branch locally
git branch -D $currentBranch

# Delete the original branch from remote (if it was pushed)
git push origin --delete $currentBranch 2>$null
```

**Note**: From this point forward, all actions will be performed on the `temp` branch. The original branch has been deleted.

### Step 9: Create Pull Request

Using the change analysis from Step 5, create the pull request from the `temp` branch.

#### 8.1: Verify You're on Temp Branch

```powershell
# Confirm current branch is temp
git branch --show-current
```

#### 8.2: Create the Pull Request

Create the PR using GitHub CLI:

```powershell
# Create the PR with title and body
gh pr create --title "<short summary of changes>" --body "<detailed description>"
```

**PR Title Guidelines**:

- Should be a concise summary (max ~72 characters)
- Use conventional commit style prefixes when appropriate:
    - `feat:` for new features
    - `fix:` for bug fixes
    - `refactor:` for code refactoring
    - `chore:` for maintenance tasks
    - `docs:` for documentation updates

**PR Body Template** (use the analysis from Step 4):

📄 **Template:** [resources/pr_body_template.md](resources/pr_body_template.md)

## Troubleshooting

### Ruff Issues

- **Import sorting conflicts**: Run `ruff check . --fix --select I` for import-only fixes
- **Line too long**: Either configure ruff to allow longer lines or refactor the code

### Test Failures

- **Missing fixtures**: Check if pytest plugins are installed (`pytest-asyncio`, etc.)
- **Import errors**: Ensure virtual environment is activated and dependencies installed

### Security Findings

- **False positives**: Add `# nosec` comment with justification if the finding is a false positive
- **Cannot fix**: Document in PR description why the issue cannot be resolved

### PR Creation Fails

- **Not authenticated**: Run `gh auth login` to authenticate with GitHub
- **No upstream branch**: Ensure you push the branch first with `git push -u origin HEAD`
- **Branch behind main**: Rebase with `git rebase origin/main` before creating PR

## Verification Checklist

Before creating the PR, ensure:

- [ ] `ruff check .` returns no errors
- [ ] `ruff format . --check` returns no formatting issues
- [ ] All new Python files have the SPDX license header
- [ ] `pytest tests/ -v` - all tests pass
- [ ] `bandit` - no high/medium security issues (or they're documented)
- [ ] `pip-audit` - no critical vulnerabilities (or they're documented)
- [ ] README.md is up-to-date with current code state
- [ ] User has reviewed and approved all changes
- [ ] All changes are committed with descriptive messages
- [ ] Changes are squashed into temp branch from main
- [ ] Original feature branch is deleted
- [ ] PR title is concise and descriptive
- [ ] PR description includes comprehensive change summary
