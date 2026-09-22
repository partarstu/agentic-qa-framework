# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""
Centralized configuration for the application.
"""

import os
import re
from pathlib import Path

from dotenv import load_dotenv
from pydantic_ai.settings import ThinkingLevel

load_dotenv()


def _optional_positive_int(name: str) -> int | None:
    """Read an optional positive integer setting."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    value = int(raw)
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer.")
    return value


# Logging
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
GOOGLE_CLOUD_LOGGING_ENABLED = os.environ.get("GOOGLE_CLOUD_LOGGING_ENABLED", "False").lower() in ("true", "1", "t")
# When enabled, each service (orchestrator and the Python agents) additionally writes its logs to a rotating file
# under LOG_DIR, named after the service's package (e.g. orchestrator.log, requirements_review.log).
LOG_TO_FILE = os.environ.get("LOG_TO_FILE", "True").lower() in ("true", "1", "t")
LOG_DIR = os.environ.get("LOG_DIR", str(Path(__file__).resolve().parent / "logs"))

# Prompt overrides. When set, a file in this directory replaces the bundled template at the
# same repository-relative path (see common/prompt_base.py). Unset means bundled prompts only.
PROMPT_OVERRIDES_DIR = os.environ.get("PROMPT_OVERRIDES_DIR")

# URLs
ORCHESTRATOR_HOST = os.environ.get("ORCHESTRATOR_HOST", "localhost")
ORCHESTRATOR_PORT = int(os.environ.get("ORCHESTRATOR_PORT", "8000"))
ORCHESTRATOR_URL = os.environ.get("ORCHESTRATOR_URL", f"http://{ORCHESTRATOR_HOST}:{ORCHESTRATOR_PORT}")
ATLASSIAN_MCP_SERVER_URL = os.environ.get("ATLASSIAN_MCP_SERVER_URL", "http://localhost:9000/mcp")
ZEPHYR_BASE_URL = os.environ.get("ZEPHYR_BASE_URL")
JIRA_BASE_URL = os.environ.get("JIRA_URL")
JIRA_USER = os.environ.get("JIRA_USERNAME")
JIRA_TOKEN = os.environ.get("JIRA_API_TOKEN")

# Webhook URLs
NEW_REQUIREMENTS_WEBHOOK_URL = f"{ORCHESTRATOR_URL}/new-requirements-available"
STORY_READY_FOR_TEST_CASE_GENERATION_WEBHOOK_URL = f"{ORCHESTRATOR_URL}/story-ready-for-test-case-generation"
EXECUTE_TESTS_WEBHOOK_URL = f"{ORCHESTRATOR_URL}/execute-tests"
UPDATE_JIRA_DB_WEBHOOK_URL = f"{ORCHESTRATOR_URL}/update-jira-db"
UPDATE_TEST_CASE_DB_WEBHOOK_URL = f"{ORCHESTRATOR_URL}/update-test-case-db"
UPDATE_SHAREPOINT_DB_WEBHOOK_URL = f"{ORCHESTRATOR_URL}/update-sharepoint-db"

# Secrets
JIRA_WEBHOOK_SECRET = os.environ.get("JIRA_WEBHOOK_SECRET")
# Shared secret guarding the internal embedding and prompt-guard services. When set, those
# services require a matching X-API-Key header and their clients send it. Left unset, the
# services stay open (they are expected to be reachable only on a private network).
INTERNAL_SERVICE_API_KEY = os.environ.get("INTERNAL_SERVICE_API_KEY")
ZEPHYR_API_TOKEN = os.environ.get("ZEPHYR_API_TOKEN")
XRAY_BASE_URL = os.environ.get("XRAY_BASE_URL")
XRAY_CLIENT_ID = os.environ.get("XRAY_CLIENT_ID")
XRAY_CLIENT_SECRET = os.environ.get("XRAY_CLIENT_SECRET")
XRAY_PRECONDITIONS_FIELD_ID = os.environ.get("XRAY_PRECONDITIONS_FIELD_ID", "Pre-conditions")

# Confluence Cloud access for the RAG document sync and for the combined Atlassian MCP server.
CONFLUENCE_URL = os.environ.get("CONFLUENCE_URL")
CONFLUENCE_USERNAME = os.environ.get("CONFLUENCE_USERNAME")
CONFLUENCE_API_TOKEN = os.environ.get("CONFLUENCE_API_TOKEN")

