# Reviewer (REVIEW phase)

In this phase you review the code changed in the package and report findings. You do not edit project files. Judge the code as it is: read the changed files fresh, and do not rely on any memory of writing them or on earlier reviews. Ideally this phase runs right after `/clear`, so that no such memory exists.

## Inputs (from the ledger)

- the package file with the plan text that the changes implement
- the mode: `FULL` in the first round of the package, `FOLLOW_UP` in every later round
- the package diff file with all changes of the package, and the changed paths
- in `FOLLOW_UP` mode, the round diff file with the changes since the previous round
- earlier findings of the package that were skipped in the FIX phase, with their reasons

## Review

1. Read `PYTHON_GUIDELINES.md` and the review criteria in `.agents/skills/reviewing-pull-requests/resources/review_criteria.md`. `AGENTS.md` is already in your context.
2. Read the full current version of every changed file, not only the diff. Read the code the changes call or affect with Grep and ranged reads (offset and limit), only as far as a finding needs it: every turn re-reads everything you have read so far.
3. Compare the changes with the package: requirements missing, built differently, or work the package does not ask for.
4. Apply the review criteria to every changed line. Keep going after the first finding.
5. Confirm each finding against the code and drop speculative ones. Report problems in unchanged code only when the changes cause or worsen them.
6. Raise a skipped finding again only with evidence that refutes the skip reason, and name its ID.

In `FOLLOW_UP` mode, review the whole package diff, but report new MEDIUM and LOW findings only on lines the round diff changes. CRITICAL and HIGH findings and re-raised skipped findings count anywhere in the package diff. Without this rule every fresh review finds new minor issues in code that has not changed since the last round, and the loop does not end.

Rate each finding CRITICAL, HIGH, MEDIUM or LOW as the review criteria define them, by impact rather than by the effort of the fix. Where the intent of the code is unclear, rate the finding by the risk it carries, as the review criteria say, instead of asking the user.

Score your confidence that each finding is real:

| Score | Meaning                                                                                        |
|-------|------------------------------------------------------------------------------------------------|
| 0     | A false positive that does not stand up to light scrutiny, or a pre-existing issue             |
| 25    | Might be real, but you could not verify it                                                     |
| 50    | Verified, but a nitpick or rare in practice                                                    |
| 75    | Verified and very likely to be hit in practice, or a violation of a rule the finding cites     |
| 100   | Verified and certain: the evidence confirms it directly                                        |

## Report

Write this report into the ledger at the end of the phase and show it in the conversation, one block per finding:

```
FINDINGS: <total> (CRITICAL <n>, HIGH <n>, MEDIUM <n>, LOW <n>)

### [<SEVERITY>] <title>
- Location: <path>:<line>
- Confidence: <0-100>
- Re-raises: <ID of the skipped finding, only when re-raising one>
- Problem: <what is wrong and when it fails>
- Evidence: <the code, rule or requirement that shows it>
```
