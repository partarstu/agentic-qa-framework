# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import hashlib
import itertools
import re
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Optional

from a2a.types import Part
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.json_schema import SkipJsonSchema
from pydantic_ai.messages import BinaryContent


@dataclass(slots=True)
class FileArtifact:
    """File artifact produced during test execution (replaces removed FileWithBytes)."""

    name: str
    raw: bytes
    media_type: str


class JsonSerializableModel(BaseModel):
    """A base model that provides a JSON string representation."""

    def __str__(self) -> str:
        return self.model_dump_json(indent=2)


class AgentExecutionError(JsonSerializableModel):
    error_message: str = Field(description="Error message describing the failure")


class AgentRuntimeError(Exception):
    """Raised when agent execution fails; carries artifact parts for the failed task response."""

    def __init__(self, parts: list[Part], message: str = ""):
        super().__init__(message)
        self.parts = parts


class BaseAgentResult(JsonSerializableModel):
    """Base class for all agent result models, carrying the `llm_comments` the model uses to report gaps, missing tools
    or anything that stopped it from completing the task.
    """

    llm_comments: str | None = Field(
        default=None,
        description="Debug comments regarding any exceptional situations, missing tools, information gaps, "
        "or other issues encountered during task execution. Use this field to explain what prevented "
        "full task completion or to provide additional context about the result.",
    )


class VectorizableBaseModel(JsonSerializableModel, ABC):
    """Abstract base class for models that can be stored in a vector database."""

    @abstractmethod
    def get_vector_id(self) -> int | str:
        """Returns the point ID for the vector database: a 64-bit unsigned integer or a standard UUID string."""
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
    id: int = Field(description="The numeric ID of the issue")
    key: str = Field(description="The key of the issue")
    summary: str = Field(description="The summary of the issue")
    description: str = Field(description="The description of the issue")
    issue_type: str = Field(description="The type of the issue")
    status: str | None = Field(default=None, description="Status of the issue")
    project_key: str | None = Field(default=None, description="Project key of the issue")
    source: str | None = Field(default=None, description="Source of the data")
    updated_at: str | None = Field(
        default=None,
        description="Last update timestamp in ISO 8601 format (e.g., '2025-01-15T10:30:00Z') for datetime range filtering",
    )

    def get_vector_id(self) -> int:
        return self.id

    def get_embedding_content(self) -> str:
        return f"{self.summary}\n\n{self.description}"


DocumentSource = Literal["confluence", "sharepoint"]
ContentKind = Literal["page_body", "attachment"]


class SyncStatus(StrEnum):
    """The one status vocabulary of a scoped sync, from the runner to the dashboard. It is a ``StrEnum``, so it
    serialises and compares as the string already persisted and rendered.
    """

    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"


class DocumentPagePart(VectorizableBaseModel):
    """One part of a Confluence document stored in the documents collection. A page-body chunk is one part; an
    attachment page is split into text parts sharing the page's reconciliation chain, with the page image on part 0
    only.
    """

    source: DocumentSource = Field(description="Source system of the document")
    space_key: str = Field(default="", description="Key of the Confluence space")
    page_id: str = Field(default="", description="ID of the Confluence page")
    page_title: str = Field(default="", description="Title of the Confluence page")
    drive_id: str | None = Field(default=None, description="ID of the SharePoint drive")
    folder_path: str | None = Field(default=None, description="Folder path of the SharePoint file")
    page_url: str | None = Field(default=None, description="Web UI link of the page")
    attachment_id: str | None = Field(default=None, description="ID of the attachment, for attachment pages")
    attachment_name: str | None = Field(default=None, description="File name of the attachment")
    media_type: str | None = Field(default=None, description="Media type of the attachment")
    content_kind: ContentKind = Field(description="'page_body' for page-body chunks, 'attachment' for attachment pages")
    document_name: str = Field(
        description="The name retrieval matches document-name patterns against: the attachment file "
        "name for attachments, the page title for page-body chunks"
    )
    breadcrumb: str = Field(description="The breadcrumb or reconciliation chain prefix of the text")
    text: str = Field(description="The embedded text: breadcrumb plus content")
    page_number: int | None = Field(default=None, description="1-based page number within the attachment")
    page_count: int | None = Field(default=None, description="True total page count of the attachment")
    part_index: int = Field(description="0-based index of this part within its page or chunk sequence")
    image: str | None = Field(default=None, description="Base64 PNG of the page image, stored on part 0 only")

    def get_vector_id(self) -> str:
        """Deterministic UUID derived from content identity: source, item, page and part index."""
        item = self.attachment_id or self.page_id
        scope = str(self.page_number) if self.attachment_id else "body"
        identity = f"quaia:document:{self.source}:{item}:{scope}:{self.part_index}"
        return str(uuid.uuid5(uuid.NAMESPACE_URL, identity))

    def get_embedding_content(self) -> str:
        return self.text