# Additional Jira custom fields handed to agents. Comma-separated custom field IDs; entries are trimmed,
# empty entries and duplicates are dropped. Every entry must match the Jira custom field ID format
# (customfield_ followed by digits) - anything else fails startup, which also keeps free text out of
# LLM tasks. Empty/unset means no additional fields and unchanged task texts.
_ADDITIONAL_FIELD_PATTERN = re.compile(r"^customfield_\d+$")


def _parse_additional_field_ids(raw: str | None) -> tuple[str, ...]:
    """Parses JIRA_ADDITIONAL_FIELD_IDS, dropping blanks/duplicates and validating the ID format."""
    if not raw:
        return ()
    ids: list[str] = []
    for entry in raw.split(","):
        field_id = entry.strip()
        if not field_id or field_id in ids:
            continue
        if not _ADDITIONAL_FIELD_PATTERN.fullmatch(field_id):
            raise ValueError(
                f"JIRA_ADDITIONAL_FIELD_IDS entry '{field_id}' is not a valid Jira custom field ID "
                "(expected 'customfield_' followed by digits)."
            )
        ids.append(field_id)
    return tuple(ids)


JIRA_ADDITIONAL_FIELD_IDS: tuple[str, ...] = _parse_additional_field_ids(os.environ.get("JIRA_ADDITIONAL_FIELD_IDS"))

# Agent
AGENT_BASE_URL = os.environ.get("AGENT_BASE_URL", "http://localhost")
MCP_SERVER_ATTACHMENTS_FOLDER_PATH = os.environ.get("MCP_SERVER_ATTACHMENTS_FOLDER_PATH", "/tmp")
ATTACHMENTS_LOCAL_DESTINATION_FOLDER_PATH = os.environ.get("ATTACHMENTS_LOCAL_DESTINATION_FOLDER_PATH", "/tmp")
JIRA_ATTACHMENT_SKIP_POSTFIX = os.environ.get("JIRA_ATTACHMENT_SKIP_POSTFIX", "_SKIP")
# Checked against the listed attachment size before any download, and against the downloaded
# content when Jira reports no size. The default matches the current Gemini API inline-data limit.
JIRA_ATTACHMENT_MAX_BYTES = int(os.environ.get("JIRA_ATTACHMENT_MAX_BYTES", str(100 * 1024 * 1024)))
JIRA_ATTACHMENT_DOWNLOAD_TIMEOUT_SECONDS = float(os.environ.get("JIRA_ATTACHMENT_DOWNLOAD_TIMEOUT_SECONDS", "60"))
MCP_SERVER_TIMEOUT_SECONDS = int(os.environ.get("MCP_SERVER_TIMEOUT_SECONDS", "30"))
MCP_SESSION_LIFECYCLE_TIMEOUT_SECONDS = int(os.environ.get("MCP_SESSION_LIFECYCLE_TIMEOUT_SECONDS", "30"))
SUPPORTED_ATTACHMENT_MIME_TYPES: set[str] = {
    # Images
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    # Documents
    "application/pdf",
    "text/plain",
    "application/json",
    # Audio
    "audio/mpeg",
    "audio/wav",
    "audio/flac",
    "audio/ogg",
    "audio/aac",
    "audio/aiff",
    # Video
    "video/mp4",
    "video/webm",
    "video/quicktime",
    "video/x-matroska",
    "video/x-flv",
    "video/mpeg",
    "video/x-ms-wmv",
    "video/3gpp",
}

# Test Management System
ZEPHYR_COMMENTS_CUSTOM_FIELD_NAME = "Review Comments"
ZEPHYR_CLIENT_TIMEOUT_SECONDS = 15
ZEPHYR_CUSTOM_FIELDS_JSON_FIELD_NAME = "customFields"
TEST_MANAGEMENT_SYSTEM = os.environ.get("TEST_MANAGEMENT_SYSTEM", "zephyr").lower()

# Test Reporting
TEST_REPORTER = os.environ.get("TEST_REPORTER", "allure").lower()
ALLURE_RESULTS_DIR = "allure-results"
ALLURE_REPORT_DIR = "allure-report"

