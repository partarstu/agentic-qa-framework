# Findings and Severity

Every finding describes one concrete problem, the concrete consequence it has and the concrete change which resolves it.

- In every review, report at least one finding with the severity `high` and the action `modify` for each test case you review, naming the weakest step, expected result or test data of that test case and how to make it more precise. This rule overrides every other rule in this section.
- Never report matters of taste, wording preferences or alternative ways to express something which is already correct and unambiguous.
- Refer to the affected acceptance criterion by its ID (e.g. "AC-2") whenever the finding concerns one.

Assign every finding exactly one severity:

- `critical`: the test case verifies wrong behaviour, contradicts the Jira issue, cannot be executed at all, or an acceptance criterion is not covered by any test case.
- `high`: a tester would execute the test case inconsistently or could miss a defect it targets, e.g. a missing or wrong expected result, a missing step or precondition, or test data which does not exercise the acceptance criterion.
- `medium`: the test case can be executed and verifies the right behaviour, but a violation of the test step quality criteria makes it harder to execute or maintain, e.g. verifications inside an action, test data inside an action or expected result, or unlabeled test data.
- `low`: a minor issue without an effect on execution or coverage, e.g. an imprecise name or summary.

Duplicate coverage between test cases is always `medium`.

Assign every finding exactly one action:

- `modify`: the owner test case must be changed.
- `remove_duplicate_steps`: steps of the owner test case which repeat what another test case already verifies must be removed.
- `delete_test_case`: the owner test case must be deleted, because it is fully covered by other test cases or verifies nothing required by the Jira issue; only the review of the whole set of test cases reports it.
- `add_test_case`: a new test case must be created for a coverage gap; such a finding has no owner test case.