class ProjectMetadata(VectorizableBaseModel):
    project_key: str = Field(description="Key of the project")
    last_update: str = Field(description="Last update timestamp")

    def get_vector_id(self) -> int:
        return int(hashlib.md5(self.project_key.encode(), usedforsecurity=False).hexdigest()[:16], 16)

    def get_embedding_content(self) -> str:
        return f"Metadata for {self.project_key}"


class RagUpdateResult(BaseAgentResult):
    """Result of RAG update operation."""

    status: SyncStatus = Field(description="Status of the RAG update operation")
    processed_count: int = Field(description="Number of items processed during the update")


class SyncRequest(BaseModel, ABC):
    """One validated RAG sync request, shared by the orchestrator and the sync runtime. The same object is the
    endpoint's request body, the source of the runner's command-line arguments in job mode and the forwarded payload
    in local mode, so every field reaching a query language or a REST path is constrained here once.
    """

    @abstractmethod
    def to_cli_args(self) -> list[str]:
        """The runner arguments AFTER the source, e.g. ``["--project-key", "PROJ"]``."""


class JiraSyncRequest(SyncRequest):
    """Scope of a Jira issue or test-case sync: one project."""

    project_key: str = Field(min_length=1, pattern=r"^[A-Z][A-Z0-9_]*$")

    def to_cli_args(self) -> list[str]:
        return ["--project-key", self.project_key]


class AttachmentFilteredSyncRequest(SyncRequest, ABC):
    """A sync scope whose attachments can be narrowed by a name pattern."""

    attachment_name_pattern: str | None = Field(default=None, max_length=200)

    @field_validator("attachment_name_pattern")
    @classmethod
    def _reject_unusable_pattern(cls, pattern: str | None) -> str | None:
        """Compile the pattern here, so every entry point rejects an unusable one as a bad request."""
        if pattern:
            # Deferred: common.utils imports this module, so importing it at module level would cycle.
            from common.utils import compile_name_pattern

            compile_name_pattern(pattern)
        return pattern


class SharePointSyncRequest(AttachmentFilteredSyncRequest):
    """Scope of a SharePoint sync: one drive, optionally one folder of it."""

    # Graph drive IDs are opaque but never carry path or query characters; constraining them keeps
    # a request from steering the app-only token at another Graph resource through the REST path.
    drive_id: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9!._-]+$")
    folder_path: str | None = Field(default=None, max_length=500)

    def to_cli_args(self) -> list[str]:
        args = ["--drive-id", self.drive_id]
        if self.folder_path:
            args += ["--folder-path", self.folder_path]
        if self.attachment_name_pattern:
            args += ["--attachment-name-pattern", self.attachment_name_pattern]
        return args


class ConfluenceSyncRequest(AttachmentFilteredSyncRequest):
    """Scope of a Confluence sync: one space, optionally one page of it."""

    space_key: str = Field(min_length=1, pattern=r"^[~]?[A-Za-z0-9._~-]+$")
    page_id: int | None = Field(default=None, gt=0)
    skip_page_body: bool = False

    def to_cli_args(self) -> list[str]:
        args = ["--space-key", self.space_key]
        if self.page_id:
            args += ["--page-id", str(self.page_id)]
        if self.attachment_name_pattern:
            args += ["--attachment-name-pattern", self.attachment_name_pattern]
        if self.skip_page_body:
            args += ["--skip-page-body"]
        return args


class SyncOutcome(JsonSerializableModel):
    """Durable, validated state of one scoped sync operation."""

    sync_type: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    status: SyncStatus
    processed_count: int = Field(default=0, ge=0)
    message: str = Field(default="", max_length=2000)
    started_at: str | None = None
    updated_at: str