# OpenTelemetry
OPEN_TELEMETRY_URL = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
MAX_OUTPUT_TOKENS = _optional_positive_int("MAX_OUTPUT_TOKENS")

# Common model config
TOP_P = 1.0
TEMPERATURE = 0.0

# Model used by the orchestrator and every agent. Either a pydantic-ai model string
# (e.g. "google-gla:gemini-3.5-flash") or "qwen:<model>" for the self-hosted Qwen endpoint below.
DEFAULT_MODEL_NAME = os.environ.get("MODEL_NAME", "google-gla:gemini-3.5-flash")

# Provider API keys, read by the provider SDKs when their model family is configured.
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

# Self-hosted, OpenAI-compatible Qwen endpoint, used by model names prefixed with "qwen:". An endpoint
# served by Cloud Run authenticates through an IAM identity token minted from the application default
# credentials, so QWEN_API_KEY only applies to any other host.
QWEN_ENDPOINT = os.environ.get("QWEN_ENDPOINT", "")
QWEN_API_KEY = os.environ.get("QWEN_API_KEY", "")
# Master switch for Qwen's thinking. When on, each agent's THINKING_LEVEL grades it; when off, thinking is
# disabled through Qwen's chat template, which is the only way to switch it off entirely.
QWEN_THINKING_ENABLED = os.environ.get("QWEN_THINKING_ENABLED", "True").lower() in ("true", "1", "t")


class BudgetConfig:
    """Token budget (hard limit) and pricing used for cost oversight."""

    # Hard cap on the total number of tokens an agent may consume per task. When exceeded,
    # the agent run is aborted with pydantic-ai's UsageLimitExceeded. The cap is token-based
    # because pydantic-ai enforces token limits, not monetary ones.
    TOTAL_TOKENS_LIMIT_PER_TASK = int(os.environ.get("TOTAL_TOKENS_LIMIT_PER_TASK", "1000000"))

    # Indicative price in USD per 1,000,000 tokens, keyed by the bare model id (without a
    # provider prefix such as "google-gla:"). "cache_read"/"cache_write" rates are optional;
    # when absent, cached tokens are priced at the input rate. Used only to estimate cost for
    # oversight (logs + dashboard); keep these values current with the provider's published
    # pricing. Models absent from this table report a null cost.
    MODEL_PRICING: dict[str, dict[str, float]] = {
        "gemini-3.5-flash": {"input": 0.30, "output": 2.50},
        "gemini-3.8-flash": {"input": 0.75, "output": 3.75, "cache_read": 0.075},
        "claude-opus-5": {"input": 5.0, "output": 25.0, "cache_read": 0.5, "cache_write": 6.25},
        "claude-sonnet-5": {"input": 2.0, "output": 10.0, "cache_read": 0.2, "cache_write": 2.5},
    }


# Prompt injection detection config
PROMPT_INJECTION_CHECK_ENABLED = os.environ.get("PROMPT_INJECTION_CHECK_ENABLED", "False").lower() in ("true", "1", "t")
PROMPT_GUARD_PROVIDER = os.environ.get("PROMPT_GUARD_PROVIDER", "protect_ai")
PROMPT_INJECTION_MIN_SCORE = float(os.environ.get("PROMPT_INJECTION_MIN_SCORE", "0.8"))
LOCAL_MODELS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "local_models")
PROMPT_INJECTION_DETECTION_MODEL_PATH = os.path.join(LOCAL_MODELS_PATH, "prompt_detection_model")
PROMPT_INJECTION_DETECTION_MODEL_NAME = os.environ.get(
    "PROMPT_INJECTION_MODEL_NAME", "ProtectAI/deberta-v3-base-prompt-injection-v2"
)
# A pinned commit keeps a later upload to the model repository out of the image; it must belong to the model above.
PROMPT_INJECTION_DETECTION_MODEL_REVISION = os.environ.get(
    "PROMPT_INJECTION_MODEL_REVISION", "90c9989b1a342275dd0d1a95aad283c04e075671"
)
PROMPT_GUARD_SERVICE_URL = os.environ.get("PROMPT_GUARD_SERVICE_URL")


