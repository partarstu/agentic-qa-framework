---
name: pr-review
description: Reviews open pull requests on GitHub by analyzing code changes against project guidelines and Python best practices. Use when reviewing a PR, finding the current branch's PR, or adding inline review comments.
---

// turbo-all

# PR Review

This skill provides a workflow for reviewing pull requests on GitHub. It finds the current branch's PR, analyzes code
changes against project guidelines (GEMINI.md) and Python best practices, and adds inline review comments directly to
the PR.

## ⚠️ User Intervention Policy

Proceed **autonomously** when steps complete successfully. Only stop and involve the user when:

- **No PR found**: The current branch has no open PR
- **API errors**: GitHub API calls fail repeatedly
- **Ambiguous issues**: Code problems with multiple valid interpretations

**Intervention Pattern**:

1. **STOP** execution and **PRESENT** the issue with context
2. **ASK** the user for the specific action needed
3. **WAIT** for response, then continue

## ⚡ Auto-Run Policy

This skill is designed to run with minimal interruption.

- **Always set `SafeToAutoRun: true`** for all `run_command` calls (and other tools).
- **Exceptions:** Only set `SafeToAutoRun: false` if a step specifically instructs you to "Ask" the user, "Wait" for approval, or "Verify" a destructive action before proceeding.
- **Restricted Symbols:** Never use the redirection operator (`>`) or `2>` in commands. Use alternatives (e.g., `Set-Content`, `Out-File`, or ignoring errors explicitly).

## Overview

1. Identify current branch and find its open PR
2. Fetch PR diff and changed files
3. Analyze each file against review criteria
4. Add inline comments to specific lines in GitHub
5. Summarize review findings

## Prerequisites

- GitHub CLI (`gh`) installed and authenticated
- Git repository with remote configured
- Current branch must have an open PR

## Review Criteria

The review uses comprehensive criteria from:

📄 **Criteria Document:** [resources/review_criteria.md](resources/review_criteria.md)

**Key categories:**

- Code style & PEP 8 naming conventions
- Type hints and type safety
- Documentation (docstrings, comments)
- Error handling and exception safety
- Security considerations
- Performance and concurrency
- Code organization and architecture

## Step-by-Step Instructions

### Step 1: Identify Current Branch

```powershell
git branch --show-current
```

Store the branch name for subsequent commands.

### Step 2: Find the Open PR for This Branch

```powershell
gh pr view --json number,title,headRefName,baseRefName,url,state
```

**Expected output:** JSON with PR details including `number`, `title`, `url`, and `state`.

**If no PR exists:** Follow the **Intervention Pattern** - inform the user that no open PR was found for this branch.

**If PR is not in "OPEN" state:** Inform the user and ask whether to proceed with reviewing a merged/closed PR.

### Step 3: Get the Head Commit SHA

The head commit is needed for adding inline comments:

```powershell
gh pr view --json headRefOid --jq ".headRefOid"
```

Store this SHA for use in Step 6.

### Step 4: Fetch PR Diff and Changed Files

#### 4.1: Get List of Changed Files

```powershell
gh pr diff --name-only
```

This returns the list of files modified in the PR.

#### 4.2: Get the Full Diff

```powershell
gh pr diff
```

This returns the unified diff showing all changes. Parse this to understand:

- Which lines were added (`+` prefix)
- Which lines were removed (`-` prefix)
- The line numbers in the new version of each file

### Step 5: Analyze Changed Files

For each changed file (especially `.py` files), use `view_file` to see the full context and analyze against the review
criteria.

**Focus areas:**

1. **New functions/classes**: Check for type hints, docstrings, naming conventions
2. **Modified code**: Verify changes don't introduce issues
3. **Error handling**: Look for bare except blocks, silent failures
4. **Security**: Check for hardcoded secrets, unsanitized inputs
5. **Style**: Verify PEP 8 compliance, code clarity

**For each issue found, record:**

