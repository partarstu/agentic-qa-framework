# Test Step Quality Criteria

- Each test step represents a complete, self-contained logical operation: it covers a coherent unit of work (e.g. filling in a form section, submitting an action, navigating to a screen, sending an API request) and may naturally encompass multiple individual interactions.
- Each test step has at least one action (a description of what needs to be executed and how) and at least one expected result reflecting a change of the state of the application under test as a result of the action.
- A test step action never contains verifications, checks, observations or assertions, because they are always implied by the expected results of the test step.
- If a test step has multiple expected results, all of them are caused by the action of this test step. Every expected result which doesn't meet this rule belongs to another test step.
- If a test step action presumes providing input data, such data is present only in the test data of the step, never in its action or expected results.
- If a test step action relates directly to the test data, the action simply refers to that data instead of duplicating it (e.g. "click the option in the list" rather than "click option '9' in the list", with the exact value present in the test step data).
- If a test step has multiple test data items, each of them is labeled to show what it represents (e.g. "departure time: 15:04", "first name: John").
- Expected results never duplicate the test data but refer to it (e.g. 'specified name', 'selected date'). If expected results refer to the test data of a previous step, they say so explicitly (e.g. 'selected in the previous steps date', 'provided in the previous steps name').
- Test data is realistic, adequate to the corresponding acceptance criterion, explicit and precise, but never real production or real personal data.
- Test data corresponds to the scope of the acceptance criterion: no invented or out-of-scope data.
- Test data is based on boundary value analysis and equivalence partitions wherever they apply.
- Test steps never duplicate the preconditions of the test case.