# Orchestrator
class OrchestratorConfig:
    THINKING_LEVEL: ThinkingLevel = "low"
    VERSION = os.environ.get("ORCHESTRATOR_VERSION", "2.0.1")
    # Label describing the environment the execution agents run their test cases against; reported
    # alongside every test execution result.
    TEST_ENVIRONMENT_LABEL = os.environ.get("TEST_ENVIRONMENT_LABEL", "Standard Test Environment")
    AUTOMATED_TC_LABEL = "automated"
    AGENTS_DISCOVERY_INTERVAL_SECONDS = 300
    AGENT_HEALTH_CHECK_INTERVAL_SECONDS = 60
    AGENT_HEALTH_CHECK_TIMEOUT_SECONDS = 10
    TASK_EXECUTION_TIMEOUT = 500.0
    AGENT_DISCOVERY_TIMEOUT_SECONDS = 120
    INCOMING_REQUEST_WAIT_TIMEOUT = AGENT_DISCOVERY_TIMEOUT_SECONDS + 5
    MODEL_NAME = DEFAULT_MODEL_NAME
    MAX_OUTPUT_TOKENS = _optional_positive_int("ORCHESTRATOR_MAX_OUTPUT_TOKENS") or MAX_OUTPUT_TOKENS
    API_KEY = os.environ.get("ORCHESTRATOR_API_KEY")
    AGENT_DISCOVERY_PORTS = os.environ.get("AGENT_DISCOVERY_PORTS", "8001-8007")
    REMOTE_EXECUTION_AGENT_HOSTS = os.environ.get("REMOTE_EXECUTION_AGENT_HOSTS", AGENT_BASE_URL)
    # Shared bearer token expected by the execution agents' main A2A endpoint. Empty means the agents run without
    # auth (e.g. local dev), so no Authorization header is attached.
    REMOTE_EXECUTION_AGENT_AUTH_TOKEN = os.environ.get("REMOTE_EXECUTION_AGENT_AUTH_TOKEN", "")


# Dashboard Authentication
class DashboardAuthConfig:
    """Configuration for UI dashboard authentication."""

    USERNAME = os.environ.get("DASHBOARD_USERNAME", "")
    PASSWORD_HASH = os.environ.get("DASHBOARD_PASSWORD_HASH", "")
    JWT_SECRET = os.environ.get("DASHBOARD_JWT_SECRET", "")
    JWT_ALGORITHM = "HS256"
    JWT_EXPIRE_HOURS = int(os.environ.get("DASHBOARD_JWT_EXPIRE_HOURS", "24"))
    LOGIN_RATE_LIMIT_ATTEMPTS = int(os.environ.get("LOGIN_RATE_LIMIT_ATTEMPTS", "5"))
    LOGIN_RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("LOGIN_RATE_LIMIT_WINDOW_SECONDS", "60"))
    LOGIN_RATE_LIMIT_TRUSTED_PROXY_HOPS = int(os.environ.get("LOGIN_RATE_LIMIT_TRUSTED_PROXY_HOPS", "0"))


class DashboardPersistenceConfig:
    """Optional durable backing store for dashboard history."""

    ENABLED = os.environ.get("DASHBOARD_PERSISTENCE_ENABLED", "false").lower() in ("true", "1", "t")
    COLLECTION_NAME = os.environ.get("QDRANT_DASHBOARD_COLLECTION_NAME", "dashboard_state")
    LOG_RETENTION_DAYS = int(os.environ.get("DASHBOARD_LOG_RETENTION_DAYS", "1"))
    HISTORY_RETENTION_DAYS = int(os.environ.get("DASHBOARD_HISTORY_RETENTION_DAYS", "7"))
    MAINTENANCE_INTERVAL_SECONDS = int(os.environ.get("DASHBOARD_MAINTENANCE_INTERVAL_SECONDS", "3600"))


