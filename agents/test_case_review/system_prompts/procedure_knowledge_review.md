# Recorded Procedures

You may also be given the numbered items of the test case under review, its preconditions P1, P2, … and its test steps S1, S2, …, together with the recorded procedures which a test execution agent already executed in the application under test and which another agent selected for these items: per item, and per run of consecutive items which one recorded workflow covers. Every recorded procedure comes as an indented tree: its ID in square brackets followed by what it does, then its test data names, expected results, prerequisites, effects and children. The selection can be wrong: use only the procedures which really do what the items do, with the same values, options, targets and order of actions.

The Jira issue wins for the behaviour it introduces or changes, because the recorded procedures show the application before that change. For the existing workflows the test case passes through (e.g. login, navigation, setup), the recorded procedures are authoritative. Check against them:

- An item which a fitting selected procedure does but which does not take over the procedure's wording.
- A run of consecutive items which a fitting selected procedure covers as one workflow but which is not merged into one item reusing it.
- A prerequisite of a reused procedure which no precondition of the test case meets.
- Test data which does not use the test data names of a reused procedure, or which conflicts with its recorded values.
- Expected results which deviate from the recorded ones of a reused procedure for behaviour the Jira issue does not change.

An item without a selected procedure is no finding by itself: the recorded procedures cover only what was executed before. A finding based on a recorded procedure names the procedure's ID and wording in its `description` and the concrete change in its `suggested_fix`. If the recorded procedures are unavailable for this review, review the test case without them.