class RequirementsReviewFeedback(BaseAgentResult):
    suggested_improvements: str = Field(
        description="List of improvements suggested by the requirements review, in plain text"
    )


class AcceptanceCriteriaItem(JsonSerializableModel):
    id: str = Field(description="The ID of the acceptance criterion (e.g., 'AC-1')")
    text: str = Field(description="The text of the acceptance criterion")
    additional_info: str = Field(
        description="All information from the Jira issue content, beyond the criterion's own text, which is "
        "relevant to this acceptance criteria item"
    )


class AcceptanceCriteriaList(JsonSerializableModel):
    items: list[AcceptanceCriteriaItem] = Field(description="List of extracted acceptance criteria")


class TestStep(JsonSerializableModel):
    __test__ = False
    action: str = Field(
        description="The description of the action which needs to be executed in the scope of this test step"
    )
    expected_results: str = Field(description="Results expected after the test step action is executed")
    test_data: list[str] = Field(description="The list of test data items which belong to this test step")


class TestStepsSequence(JsonSerializableModel):
    ac_id: str = Field(description="The ID of the acceptance criteria item which these steps cover")
    steps: list[TestStep] = Field(description="List of test steps ordered in the logical execution sequence")


class TestStepsSequenceList(JsonSerializableModel):
    __test__ = False
    items: list[TestStepsSequence] = Field(description="List of test step sequences for multiple acceptance criteria.")


class TestCase(JsonSerializableModel):
    __test__ = False
    key: str | None = Field(description="The ID or key of the generated test case")
    labels: list[str] = Field(
        description="The list of the labels which were assigned to this test case, should "
        "be empty for a newly created test case"
    )
    name: str = Field(description="The name of this test case")
    summary: str
    comment: str = Field(description="Any important comments or warnings from your side")
    preconditions: str | None = Field(description="Any preconditions relevant for this test case")
    steps: list[TestStep] = Field(description="Test steps of this test case")
    parent_issue_key: str | None = Field(
        description="The Jira issue key to which this test case is related and will be linked to"
    )


class DesignedTestCase(TestCase):
    """A test case of a design, traced to the acceptance criteria it verifies."""

    ac_ids: list[str] = Field(description="The IDs of the acceptance criteria which this test case verifies")


class ListedTestCase(JsonSerializableModel):
    """A test case returned by a project-wide listing with its current status."""

    test_case: TestCase
    status: str


class TestCaseType(StrEnum):
    """Supported automated test-case types and their Jira labels."""

    UI = "UI"
    API = "API"
    SECURITY = "SECURITY"
    PERFORMANCE = "PERFORMANCE"
    LOAD = "LOAD"
    STRESS = "STRESS"

    @property
    def label(self) -> str:
        """Return the Jira label used to route this test type."""
        return self.value.lower()


class GeneratedTestCases(BaseAgentResult):
    """Result of test case generation."""

    test_cases: list[DesignedTestCase] = Field(description="The list of generated by you test cases")


class ClassifiedTestCase(JsonSerializableModel):
    issue_key: str = Field(description="The Jira issue key of the test case")
    name: str = Field(description="The name of the test case")
    test_type: TestCaseType
    automation_capability: Literal["automated", "semi-automated", "manual"]
    labels: list[str]
    tool_use_comment: str = Field(
        description="Any comments regarding which tools you used, with which arguments and why"
    )


class TestCaseReviewRequest(JsonSerializableModel):
    test_cases: list[TestCase]


class OverlappingTestCase(JsonSerializableModel):
    """An existing test case whose coverage overlaps the reviewed one."""

    test_case_key: str = Field(description="The key of the candidate test case which overlaps in coverage")
    overlap_explanation: str = Field(description="What exactly both test cases cover in common")
    fully_covers: bool = Field(
        description="Whether the candidate verifies everything the reviewed test case verifies, so that the reviewed "
        "one adds no coverage of its own"
    )


class TestCaseDuplicateJudgement(BaseAgentResult):
    """The duplicate judge's verdict over the duplicate candidates of one reviewed test case."""

    __test__ = False
    overlapping_test_cases: list[OverlappingTestCase] = Field(
        description="Only the candidates which genuinely overlap in coverage with the reviewed test case; "
        "empty when none of them does"
    )