# Requirements Review Agent
class RequirementsReviewAgentConfig:
    THINKING_LEVEL: ThinkingLevel = "medium"
    VERSION = os.environ.get("REQUIREMENTS_REVIEW_AGENT_VERSION", "1.1.2")
    OWN_NAME = "Jira Requirements Reviewer"
    SKILL_ID = "jira-requirements-review"
    SKILL_NAME = "Jira Requirements Review"
    SKILL_DESCRIPTION = "Review of requirements including Jira user stories, with attachments"
    PORT = int(os.environ.get("PORT", "8001"))
    EXTERNAL_PORT = int(os.environ.get("EXTERNAL_PORT", PORT))
    PROTOCOL = "http"
    MODEL_NAME = DEFAULT_MODEL_NAME
    MAX_OUTPUT_TOKENS = _optional_positive_int("REQUIREMENTS_REVIEW_MAX_OUTPUT_TOKENS") or MAX_OUTPUT_TOKENS
    MAX_REQUESTS_PER_TASK = 30


# Test Case Classification Agent
class TestCaseClassificationAgentConfig:
    THINKING_LEVEL: ThinkingLevel = "medium"
    VERSION = os.environ.get("TEST_CASE_CLASSIFICATION_AGENT_VERSION", "1.2.1")
    OWN_NAME = "Test Case Classification Agent"
    SKILL_ID = "test-case-classification"
    SKILL_NAME = "Test Case Classification"
    SKILL_DESCRIPTION = "Classification of test cases by type and automation capability"
    PORT = int(os.environ.get("PORT", "8003"))
    EXTERNAL_PORT = int(os.environ.get("EXTERNAL_PORT", PORT))
    PROTOCOL = "http"
    MODEL_NAME = DEFAULT_MODEL_NAME
    MAX_OUTPUT_TOKENS = _optional_positive_int("TEST_CASE_CLASSIFICATION_MAX_OUTPUT_TOKENS") or MAX_OUTPUT_TOKENS
    MAX_REQUESTS_PER_TASK = 30


# Test Case Generation Agent
class TestCaseGenerationAgentConfig:
    THINKING_LEVEL: ThinkingLevel = "medium"
    VERSION = os.environ.get("TEST_CASE_GENERATION_AGENT_VERSION", "1.2.1")
    OWN_NAME = "Test Case Generation Agent"
    SKILL_ID = "test-case-generation"
    SKILL_NAME = "Test Case Generation"
    SKILL_DESCRIPTION = "Generation of test cases based on Jira user stories and their acceptance criteria"
    PORT = int(os.environ.get("PORT", "8002"))
    EXTERNAL_PORT = int(os.environ.get("EXTERNAL_PORT", PORT))
    PROTOCOL = "http"
    MODEL_NAME = DEFAULT_MODEL_NAME
    MAX_OUTPUT_TOKENS = _optional_positive_int("TEST_CASE_GENERATION_MAX_OUTPUT_TOKENS") or MAX_OUTPUT_TOKENS
    MAX_REQUESTS_PER_TASK = 30


# Test Case Review Agent
class TestCaseReviewAgentConfig:
    THINKING_LEVEL: ThinkingLevel = "high"
    VERSION = os.environ.get("TEST_CASE_REVIEW_AGENT_VERSION", "1.1.2")
    REVIEW_COMPLETE_STATUS_NAME = "Review Complete"
    OWN_NAME = "Test Case Review Agent"
    SKILL_ID = "test-case-review"
    SKILL_NAME = "Test Case Review"
    SKILL_DESCRIPTION = "Review of generated test cases for coherence, redundancy, and effectiveness"
    PORT = int(os.environ.get("PORT", "8004"))
    EXTERNAL_PORT = int(os.environ.get("EXTERNAL_PORT", PORT))
    PROTOCOL = "http"
    MODEL_NAME = DEFAULT_MODEL_NAME
    MAX_OUTPUT_TOKENS = _optional_positive_int("TEST_CASE_REVIEW_MAX_OUTPUT_TOKENS") or MAX_OUTPUT_TOKENS
    MAX_REQUESTS_PER_TASK = 30


