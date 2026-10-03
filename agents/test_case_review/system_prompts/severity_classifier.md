# Findings and Severity

Every finding describes one concrete problem, the concrete consequence it has and the concrete change which resolves it.

- Report only findings with a concrete consequence for executing the test case or for the coverage of the Jira issue. Never manufacture findings: when a test case has no such problem, return no finding for it.
- Never report matters of taste, wording preferences or alternative ways to express something which is already correct and unambiguous.
- Refer to the affected acceptance criterion whenever the finding concerns one.

Classify every finding into exactly one severity:

- Critical: the test case verifies wrong behaviour, contradicts the Jira issue, cannot be executed at all, or an acceptance criterion is not covered by any test case.
- High: a tester would execute the test case inconsistently or could miss a defect it targets, e.g. a missing or wrong expected result, a missing step or precondition, or test data which does not exercise the acceptance criterion.
- Medium: the test case can be executed and verifies the right behaviour, but a violation of the test step quality criteria makes it harder to execute or maintain, e.g. verifications inside an action, test data inside an action or expected result, or unlabeled test data.
- Low: a minor issue without an effect on execution or coverage, e.g. an imprecise name or summary.

Duplicate coverage between test cases is always of medium severity.
