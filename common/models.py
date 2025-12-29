# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

import hashlib
from typing import List, Literal, Optional
from abc import ABC, abstractmethod

from a2a.types import FileWithBytes
from pydantic import Field, BaseModel


class JsonSerializableModel(BaseModel):
    """A base model that provides a JSON string representation."""

    def __str__(self) -> str:
        return self.model_dump_json(indent=2)


class VectorizableBaseModel(JsonSerializableModel, ABC):
    """Abstract base class for models that can be stored in a vector database."""

    @abstractmethod
    def get_vector_id(self) -> str:
        """Returns the unique ID for the vector database."""
        pass

    @abstractmethod
    def get_embedding_content(self) -> str:
        """Returns the content to be embedded."""
        pass


class JiraUserStory(JsonSerializableModel):
    id: int
    key: str
    summary: str
    description: str
    acceptance_criteria: str
    status: str


class JiraIssue(VectorizableBaseModel):
    """Model representing a Jira issue for vector storage.

    Fields can be used for payload filtering in vector searches:
    - issue_type: Filter by issue type (e.g., 'Bug', 'Story', 'Task')
    - status: Filter by issue status (e.g., 'To Do', 'In Progress', 'Done')
    - project_key: Filter by project key
    - source: Filter by data source
    - updated_at: Filter by last update timestamp (ISO 8601 format for datetime range queries)
    """

    id: int = Field(description="The numeric ID of the issue")
    key: str = Field(description="The key of the issue")
    summary: str = Field(description="The summary of the issue")
    description: str = Field(description="The description of the issue")
    issue_type: str = Field(description="The type of the issue")
    status: Optional[str] = Field(default=None, description="Status of the issue")
    project_key: Optional[str] = Field(default=None, description="Project key of the issue")
    source: Optional[str] = Field(default=None, description="Source of the data")
    updated_at: Optional[str] = Field(
        default=None,
        description="Last update timestamp in ISO 8601 format (e.g., '2025-01-15T10:30:00Z') for datetime range filtering",
    )

    def get_vector_id(self) -> str:
        # Use the numeric Jira issue ID directly
        return str(self.id)

    def get_embedding_content(self) -> str:
        return str(self)


class ProjectMetadata(VectorizableBaseModel):
    project_key: str = Field(description="Key of the project")
    last_update: str = Field(description="Last update timestamp")

    def get_vector_id(self) -> str:
        # Convert project_key to integer using hash
        return str(int(hashlib.md5(self.project_key.encode()).hexdigest()[:16], 16))

    def get_embedding_content(self) -> str:
        return f"Metadata for {self.project_key}"


class IncidentIndexData(VectorizableBaseModel):
    incident_id: int = Field(description="Numeric ID of the incident")
    incident_key: str = Field(description="Key of the incident")
    content: str = Field(description="Content to be indexed")
    source: str = Field(default="incident_creation", description="Source of the data")

    def get_vector_id(self) -> str:
        # Use the numeric Jira incident ID directly
        return str(self.incident_id)

    def get_embedding_content(self) -> str:
        return self.content


class RequirementsReviewFeedback(JsonSerializableModel):
    suggested_improvements: List[str] = Field(description="List of improvements suggested by the review")


class AcceptanceCriteriaItem(JsonSerializableModel):
    id: str = Field(description="The ID of the acceptance criterion (e.g., 'AC-1')")
    text: str = Field(description="The text of the acceptance criterion")
    attachment_info: str = Field(description="All information extracted from the attachments which might be relevant "
                                             "to this acceptance criteria item")


class AcceptanceCriteriaList(JsonSerializableModel):
    items: List[AcceptanceCriteriaItem] = Field(description="List of extracted acceptance criteria")


class TestStep(JsonSerializableModel):
    action: str = Field(
        description="The description of the action which needs to be executed in the scope of this test step")
    expected_results: str = Field(description="Results expected after the test step action is executed")
    test_data: list[str] = Field(description="The list of test data items which belong to this test step")


class TestStepsSequence(JsonSerializableModel):
    ac_id: str = Field(description="The ID of the acceptance criteria item which these steps cover")
    steps: List[TestStep] = Field(description="List of test steps ordered in the logical execution sequence")


class TestStepsSequenceList(JsonSerializableModel):
    items: List[TestStepsSequence] = Field(description="List of test step sequences for multiple acceptance criteria.")


class TestCase(JsonSerializableModel):
    key: Optional[str] = Field(description="The ID or key of the generated test case")
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
    test_cases: List[TestCase] = Field(description="The list of generated by you test cases")


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
    artifacts: Optional[List[FileWithBytes]] = Field(
        default=None, description="Optional dictionary of artifacts generated during execution (e.g., screenshots, "
                                  "reports, stack traces etc.)")
    start_timestamp: str = Field(description="Timestamp when the test execution started")
    end_timestamp: str = Field(description="Timestamp when the test execution ended")
    system_description: Optional[str] = Field(default=None, description="Description of the system on which the agent "
                                                                        "executed the test case.")
    incident_creation_result: Optional["IncidentCreationResult"] = Field(
        default=None, description="Result of the incident creation process if the test failed.")
    test_case: Optional["TestCase"] = Field(
        default=None, description="The full test case object that was executed.")


class TestCaseKeys(JsonSerializableModel):
    issue_keys: List[str]


class ClassifiedTestCases(JsonSerializableModel):
    test_cases: List[ClassifiedTestCase]


class ProjectExecutionRequest(JsonSerializableModel):
    """Request to trigger test execution for a project."""
    project_key: str = Field(description="The key of the project for which all tests should be executed.")


class AggregatedTestResults(JsonSerializableModel):
    """Payload for sending aggregated test results to the processing agent."""
    results: List[TestExecutionResult]


class SelectedAgent(JsonSerializableModel):
    id: str = Field(description="ID of the agent that is most suitable for the task execution.")


class SelectedAgents(JsonSerializableModel):
    ids: List[str] = Field(description="The IDs of all agents that are suitable for the task execution.")


class IncidentCreationInput(JsonSerializableModel):
    test_case: TestCase
    test_execution_result: str
    test_step_results: List["TestStepResult"] = Field(
        description="Structured test step execution results for reproduction steps and analysis"
    )
    system_description: str
    issue_priority_field_id: str = Field(
        description="The ID of the Jira issue field for issue priority"
    )
    issue_severity_field_name: str = Field(
        description="The name of the Jira issue field for issue severity"
    )


class DuplicateDetectionResult(JsonSerializableModel):
    issue_key: str = Field(description="The key of existing incident Jira issue, which is a candidate for duplicate")
    is_duplicate: bool = Field(description="True if the candidate is indeed a duplicate")
    message: str = Field(description="Elaborate Justification of the decision about being or not being a duplicate")


class IncidentCreationResult(JsonSerializableModel):
    incident_id: Optional[int] = Field(default=None, description="The numeric ID of the created incident")
    incident_key: Optional[str] = Field(description="The key of the created incident, may be null if duplicates are detected")
    duplicates: List[DuplicateDetectionResult] = Field(
        description="All identified positive duplicate incident detection results, may be empty")