# Incident Creation Agent
class IncidentCreationAgentConfig:
    THINKING_LEVEL: ThinkingLevel = "medium"
    VERSION = os.environ.get("INCIDENT_CREATION_AGENT_VERSION", "1.1.1")
    OWN_NAME = "Incident Creation Agent"
    SKILL_ID = "incident-creation"
    SKILL_NAME = "Incident Creation"
    SKILL_DESCRIPTION = "Creation of detailed incident reports in Jira based on test execution results"
    PORT = int(os.environ.get("PORT", "8007"))
    EXTERNAL_PORT = int(os.environ.get("EXTERNAL_PORT", PORT))
    PROTOCOL = "http"
    MODEL_NAME = DEFAULT_MODEL_NAME
    MAX_OUTPUT_TOKENS = _optional_positive_int("INCIDENT_CREATION_MAX_OUTPUT_TOKENS") or MAX_OUTPUT_TOKENS
    MAX_REQUESTS_PER_TASK = 30
    MIN_SIMILARITY_SCORE = float(os.environ.get("INCIDENT_AGENT_MIN_SIMILARITY_SCORE", "0.7"))
    ISSUE_PRIORITY_FIELD_ID = os.environ.get("ISSUE_PRIORITY_FIELD_ID", "priority")
    ISSUE_SEVERITY_FIELD_NAME = os.environ.get("ISSUE_SEVERITY_FIELD_NAME", "customfield_10124")
    # Severity values: comma-separated list of "value:description" pairs
    SEVERITY_VALUES = os.environ.get(
        "INCIDENT_AGENT_SEVERITY_VALUES",
        "'10020':blocker or crash,'10021':functional failure,'10022':UI/UX issue,'10023':typo or minor visual issue",
    )
    # Priority values: comma-separated list of "value:description" pairs
    PRIORITY_VALUES = os.environ.get(
        "INCIDENT_AGENT_PRIORITY_VALUES", "High:immediate fix,Medium:normal release,Low:backlog"
    )
    # Jira statuses considered terminal — bugs in these statuses are excluded from duplicate detection
    TERMINAL_STATUSES = os.environ.get(
        "INCIDENT_AGENT_TERMINAL_STATUSES", "Closed,Done,Duplicate,Rejected,Won't Fix,Cannot Reproduce,Resolved"
    ).split(",")


class RetryConfig:
    MAX_RETRIES = 3
    RETRYABLE_STATUS_CODES = {404, 429, 500, 502, 503, 504}
    RETRY_BASE_DELAY_SECONDS = 5.0
    LLM_RESULTS_EXTRACTOR_RETRY_BASE_DELAY_SECONDS = 60.0


class QdrantConfig:
    # QDRANT_URL is authoritative and includes the port (or relies on the scheme default);
    # there is no separate port setting.
    URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
    API_KEY = os.environ.get("QDRANT_API_KEY")
    TIMEOUT_SECONDS = int(os.environ.get("QDRANT_TIMEOUT_SECONDS", "30"))
    COLLECTION_NAME = os.environ.get("QDRANT_COLLECTION_NAME", "jira_issues")
    TICKETS_COLLECTION_NAME = os.environ.get("QDRANT_TICKETS_COLLECTION_NAME", "jira_issues")
    METADATA_COLLECTION_NAME = os.environ.get("QDRANT_METADATA_COLLECTION_NAME", "rag_metadata")
    MIN_SIMILARITY_SCORE = float(os.environ.get("RAG_MIN_SIMILARITY_SCORE", "0.7"))
    MAX_RESULTS = int(os.environ.get("RAG_MAX_RESULTS", "5"))
    EMBEDDING_SERVICE_URL = os.environ.get("EMBEDDING_SERVICE_URL")
    EMBEDDING_SERVICE_TIMEOUT_SECONDS = float(os.environ.get("EMBEDDING_SERVICE_TIMEOUT_SECONDS", "120.0"))
    EMBEDDING_SERVICE_MAX_RETRIES = int(os.environ.get("EMBEDDING_SERVICE_MAX_RETRIES", "6"))
    EMBEDDING_SERVICE_RETRY_BACKOFF_CAP_SECONDS = float(
        os.environ.get("EMBEDDING_SERVICE_RETRY_BACKOFF_CAP_SECONDS", "32.0")
    )
    TEST_CASES_COLLECTION_NAME = os.environ.get("QDRANT_TEST_CASES_COLLECTION_NAME", "test_cases")
    CONFLUENCE_COLLECTION_NAME = os.environ.get("QDRANT_CONFLUENCE_COLLECTION_NAME", "confluence_documents")
    SHAREPOINT_COLLECTION_NAME = os.environ.get("QDRANT_SHAREPOINT_COLLECTION_NAME", "sharepoint_documents")
    TEST_CASE_INDEX_STATUSES = tuple(
        item.strip() for item in os.environ.get("TEST_CASE_INDEX_STATUSES", "").split(",") if item.strip()
    )
    TEST_CASE_DUPLICATE_MIN_SCORE = float(os.environ.get("TEST_CASE_DUPLICATE_MIN_SCORE", "0.8"))
    TEST_CASE_DUPLICATE_MAX_CANDIDATES = int(os.environ.get("TEST_CASE_DUPLICATE_MAX_CANDIDATES", "5"))
    BUG_ISSUE_TYPE = os.environ.get("JIRA_BUG_ISSUE_TYPE", "Bug")
    # Batch size for vector upserts, keeping requests within the size limit.
    UPSERT_BATCH_SIZE = int(os.environ.get("QDRANT_UPSERT_BATCH_SIZE", "64"))


