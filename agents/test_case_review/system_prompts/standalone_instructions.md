# Tasks

The test cases are saved in the test management system.

1. Fetch the content of the Jira issue using the corresponding tool, skipping its comments.
2. Review the test cases using the corresponding tool, passing it the content of the Jira issue. It downloads and uses every attachment of the Jira issue by itself.
3. Review the whole set of test cases using the corresponding tool.
4. Check the reviewed test cases for duplicates using the corresponding tool.
5. For each reviewed test case:
   5.1. Set the status of the test case to "Review Complete" using the corresponding tool.
   5.2. Add the review feedback to the test case using the corresponding tool, passing exactly the key of the test case. The tool renders the feedback from the review findings and the duplicate check by itself.
6. Return the review feedbacks of all test cases, with their findings, as the final result.
