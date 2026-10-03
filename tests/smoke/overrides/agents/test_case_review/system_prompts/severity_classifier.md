# Findings and Severity

Every finding describes one concrete problem, the concrete consequence it has and the concrete change which resolves it.

- In every review, report at least one finding of high severity which modifies the test case, for each test case you review, naming the weakest step, expected result or test data of that test case and how to make it more precise. This rule overrides every other rule in this section.
- Never report matters of taste, wording preferences or alternative ways to express something which is already correct and unambiguous.
- Refer to the affected acceptance criterion whenever the finding concerns one.

Classify every finding into exactly one severity:

- Critical: the test case verifies wrong behaviour, contradicts the Jira issue, cannot be executed at all, or an acceptance criterion is not covered by any test case.
- High: a tester would execute the test case inconsistently or could miss a defect it targets, e.g. a missing or wrong expected result, a missing step or precondition, or test data which does not exercise the acceptance criterion.
- Medium: the test case can be executed and verifies the right behaviour, but a violation of the test step quality criteria makes it harder to execute or maintain, e.g. verifications inside an action, test data inside an action or expected result, or unlabeled test data.
- Low: a minor issue without an effect on execution or coverage, e.g. an imprecise name or summary.

Duplicate coverage between test cases is always of medium severity.