class EmbeddingServiceConfig:
    """Configuration of the embedding service's backends.

    ``text`` is the only backend implemented; ``EMBEDDING_BACKENDS`` and the backend
    registry are the extension point for the ones that follow.
    """

    # Comma-separated enabled backends, e.g. "text" or "text,visual".
    BACKENDS = tuple(
        entry.strip() for entry in os.environ.get("EMBEDDING_BACKENDS", "text").split(",") if entry.strip()
    )
    # One multilingual model producing dense and learned-sparse output in a single pass.
    TEXT_MODEL_NAME = os.environ.get("EMBEDDING_TEXT_MODEL", "BAAI/bge-m3")
    # A pinned commit keeps a later upload to the model repository out of the image; it must belong to TEXT_MODEL_NAME.
    TEXT_MODEL_REVISION = os.environ.get("EMBEDDING_TEXT_MODEL_REVISION", "5617a9f61b028005a4858fdac845db406aefb181")
    # The repository also ships an ONNX export (~2.3 GB) and README images the service never loads.
    TEXT_MODEL_DOWNLOAD_IGNORE_PATTERNS = ("onnx/*", "imgs/*")
    TEXT_MODEL_PATH = os.path.join(LOCAL_MODELS_PATH, "embedding_model")
    # Input limits guarding against memory exhaustion.
    MAX_BATCH_SIZE = int(os.environ.get("EMBEDDING_MAX_BATCH_SIZE", "32"))
    MAX_TEXT_LENGTH = int(os.environ.get("EMBEDDING_MAX_TEXT_LENGTH", "50000"))


class RagSyncConfig:
    """RAG sync runtime, triggering, locks and cursors.

    Job mode is enabled by the Cloud Run job identity; local mode by the local sync
    service URL. When neither is configured the sync endpoints answer with an error
    naming the missing configuration.
    """

    # Cloud Run job resource name, e.g. projects/<p>/locations/<region>/jobs/<job>.
    JOB_NAME = os.environ.get("RAG_SYNC_JOB_NAME")
    JOB_REGION = os.environ.get("RAG_SYNC_JOB_REGION", "us-central1")
    # Local sync service URL (development/debug only); the orchestrator forwards requests to it.
    SERVICE_URL = os.environ.get("RAG_SYNC_SERVICE_URL")
    # Duration bound of one job task; task retries stay 0 (the next scheduled call retries).
    JOB_TASK_TIMEOUT_SECONDS = int(os.environ.get("RAG_SYNC_JOB_TASK_TIMEOUT_SECONDS", "3600"))
    # Lock expiry. Defaults to the task timeout plus a safety margin, so a live job never
    # outlives its lock and a crashed job frees the scope after the TTL.
    LOCK_TTL_SECONDS = int(os.environ.get("RAG_SYNC_LOCK_TTL_SECONDS", str(JOB_TASK_TIMEOUT_SECONDS + 300)))
    # How long an unconfirmed job start keeps the lock before the next request may take over.
    START_ALLOWANCE_SECONDS = int(os.environ.get("RAG_SYNC_START_ALLOWANCE_SECONDS", "300"))
    CALLBACK_URL = os.environ.get("SYNC_CALLBACK_ORCHESTRATOR_URL")


