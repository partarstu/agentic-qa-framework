---
name: Prepare PR
description: Comprehensive workflow to run all CI checks, fix issues, and create a pull request with automated analysis
---

# Prepare Pull Request

This skill provides a comprehensive workflow to prepare your code for a pull request. It runs all CI checks locally, fixes any issues, and creates a well-documented pull request.

## Overview

The workflow:
1. Runs linting (ruff) and auto-fixes issues
2. Runs unit tests and assists with fixing failures
3. Runs security scan (bandit) and reviews findings
4. Runs dependency vulnerability check (pip-audit)
5. Presents all changes for user review and approval
6. Commits approved changes
7. Analyzes all changes against `main` branch and creates a descriptive PR

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

If there are unfixable issues that ruff reports, manually analyze and fix them. Re-run `ruff check .` until no issues remain.

### Step 2: Run Unit Tests and Fix Any Failures

Run the complete test suite:

```powershell
pytest tests/ -v
```

If any tests fail:
1. Analyze the failure output carefully
2. Determine if the failure is due to:
   - A bug in the new code → Fix the code
   - An outdated test → Update the test
   - Missing test dependencies → Install them
3. Re-run `pytest tests/ -v` until all tests pass

For running tests with coverage (as in CI):

```powershell
pytest tests/ --cov=. --cov-report=term-missing -v
```

### Step 3: Run Security Scan (Bandit)

Run the bandit security scanner:

```powershell
bandit -r . -x ./tests,./orchestrator/ui,./.venv -f txt
```

Review any security findings:
- **High severity**: Must be fixed before PR
- **Medium severity**: Should be fixed or explicitly justified
- **Low severity**: Review and fix if reasonable

Common fixes:
- Hardcoded passwords → Use environment variables
- SQL injection risks → Use parameterized queries
- Insecure random → Use `secrets` module instead of `random`

### Step 4: Run Dependency Vulnerability Check (pip-audit)

Check for known vulnerabilities in dependencies:

```powershell
pip-audit --desc
```

If vulnerabilities are found:
1. Check if a newer version of the package fixes the issue
2. Update `requirements.txt` with the patched version
3. Re-run `pip-audit --desc` to verify the fix

Note: Some vulnerabilities may not have fixes available yet. Document these in the PR description if they cannot be resolved.

### Step 5: Review All Changes with User

After all checks pass, show the user all modifications made:

```powershell
# Show summary of changed files
git status

# Show detailed diff of all changes
git diff

# Show diff with staging area if files are already staged
git diff --cached
```

**Important**: Present the changes to the user and explicitly ask for their approval before proceeding:

> "I've made the following changes to fix linting and test issues. Please review them and confirm if you'd like me to commit these changes."

Wait for explicit user confirmation before proceeding to the next step. If the user requests modifications, make them and re-run the relevant checks.

### Step 6: Commit All Approved Changes

After user approval, stage and commit all changes:

```powershell
# Stage all changes
git add -A

# Commit with a descriptive message
git commit -m "chore: fix linting errors and update code quality"
```

You may need separate commits for different types of changes:
- `chore: fix ruff linting errors` - For pure formatting/linting fixes
- `fix: resolve security issues detected by bandit` - For security fixes
- `chore: update dependencies for security patches` - For dependency updates
- `fix: resolve failing unit tests` - For test fixes

### Step 7: Analyze Changes and Create Pull Request

#### 7.1: Get the Full Diff Against Main Branch

```powershell
# Fetch latest main branch
git fetch origin main

# Get the current branch name
git branch --show-current

# Generate comprehensive diff against main
git diff origin/main...HEAD
```

#### 7.2: Analyze the Changes

Review the diff and categorize changes:
- **New features**: New functionality added
- **Bug fixes**: Issues that were resolved
- **Refactoring**: Code improvements without behavior changes
- **Tests**: New or updated tests
- **Documentation**: README, docstrings, comments
- **Dependencies**: Added, removed, or updated packages
- **Configuration**: Changes to config files, CI/CD, etc.

#### 7.3: Create the Pull Request

Create the PR using GitHub CLI:

```powershell
# Push the branch to remote first
git push -u origin HEAD

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

**PR Body Template**:

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

### Other
- <Any other changes>

## Files Changed

<List of key files modified with brief explanations>

## Testing

- [ ] All unit tests pass
- [ ] Linting passes (ruff)
- [ ] Security scan reviewed (bandit)
- [ ] Dependency vulnerabilities checked (pip-audit)

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

# Step 3: Security scan
bandit -r . -x ./tests,./orchestrator/ui,./.venv -f txt

# Step 4: Dependency check
pip-audit --desc

# Step 5: Review changes
git status
git diff

# Step 6: Commit (after user approval)
git add -A
git commit -m "chore: fix code quality issues"

# Step 7: Create PR
git fetch origin main
git push -u origin HEAD
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
- [ ] User has reviewed and approved all changes
- [ ] All changes are committed with descriptive messages
- [ ] PR title is concise and descriptive
- [ ] PR description includes comprehensive change summary
