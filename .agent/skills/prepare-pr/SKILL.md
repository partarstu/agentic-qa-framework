---
name: Prepare PR
description: Comprehensive workflow to run all CI checks, fix issues, and create a pull request with automated analysis
---

# Prepare Pull Request

This skill provides a comprehensive workflow to prepare your code for a pull request. It runs all CI checks locally, fixes any issues, and creates a well-documented pull request.

## ⚠️ CRITICAL: User Intervention Policy

**IMPORTANT**: If at ANY step during this workflow user intervention is required (e.g., manual fixes needed, decisions to be made, approval required), you MUST:

1. **STOP** the workflow execution immediately
2. **PRESENT** the issue clearly to the user with all relevant context
3. **ASK** the user for the specific action or decision needed
4. **WAIT** for user response before continuing

Never proceed autonomously when user input is required. This ensures the user maintains full control over all changes.

## Overview

The workflow:
1. Runs linting (ruff) and auto-fixes issues
2. Runs unit tests and assists with fixing failures
3. Runs security scan (bandit) and dependency vulnerability check (pip-audit)
4. Analyzes changes against `main` branch and updates README documentation
5. Presents all changes for user review and approval
6. Commits approved changes
7. Creates a clean `temp` branch from `main` with all changes squashed into a single commit
8. Creates a descriptive pull request from the `temp` branch

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

### Step 2: Run Unit Tests and Fix Any Failures

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

### Step 3: Run Security and Dependency Checks

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

### Step 4: Analyze Changes and Update Documentation

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

| Category | Description | Examples |
|----------|-------------|----------|
| **Features** | New functionality added | New endpoints, new agents, new commands |
| **Bug Fixes** | Issues that were resolved | Error handling fixes, logic corrections |
| **Refactoring** | Code improvements without behavior changes | Renaming, restructuring, optimization |
| **Tests** | New or updated tests | Unit tests, integration tests |
| **Documentation** | README, docstrings, comments | Updated docs, new examples |
| **Dependencies** | Added, removed, or updated packages | requirements.txt changes |
| **Configuration** | Changes to config files, CI/CD | cloudbuild.yaml, ci.yml changes |

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
1. **PRESENT** the proposed changes to the user
2. **ASK** the user to confirm the documentation updates
3. Apply the approved changes

If no README updates are needed (e.g., only internal refactoring), explicitly note this and proceed.

### Step 5: Review All Changes with User

After all checks pass and documentation is updated, show the user all modifications made:

```powershell
# Show summary of changed files
git status

# Show detailed diff of all changes
git diff

# Show diff with staging area if files are already staged
git diff --cached
```

**MANDATORY**: Present the changes to the user and explicitly ask for their approval:

> "I've made the following changes:
> - [List of linting fixes]
> - [List of test fixes, if any]
> - [List of security fixes, if any]
> - [List of documentation updates, if any]
>
> Please review these changes and confirm if you'd like me to commit them. If you want any modifications, please let me know."

**WAIT** for explicit user confirmation before proceeding to the next step. 

If the user requests modifications:
1. Apply the requested changes
2. Re-run any relevant checks (linting, tests, etc.)
3. Present the updated changes for approval again

### Step 6: Commit and Push All Approved Changes

After user approval, stage, commit, and push all changes:

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

### Step 7: Create Clean Temp Branch with Squashed Changes

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

### Step 8: Create Pull Request

Using the change analysis from Step 4, create the pull request from the `temp` branch.

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

```markdown
## Summary

<Brief overview of what this PR accomplishes>

## Changes

### Features
- <List of new features, if any>

### Bug Fixes
- <List of bug fixes, if any>

### Refactoring
- <List of code improvements, if any>

### Tests
- <List of test changes, if any>

### Documentation
- <List of documentation updates, if any>

### Other
- <Any other changes>

## Testing
- [x] All unit tests pass
- [x] Linting passes (ruff)
- [x] Security scan reviewed (bandit)
- [x] Dependency vulnerabilities checked (pip-audit)

## Notes

<Any additional context, breaking changes, or follow-up work needed>
```

## Complete Example Workflow

Here's a complete example of running this workflow:

```powershell
# Step 1: Lint and auto-fix
ruff check . --fix
ruff format .
ruff check .  # Verify no remaining issues

# Step 2: Run tests
pytest tests/ -v

# Step 3: Security and dependency checks
bandit -r . -x ./tests,./orchestrator/ui,./.venv -f txt
pip-audit --desc

# Step 4: Analyze changes and update docs
git fetch origin main
git diff origin/main...HEAD
# Update README.md if needed

# Step 5: Review changes (STOP and ask user)
git status
git diff

# Step 6: Commit and push (ONLY after user approval)
git add -A
git commit -m "chore: fix code quality issues"
git push -u origin HEAD

# Step 7: Create temp branch with squashed changes
$currentBranch = git branch --show-current
git fetch origin main
git checkout -b temp origin/main
git merge --squash $currentBranch
git commit -m "PR preparation"
git push -u origin temp
git branch -D $currentBranch
git push origin --delete $currentBranch 2>$null

# Step 8: Create PR (from temp branch)
gh pr create --title "feat: add new feature X" --body "## Summary\n\nAdded feature X...\n\n## Changes\n\n- Added X\n- Fixed Y\n\n## Testing\n\n- [x] All tests pass"
```

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