class SharePointConfig:
    """Microsoft Graph app-only access for the SharePoint document-library ingestion.

    The least-privilege setup grants the ``Sites.Selected`` application permission to the
    app for the specific sites; ``Files.Read.All`` is the tenant-wide fallback.
    """

    TENANT_ID = os.environ.get("SHAREPOINT_TENANT_ID")
    CLIENT_ID = os.environ.get("SHAREPOINT_CLIENT_ID")
    CLIENT_SECRET = os.environ.get("SHAREPOINT_CLIENT_SECRET")
    # Both overridable so a mocked Graph endpoint serves the token request and the Graph calls (smoke).
    AUTHORITY_URL = os.environ.get("SHAREPOINT_AUTHORITY_URL", "https://login.microsoftonline.com")
    GRAPH_BASE_URL = os.environ.get("SHAREPOINT_GRAPH_BASE_URL", "https://graph.microsoft.com/v1.0")


class DocumentRagConfig:
    """Confluence document ingestion and the documents collection.

    The chunk token budget uses a conservative character-based estimate (four
    characters per token), which stays safe while the budget is far below the
    embedding model's maximum input length.
    """

    # Documents collection holding page-body chunks and attachment page parts.
    DOCUMENTS_COLLECTION_NAME = QdrantConfig.CONFLUENCE_COLLECTION_NAME
    CONFLUENCE_RETRIEVAL_ENABLED = os.environ.get("CONFLUENCE_RETRIEVAL_ENABLED", "false").lower() in ("true", "1", "t")
    SHAREPOINT_RETRIEVAL_ENABLED = os.environ.get("SHAREPOINT_RETRIEVAL_ENABLED", "false").lower() in ("true", "1", "t")
    # Confluence REST v2 page size for listing calls.
    LIST_PAGE_SIZE = int(os.environ.get("RAG_CONFLUENCE_LIST_PAGE_SIZE", "50"))
    # Retries for Confluence 429/5xx responses, honouring Retry-After.
    CONFLUENCE_MAX_RETRIES = int(os.environ.get("RAG_CONFLUENCE_MAX_RETRIES", "5"))
    CONFLUENCE_TIMEOUT_SECONDS = float(os.environ.get("RAG_CONFLUENCE_TIMEOUT_SECONDS", "30"))
    # Chunk token budget for page bodies, breadcrumb included; 1 token ~ 4 characters.
    CHUNK_MAX_TOKENS = int(os.environ.get("RAG_CHUNK_MAX_TOKENS", "512"))
    CHARACTERS_PER_TOKEN = 4

    # --- Attachment ingestion ---
    # Checked against the listed size before any download. The default matches the
    # current Gemini API inline-data limit.
    MAX_ATTACHMENT_BYTES = int(os.environ.get("RAG_MAX_ATTACHMENT_BYTES", str(100 * 1024 * 1024)))
    # Hard cap on rendered/ingested pages per document; pages beyond it are skipped
    # and the true total page count is still recorded.
    MAX_PAGES_PER_DOCUMENT = int(os.environ.get("RAG_MAX_PAGES_PER_DOCUMENT", "200"))
    # Render resolution for PDF page rasterization.
    RENDER_DPI = int(os.environ.get("RAG_RENDER_DPI", "150"))
    # Maximum pixel dimension of a normalized page image (decompression-bomb guard).
    MAX_IMAGE_DIMENSION = int(os.environ.get("RAG_MAX_IMAGE_DIMENSION", "4096"))
    # Headless LibreOffice conversion of office formats to PDF. When disabled or the
    # binary is missing, formats that need conversion are skipped with a warning.
    OFFICE_CONVERSION_ENABLED = os.environ.get("RAG_OFFICE_CONVERSION_ENABLED", "true").lower() in ("true", "1", "t")
    OFFICE_CONVERSION_TIMEOUT_SECONDS = int(os.environ.get("RAG_OFFICE_CONVERSION_TIMEOUT_SECONDS", "120"))
    # Bounded concurrent LibreOffice invocations (it dislikes parallel profiles).
    OFFICE_CONVERSION_CONCURRENCY = int(os.environ.get("RAG_OFFICE_CONVERSION_CONCURRENCY", "1"))
    # A page with native text below this many characters counts as image-only (full-page OCR).
    OCR_TEXT_THRESHOLD_CHARACTERS = int(os.environ.get("RAG_OCR_TEXT_THRESHOLD_CHARACTERS", "20"))
