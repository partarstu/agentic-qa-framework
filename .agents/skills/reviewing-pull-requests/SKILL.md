---
name: reviewing-pull-requests
description: Reviews a GitHub pull request of the QuAIA repository against AGENTS.md, PYTHON_GUIDELINES.md and the project review criteria, then posts the findings as a single GitHub review with inline comments once the user approves. Use when the user asks to review a PR, either by number or the PR of the current branch.
---

# Reviewing Pull Requests

Requires the GitHub CLI (`gh`), authenticated for the repository.

Copy this checklist and track progress:

```
- [ ] 1. Identify the PR
- [ ] 2. Collect the diff and file contents
- [ ] 3. Analyse against the criteria
- [ ] 4. Present the findings and get approval
- [ ] 5. Post one review
```

## 1. Identify the PR

Use the PR number the user gave; without one, `gh` resolves the current branch's PR:

```bash
gh pr view <number> --json number,title,url,state,baseRefName,headRefOid
gh repo view --json nameWithOwner --jq .nameWithOwner
```

If there is no PR, tell the user and stop. If its state is not `OPEN`, ask whether to continue.

## 2. Collect the diff and file contents

```bash
gh pr diff <number> --name-only
gh pr diff <number>
git fetch origin pull/<number>/head
git show FETCH_HEAD:<path>
```

Read the full new version of each changed file with `git show`, not only the diff hunks. Do not check out the PR
branch: the working tree may hold uncommitted work.

## 3. Analyse against the criteria

Apply [resources/review_criteria.md](resources/review_criteria.md). For each finding record the file path, the line in
the new version of the file, the severity, the problem and a suggested fix.

- Inline comments are only possible on lines inside a diff hunk. Report issues in untouched code in the review body.
- Confirm every finding against the code before keeping it; drop speculative ones.
- Also check what the PR is missing: tests, CALM model update, smoke-suite update, README or skill updates.

## 4. Present the findings and get approval

Show the findings to the user grouped by severity, together with the proposed review body and event: `COMMENT` by
default, `REQUEST_CHANGES` only if the user agrees. Posting notifies the PR author, so ask for approval and wait.

## 5. Post one review

Write the review as JSON to a temporary file outside the repository:

```json
{
  "commit_id": "<headRefOid>",
  "event": "COMMENT",
  "body": "## Review summary\n\nFiles reviewed: <n> | Critical: <n> | High: <n> | Medium: <n> | Low: <n>\n\n<Key findings and issues outside the diff>",
  "comments": [
    {"path": "agents/foo/main.py", "line": 25, "side": "RIGHT", "body": "[HIGH] <problem>\n\nSuggested fix: <fix>"},
    {"path": "common/models.py", "start_line": 10, "start_side": "RIGHT", "line": 14, "side": "RIGHT", "body": "[LOW] <problem>"}
  ]
}
```

Post it in a single call, which sends one notification and avoids GitHub's secondary rate limits for rapid comments:

```bash
gh api repos/<owner>/<repo>/pulls/<number>/reviews --method POST --input <path to review JSON>
```

If GitHub rejects the review with `422` because a comment line is outside the diff, move that finding into the review
body and post again. Finish by giving the user the PR URL and the finding counts.