class TestCaseDuplicateCheck(JsonSerializableModel):
    """The outcome of the duplicate check of one reviewed test case; empty means no duplicates were found."""

    __test__ = False
    overlapping_test_cases: list[OverlappingTestCase] = Field(default_factory=list)


class FindingSeverity(StrEnum):
    """How much a review finding endangers the test case's purpose, ordered from low to critical."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return list(FindingSeverity).index(self)


class FindingAction(StrEnum):
    """What fixing a review finding does to the test cases."""

    MODIFY = "modify"
    REMOVE_DUPLICATE_STEPS = "remove_duplicate_steps"
    DELETE_TEST_CASE = "delete_test_case"
    ADD_TEST_CASE = "add_test_case"


class ReviewFinding(JsonSerializableModel):
    """One concrete problem found by a review, assigned to the single test case whose fix resolves it."""

    owner_test_case_id: str | None = Field(
        description="The ID of the only test case whose change resolves the finding; null only for 'add_test_case'"
    )
    action: FindingAction = Field(description="What fixing the finding does to the owner test case or the test set")
    severity: FindingSeverity
    category: str = Field(description="Short category of the problem, e.g. 'missing coverage' or 'ambiguous step'")
    description: str = Field(description="What exactly is wrong and which concrete consequence it has")
    suggested_fix: str = Field(description="The concrete change which resolves the finding")
    ac_ref: str | None = Field(default=None, description="The ID of the affected acceptance criterion, if any")
    related_test_case_ids: list[str] = Field(
        default_factory=list, description="IDs of other test cases involved, e.g. the duplicated one"
    )


class TestCaseReviewFeedback(BaseAgentResult):
    __test__ = False
    test_case_id: str = Field(description="The ID or key of the test case which was reviewed")
    findings: list[ReviewFinding] = Field(description="The findings of the review, empty when there are none")


class TestSuiteReview(BaseAgentResult):
    __test__ = False
    findings: list[ReviewFinding] = Field(
        description="The findings about the test cases as a whole set, empty when there are none"
    )


class DesignStopReason(StrEnum):
    """Why the generate-review-fix loop of a test case design stopped."""

    CONVERGED = "converged"
    ITERATION_LIMIT = "iteration_limit"
    NO_PROGRESS = "no_progress"


class DeletedTestCase(JsonSerializableModel):
    """A test case which a fix deleted, kept so that it can be restored if its deletion leaves a coverage gap."""

    test_case: DesignedTestCase
    findings: list[ReviewFinding]
    deleted_by: ReviewFinding


class PreviousReview(JsonSerializableModel):
    """A test case as it was reviewed before its last fix, with the findings of that review."""

    test_case: DesignedTestCase
    findings: list[ReviewFinding]


DRAFT_ID_PREFIX = "DRAFT-"
# Jira issue keys are a project key, a hyphen and the issue number, e.g. PROJ-123.
JIRA_ISSUE_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*-\d+$")


class TestCaseDesignRequest(JsonSerializableModel):
    """The structured data part of a test case design task; the design session starts from it."""

    __test__ = False
    model_config = ConfigDict(extra="forbid")

    story_key: str = Field(pattern=JIRA_ISSUE_KEY_PATTERN.pattern)


class TestCaseDesignSession(JsonSerializableModel):
    """The state of one test case design, shared in-process by the design agent and the agents it delegates to.

    Test cases are keyed by a temporary `DRAFT-<n>` id until they are saved, then by their test management system key.
    """

    __test__ = False

    story_key: str
    story_id: int | None = None
    story_content: str | None = None
    attachments: SkipJsonSchema[dict[str, BinaryContent] | None] = None
    acceptance_criteria: list[AcceptanceCriteriaItem] = Field(default_factory=list)
    test_cases: dict[str, DesignedTestCase] = Field(default_factory=dict)
    changed_test_case_ids: set[str] = Field(default_factory=set)
    findings: dict[str, list[ReviewFinding]] = Field(default_factory=dict)
    suite_findings: list[ReviewFinding] = Field(default_factory=list)
    deleted_test_cases: dict[str, DeletedTestCase] = Field(default_factory=dict)
    previous_reviews: dict[str, PreviousReview] = Field(default_factory=dict)
    duplicate_checks: dict[str, TestCaseDuplicateCheck] = Field(default_factory=dict)
    iteration: int = 0
    fixes: int = 0
    previous_blocking_count: int | None = None
    stop_reason: DesignStopReason | None = None
    next_draft_number: int = 1
    uploaded: bool = False
    classified: bool = False
    published: bool = False

    @property
    def project_key(self) -> str:
        return self.story_key.rsplit("-", 1)[0]

    def add_draft(self, test_case: DesignedTestCase) -> str:
        """Stores a new test case under the next draft id, marks it changed and returns the id."""
        draft_id = f"{DRAFT_ID_PREFIX}{self.next_draft_number}"
        self.next_draft_number += 1
        self.test_cases[draft_id] = test_case
        self.changed_test_case_ids.add(draft_id)
        return draft_id

    def restore_named_by(self, gaps: list[ReviewFinding]) -> list[str]:
        """Puts the deleted test cases which the coverage gaps name back, with their findings, and returns their IDs.

        A restored test case is marked changed, so that a review that follows gives it a full review.
        """
        restored: list[str] = []
        for gap in gaps:
            for test_case_id in gap.related_test_case_ids:
                if deleted := self.deleted_test_cases.pop(test_case_id, None):
                    self.test_cases[test_case_id] = deleted.test_case
                    self.findings[test_case_id] = deleted.findings
                    self.changed_test_case_ids.add(test_case_id)
                    restored.append(test_case_id)
        return restored

    def blocking_findings(self, min_severity: FindingSeverity) -> list[ReviewFinding]:
        """The per-test-case and whole-set findings at or above the given severity."""
        all_findings = [*itertools.chain.from_iterable(self.findings.values()), *self.suite_findings]
        return [finding for finding in all_findings if finding.severity.rank >= min_severity.rank]

    def drop_blocking_findings(self, min_severity: FindingSeverity) -> None:
        """Removes the per-test-case and whole-set findings at or above the given severity."""
        self.findings = {
            test_case_id: [finding for finding in findings if finding.severity.rank < min_severity.rank]
            for test_case_id, findings in self.findings.items()
        }
        self.suite_findings = [finding for finding in self.suite_findings if finding.severity.rank < min_severity.rank]


class TestCaseDesignResult(BaseAgentResult):
    __test__ = False
    # Filled in from the design session by code, never by a model, so they are hidden from the output schema.
    test_case_keys: SkipJsonSchema[list[str]] = Field(default_factory=list)
    iterations: SkipJsonSchema[int] = 0
    stop_reason: SkipJsonSchema[DesignStopReason | None] = None


class TestExecutionRequest(JsonSerializableModel):
    test_case: TestCase


class TestStepResult(JsonSerializableModel):
    __test__ = False
    stepDescription: str = Field(description="Description of the test step (action which was executed)")
    testData: list[str] = Field(description="Data used for the test step")
    expectedResults: str = Field(description="Expected results for the test step")
    actualResults: str = Field(description="Actual results based on the execution")
    success: bool = Field(description="Whether the test step passed or failed")
    errorMessage: str = Field(description="Error message if the test step failed")
    executionStartTimestamp: str | None = Field(default=None, description="Timestamp when the step execution started")
    executionEndTimestamp: str | None = Field(default=None, description="Timestamp when the step execution ended")


class AgentInfo(JsonSerializableModel):
    """Traceability data about the agent that produced a test execution result."""

    agent_name: str
    agent_version: str
    environment: str


class TestExecutionResult(JsonSerializableModel):
    __test__ = False
    stepResults: list[TestStepResult] = Field(description="List of test step execution results in the test case")
    testCaseKey: str = Field(description="Key of the executed test case")
    testCaseName: str = Field(description="Name of the executed test case")
    testExecutionStatus: Literal["passed", "failed", "error"] = Field(
        description="Overall status of the test execution"
    )
    generalErrorMessage: str = Field(
        description="General error message if the test execution failed (e.g. preconditions failed)"
    )
    artifacts: list[FileArtifact] | None = Field(
        default=None,
        description="Optional dictionary of artifacts generated during "
        "execution (e.g., screenshots, reports, stack traces etc.)",
    )
    start_timestamp: str = Field(description="Timestamp when the test execution started")
    end_timestamp: str = Field(description="Timestamp when the test execution ended")
    system_description: str | None = Field(
        default=None, description="Description of the system on which the agent executed the test case"
    )
    incident_creation_result: Optional["IncidentCreationResult"] = Field(
        default=None, description="Result of the incident creation process if the test failed"
    )
    test_case: Optional["TestCase"] = Field(default=None, description="The full test case object that was executed")
    agent_info: AgentInfo | None = Field(
        default=None,
        description="Name and version of the agent which executed the test case and the environment it ran against. "
        "Populated by the orchestrator, not expected from the execution agent.",
    )


class TestCaseKeys(JsonSerializableModel):
    __test__ = False
    issue_keys: list[str]


class ClassifiedTestCases(BaseAgentResult):
    """Result of test case classification."""

    test_cases: list[ClassifiedTestCase]


class ProjectExecutionRequest(JsonSerializableModel):
    """Request to trigger test execution for a project."""

    project_key: str = Field(description="The key of the project for which all tests should be executed")


class AggregatedTestResults(JsonSerializableModel):
    """Payload for sending aggregated test results to the processing agent."""

    results: list[TestExecutionResult]


class AgentSkillDeclaration(JsonSerializableModel):
    """Declared skill of a Python agent, published on its A2A card. Every agent declares exactly one skill with a stable
    identity, which AgentBase requires and never replaces with a generic fallback.
    """

    id: str = Field(description="Stable, unique skill ID, e.g. 'jira-requirements-review'")
    name: str = Field(description="Human-readable skill name, e.g. 'Jira Requirements Review'")
    description: str = Field(description="What the agent can do, used for routing decisions")
    tags: list[str] = Field(default_factory=lambda: ["qa"], description="Skill tags")


class RoutingOutcome(StrEnum):
    """Outcome of one routing decision over the full agent registry."""

    AGENT_SELECTED = "agent_selected"
    SUITABLE_BUT_BUSY = "suitable_but_busy"
    NONE_SUITABLE = "none_suitable"


class AgentRoutingDecision(JsonSerializableModel):
    """Result of one routing call that sees every registered agent, including availability.

    The justification is mandatory for every outcome, so an unusable decision is never silent.
    """

    selected_agent_id: str | None = Field(
        default=None,
        description="ID of the single most suitable agent. Must be None unless the outcome is 'agent_selected'.",
    )
    outcome: RoutingOutcome = Field(description="One of the three routing outcomes")
    justification: str = Field(
        description="Elaborate justification of the decision. Must always be given, whatever the outcome."
    )


class SelectedAgents(JsonSerializableModel):
    ids: list[str] = Field(description="The IDs of all agents that are suitable for the task execution")
    justification: str = Field(
        default="",
        description="Justification of the selection, to be given whenever the selected set is empty or partial",
    )


class IncidentCreationInput(JsonSerializableModel):
    project_key: str = Field(min_length=1, description="Project key owning the incident")
    test_case: TestCase
    test_execution_result: str
    test_step_results: list["TestStepResult"] = Field(
        description="Structured test step execution results for reproduction steps and analysis"
    )
    system_description: str
    issue_priority_field_id: str = Field(description="The ID of the Jira issue field for issue priority")


class DuplicateCandidate(JsonSerializableModel):
    issue_id: str | None = Field(default=None, description="Numeric Jira issue ID of the candidate when available")
    key: str = Field(description="Jira issue key of the candidate (e.g. 'PROJ-123')")
    content: str = Field(description="Full content/description of the candidate issue")


class DuplicateIssue(JsonSerializableModel):
    issue_id: str = Field(
        description="The numeric issue ID of existing incident Jira issue, which is a candidate for duplicate"
    )
    issue_key: str = Field(description="The key of existing incident Jira issue, which is a candidate for duplicate")
    message: str = Field(description="Elaborate Justification of the decision about being or not being a duplicate")


class DuplicateDetectionResult(JsonSerializableModel):
    duplicates: list[DuplicateIssue] = Field(
        default_factory=list,
        description="Only the candidates confirmed to be actual duplicates of the current incident",
    )
    message: str = Field(default="", description="Summary of the duplicate detection outcome")


class IncidentCreationResult(BaseAgentResult):
    incident_id: int | None = Field(default=None, description="The numeric issue ID of the created incident")
    incident_key: str | None = Field(description="The key of the created incident, is null if duplicates are detected")
    duplicates: list[DuplicateIssue] = Field(description="All identified duplicate incidents, may be empty")
