# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

from typing import List, Literal, Optional

from a2a.types import FileWithBytes
from pydantic import Field, BaseModel


class JsonSerializableModel(BaseModel):
    """A base model that provides a JSON string representation."""

    def __str__(self) -> str:
        return self.model_dump_json(indent=2)


class JiraUserStory(JsonSerializableModel):
    id: str
    key: str
    summary: str
    description: str
    acceptance_criteria: str
    status: str


class RequirementsReviewFeedback(JsonSerializableModel):
    suggested_improvements: List[str] = Field(description="List of improvements suggested by the review")


class SelectedAgent(JsonSerializableModel):
    name: str


class TestStep(JsonSerializableModel):
    action: str = Field(
        description="The description of the action which needs to be executed in the scope of this test step")
    expected_results: str = Field(description="Results expected after the test step action is executed")
    test_data: list[str] = Field(description="The list of test data items which belong to this test step")


class TestCase(JsonSerializableModel):
    id: Optional[str] = Field(description="The ID or key of the generated test case")
    labels: list[str] = Field(description="The list of the labels which were assigned to this test case, should "
                                          "be empty for a newly created test case")
    name: str = Field(description="The name of this test case")
    summary: str
    comment: str = Field(description="Any important comments or warnings from your side")
    preconditions: Optional[str] = Field(description="Any preconditions relevant for this test case")
    steps: List[TestStep] = Field(description="Test steps of this test case")
    parent_issue_key: Optional[str] = Field(
        description="The Jira issue key to which this test case is related and will be linked to")


class GeneratedTestCases(JsonSerializableModel):
    test_cases: List[TestCase]


class ClassifiedTestCase(JsonSerializableModel):
    issue_key: str = Field(description="The Jira issue key of the test case")
    name: str = Field(description="The name of the test case")
    test_type: Literal["UI", "API", "Performance", "Load/Stress"]
    automation_capability: Literal["automated", "semi-automated", "manual"]
    labels: List[str]
    tool_use_comment: str = Field(
        description="Any comments regarding which tools you used, with which arguments and why")


class TestCaseReviewRequest(JsonSerializableModel):
    test_cases: List[TestCase]


class TestCaseReviewFeedback(JsonSerializableModel):
    test_case_id: str = Field(description="The ID or key of the test case which was reviewed")
    review_feedback: str = Field(description="Test case review feedback")


class TestCaseReviewFeedbacks(JsonSerializableModel):
    review_feedbacks: list[TestCaseReviewFeedback] = Field(
        description="A dictionary where the key is the test case ID/key and the value is the review feedback of "
                    "this test case")


class TestExecutionRequest(JsonSerializableModel):
    test_case: TestCase


class TestStepResult(JsonSerializableModel):
    stepDescription: str = Field(description="Description of the test step (action which was executed)")
    testData: list[str] = Field(description="Data used for the test step")
    expectedResults: str = Field(description="Expected results for the test step")
    actualResults: str = Field(description="Actual results based on the execution")
    success: bool = Field(description="Whether the test step passed or failed")
    errorMessage: str = Field(description="Error message if the test step failed")


class TestExecutionResult(JsonSerializableModel):
    stepResults: List[TestStepResult] = Field(description="List of test step execution results in the test case")
    testCaseKey: str = Field(description="Key of the executed test case")
    testCaseName: str = Field(description="Name of the executed test case")
    testExecutionStatus: Literal["passed", "failed", "error"] = Field(description="Overall status of the test"
                                                                                  " execution")
    generalErrorMessage: str = Field(description=
                                     "General error message if the test execution failed (e.g. preconditions failed)")
    logs: str = Field(description="Logs generated during the test execution")
    artifacts: Optional[List[FileWithBytes]] = Field(
        default=None, description="Optional dictionary of artifacts generated during execution (e.g., screenshots, "
                                  "reports, stack traces etc.)")
    start_timestamp: str = Field(description="Timestamp when the test execution started")
    end_timestamp: str = Field(description="Timestamp when the test execution ended")


class TestCaseKeys(JsonSerializableModel):
    issue_keys: List[str]


class ClassifiedTestCases(JsonSerializableModel):
    test_cases: List[ClassifiedTestCase]


# New models to be added:
class ProjectExecutionRequest(JsonSerializableModel):
    """Request to trigger test execution for a project."""
    project_key: str


class AggregatedTestResults(JsonSerializableModel):
    """Payload for sending aggregated test results to the processing agent."""
    results: List[TestExecutionResult]


class SelectedAgents(BaseModel):
    names: List[str] = Field(..., description="The names of all agents that are suitable for the task.")