- File path (relative to repo root)
- Line number in the NEW version of the file
- Issue description with severity level
- Suggested fix (if applicable)

### Step 6: Add Inline Review Comments

For each issue found, add an inline comment using the GitHub API:

```powershell
gh api repos/{owner}/{repo}/pulls/{pr_number}/comments `
  -f body="[SEVERITY] Issue description here.

Suggested fix: ..." `
  -f commit_id="{head_commit_sha}" `
  -f path="{file_path}" `
  -F line={line_number} `
  -f side="RIGHT"
```

**Parameter details:**

| Parameter   | Description                                                  |
|-------------|--------------------------------------------------------------|
| `body`      | Comment text with severity prefix (see criteria doc)         |
| `commit_id` | Head commit SHA from Step 3                                  |
| `path`      | File path relative to repo root (e.g., `agents/foo/main.py`) |
| `line`      | Line number in the NEW version of the file                   |
| `side`      | `RIGHT` for new code, `LEFT` for old code (use `RIGHT`)      |

**Severity prefixes:**

- `[CRITICAL]` - Must fix before merge
- `[MAJOR]` - Should fix
- `[MINOR]` - Nice to fix
- `[SUGGESTION]` - Optional improvement
- `[QUESTION]` - Request for clarification

**Example:**

```powershell
gh api repos/partarstu/agentic-qa-framework/pulls/42/comments `
  -f body="[MAJOR] Missing type hints for function parameters.

Add type hints to improve code clarity:
``python
def process_data(items: list[str], limit: int | None = None) -> dict[str, int]:
``" `
  -f commit_id="abc123def456" `
  -f path="agents/test_agent/main.py" `
  -F line=25 `
  -f side="RIGHT"
```

### Step 7: Add Review Summary Comment

After adding inline comments, add a summary comment to the PR:

```powershell
gh pr comment --body "## 📝 Code Review Summary

**Files reviewed:** {count}
**Issues found:** {count}

### Breakdown by Severity
- 🔴 Critical: {count}
- 🟠 Major: {count}
- 🟡 Minor: {count}
- 💡 Suggestions: {count}

### Key Findings
{summary of main issues}

---
*Review based on project guidelines (GEMINI.md) and Python best practices.*"
```

### Step 8: Report to User

Present a summary to the user:

> "I've completed the PR review for PR #{number}: {title}
>
> - **Files reviewed:** {count}
> - **Comments added:** {count}
> - **Critical issues:** {count}
>
> View the PR: {url}"

## Handling Special Cases

### Multi-line Comments

For issues spanning multiple lines, use `start_line` and `start_side`:

```powershell
gh api repos/{owner}/{repo}/pulls/{pr_number}/comments `
  -f body="[MAJOR] This block needs refactoring..." `
  -f commit_id="{sha}" `
  -f path="{path}" `
  -F start_line={start} `
  -f start_side="RIGHT" `
  -F line={end} `
  -f side="RIGHT"
```

### Files Not in Diff

You can only comment on lines that are part of the PR diff. If an issue exists in unchanged code:

1. Note it in the summary comment instead
2. Or suggest the author make a small change to bring the line into the diff

### Binary or Non-Python Files

- Skip binary files
- For config files (YAML, TOML, JSON), check for snake_case keys
- For Dockerfiles, check for best practices (multi-stage builds, security)

## Verification Checklist

- [ ] Current branch identified
- [ ] Open PR found for this branch
- [ ] Head commit SHA retrieved
- [ ] PR diff fetched and parsed
- [ ] Changed Python files analyzed against criteria
- [ ] Inline comments added for issues found
- [ ] Summary comment posted to PR
- [ ] User informed of review completion

## Quick Reference: Getting Repo Owner/Name

```powershell
# Get the remote URL and parse owner/repo
gh repo view --json owner,name --jq '"\(.owner.login)/\(.name)"'
```

This returns the `owner/repo` format needed for API calls.
