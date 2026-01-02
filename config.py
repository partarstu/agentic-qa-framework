# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

"""
Centralized configuration for the application.
"""

from dotenv import load_dotenv
import os

load_dotenv()

# Logging
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()
GOOGLE_CLOUD_LOGGING_ENABLED = os.environ.get("GOOGLE_CLOUD_LOGGING_ENABLED", "False").lower() in ("true", "1", "t")

# URLs
ORCHESTRATOR_HOST = os.environ.get("ORCHESTRATOR_HOST", "localhost")
ORCHESTRATOR_PORT = int(os.environ.get("ORCHESTRATOR_PORT", "8000"))
ORCHESTRATOR_URL = os.environ.get("ORCHESTRATOR_URL", f"http://{ORCHESTRATOR_HOST}:{ORCHESTRATOR_PORT}")
JIRA_MCP_SERVER_URL = os.environ.get("JIRA_MCP_SERVER_URL", "http://localhost:9000/sse")
ZEPHYR_BASE_URL = os.environ.get("ZEPHYR_BASE_URL")
JIRA_BASE_URL = os.environ.get("JIRA_URL")
JIRA_USER = os.environ.get("JIRA_USERNAME")
JIRA_TOKEN = os.environ.get("JIRA_API_TOKEN")

# Webhook URLs
NEW_REQUIREMENTS_WEBHOOK_URL = f"{ORCHESTRATOR_URL}/new-requirements-available"
STORY_READY_FOR_TEST_CASE_GENERATION_WEBHOOK_URL = f"{ORCHESTRATOR_URL}/story-ready-for-test-case-generation"
EXECUTE_TESTS_WEBHOOK_URL = f"{ORCHESTRATOR_URL}/execute-tests"
UPDATE_RAG_DB_WEBHOOK_URL = f"{ORCHESTRATOR_URL}/update-rag-db"

# Secrets
JIRA_WEBHOOK_SECRET = os.environ.get("JIRA_WEBHOOK_SECRET")
ZEPHYR_API_TOKEN = os.environ.get("ZEPHYR_API_TOKEN")

XRAY_BASE_URL = os.environ.get("XRAY_BASE_URL")
XRAY_CLIENT_ID = os.environ.get("XRAY_CLIENT_ID")
XRAY_CLIENT_SECRET = os.environ.get("XRAY_CLIENT_SECRET")
XRAY_PRECONDITIONS_FIELD_ID = os.environ.get("XRAY_PRECONDITIONS_FIELD_ID", "Pre-conditions")

# Agent
AGENT_BASE_URL = os.environ.get("AGENT_BASE_URL", "http://localhost")
MCP_SERVER_ATTACHMENTS_FOLDER_PATH = "/tmp"
ATTACHMENTS_DESTINATION_FOLDER_PATH = "D://temp"
REMOTE_EXECUTION_AGENT_HOSTS = os.environ.get("REMOTE_EXECUTION_AGENT_HOSTS", AGENT_BASE_URL)
AGENT_DISCOVERY_PORTS = os.environ.get("AGENT_DISCOVERY_PORTS", "8001-8007")
USE_GOOGLE_CLOUD_STORAGE = os.environ.get("USE_CLOUD_STORAGE", "False").lower() in ("true", "1", "t")
GOOGLE_CLOUD_STORAGE_BUCKET_NAME = os.environ.get("CLOUD_STORAGE_BUCKET_NAME")
JIRA_ATTACHMENTS_CLOUD_STORAGE_FOLDER = os.environ.get("JIRA_ATTACHMENTS_CLOUD_STORAGE_FOLDER", "jira")
MCP_SERVER_TIMEOUT_SECONDS = 30

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
OPEN_TELEMETRY_URL = os.environ.get('OTEL_EXPORTER_OTLP_ENDPOINT')

# Common model config
TOP_P = 1.0
TEMPERATURE = 0.0

# Prompt injection detection config
PROMPT_INJECTION_CHECK_ENABLED = os.environ.get("PROMPT_INJECTION_CHECK_ENABLED", "False").lower() in ("true", "1", "t")
PROMPT_GUARD_PROVIDER = os.environ.get("PROMPT_GUARD_PROVIDER", "protect_ai")
PROMPT_INJECTION_MIN_SCORE = float(os.environ.get("PROMPT_INJECTION_MIN_SCORE", "0.8"))
LOCAL_MODELS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "local_models")
PROMPT_INJECTION_DETECTION_MODEL_PATH = os.path.join(LOCAL_MODELS_PATH, "prompt_detection_model")
PROMPT_INJECTION_DETECTION_MODEL_NAME = os.environ.get("PROMPT_INJECTION_MODEL_NAME", "ProtectAI/deberta-v3-base-prompt-injection-v2")


# Orchestrator
class OrchestratorConfig:
    AUTOMATED_TC_LABEL = "automated"
    AGENTS_DISCOVERY_INTERVAL_SECONDS = 300
    TASK_EXECUTION_TIMEOUT = 500.0
    AGENT_DISCOVERY_TIMEOUT_SECONDS = 120
    INCOMING_REQUEST_WAIT_TIMEOUT = AGENT_DISCOVERY_TIMEOUT_SECONDS + 5
    MODEL_NAME = "google-gla:gemini-3-flash-preview"
    API_KEY = os.environ.get("ORCHESTRATOR_API_KEY")


# Requirements Review Agent
class RequirementsReviewAgentConfig:
    THINKING_BUDGET = 5000
    OWN_NAME = "Jira Requirements Reviewer"
    PORT = int(os.environ.get("PORT", "8001"))
    EXTERNAL_PORT = int(os.environ.get("EXTERNAL_PORT", PORT))
    PROTOCOL = "http"
    MODEL_NAME = "google-gla:gemini-3-flash-preview"
    MAX_REQUESTS_PER_TASK = 10


# Test Case Classification Agent
class TestCaseClassificationAgentConfig:
    THINKING_BUDGET = 2000
    OWN_NAME = "Test Case Classification Agent"
    PORT = int(os.environ.get("PORT", "8003"))
    EXTERNAL_PORT = int(os.environ.get("EXTERNAL_PORT", PORT))
    PROTOCOL = "http"
    MODEL_NAME = "google-gla:gemini-3-flash-preview"
    MAX_REQUESTS_PER_TASK = 5


# Test Case Generation Agent
class TestCaseGenerationAgentConfig:
    THINKING_BUDGET = 0
    OWN_NAME = "Test Case Generation Agent"
    PORT = int(os.environ.get("PORT", "8002"))
    EXTERNAL_PORT = int(os.environ.get("EXTERNAL_PORT", PORT))
    PROTOCOL = "http"
    MODEL_NAME = "google-gla:gemini-3-flash-preview"
    MAX_REQUESTS_PER_TASK = 10


# Test Case Review Agent
class TestCaseReviewAgentConfig:
    THINKING_BUDGET = 5000
    REVIEW_COMPLETE_STATUS_NAME = "Review Complete"
    OWN_NAME = "Test Case Review Agent"
    PORT = int(os.environ.get("PORT", "8004"))
    EXTERNAL_PORT = int(os.environ.get("EXTERNAL_PORT", PORT))
    PROTOCOL = "http"
    MODEL_NAME = "google-gla:gemini-3-flash-preview"
    MAX_REQUESTS_PER_TASK = 5


# Incident Creation Agent
class IncidentCreationAgentConfig:
    THINKING_BUDGET = 5000
    OWN_NAME = "Incident Creation Agent"
    PORT = int(os.environ.get("PORT", "8007"))
    EXTERNAL_PORT = int(os.environ.get("EXTERNAL_PORT", PORT))
    PROTOCOL = "http"
    MODEL_NAME = "google-gla:gemini-3-flash-preview"
    MAX_REQUESTS_PER_TASK = 10
    MIN_SIMILARITY_SCORE = float(os.environ.get("INCIDENT_AGENT_MIN_SIMILARITY_SCORE", "0.7"))
    ISSUE_PRIORITY_FIELD_ID = os.environ.get("ISSUE_PRIORITY_FIELD_ID", "priority")
    ISSUE_SEVERITY_FIELD_NAME = os.environ.get("ISSUE_SEVERITY_FIELD_NAME", "customfield_10124")
    # Severity values: comma-separated list of "value:description" pairs
    SEVERITY_VALUES = os.environ.get(
        "INCIDENT_AGENT_SEVERITY_VALUES",
        "'10020':blocker or crash,'10021':functional failure,'10022':UI/UX issue,'10023':typo or minor visual issue"
    )
    # Priority values: comma-separated list of "value:description" pairs
    PRIORITY_VALUES = os.environ.get(
        "INCIDENT_AGENT_PRIORITY_VALUES",
        "High:immediate fix,Medium:normal release,Low:backlog"
    )


# RAG Update Agent
class JiraRagUpdateAgentConfig:
    THINKING_BUDGET = 2000
    OWN_NAME = "Jira RAG Update Agent"
    PORT = int(os.environ.get("PORT", "8006"))
    EXTERNAL_PORT = int(os.environ.get("EXTERNAL_PORT", PORT))
    PROTOCOL = "http"
    MODEL_NAME = "google-gla:gemini-3-flash-preview"
    MAX_REQUESTS_PER_TASK = 10


class QdrantConfig:
    URL = os.environ.get("QDRANT_URL", "http://localhost")
    API_KEY = os.environ.get("QDRANT_API_KEY")
    TIMEOUT_SECONDS = float(os.environ.get("QDRANT_TIMEOUT_SECONDS", "30.0"))
    PORT = int(os.environ.get("QDRANT_PORT", "6333"))
    COLLECTION_NAME = os.environ.get("QDRANT_COLLECTION_NAME", "jira_issues")
    TICKETS_COLLECTION_NAME = os.environ.get("QDRANT_TICKETS_COLLECTION_NAME", "jira_issues")
    METADATA_COLLECTION_NAME = os.environ.get("QDRANT_METADATA_COLLECTION_NAME", "rag_metadata")
    MIN_SIMILARITY_SCORE = float(os.environ.get("RAG_MIN_SIMILARITY_SCORE", "0.7"))
    MAX_RESULTS = int(os.environ.get("RAG_MAX_RESULTS", "5"))
    EMBEDDING_MODEL = os.environ.get("RAG_EMBEDDING_MODEL", "jinaai/jina-embeddings-v3")
    EMBEDDING_MODEL_PATH = os.path.join(LOCAL_MODELS_PATH, "embedding_model")
    EMBEDDING_SERVICE_URL = os.environ.get("EMBEDDING_SERVICE_URL")
    EMBEDDING_SERVICE_TIMEOUT_SECONDS = float(os.environ.get("EMBEDDING_SERVICE_TIMEOUT_SECONDS", "30.0"))
    VALID_STATUSES = os.environ.get("JIRA_VALID_STATUSES", "To Do,In Progress,Done").split(",")
    BUG_ISSUE_TYPE = os.environ.get("JIRA_BUG_ISSUE_TYPE", "Bug")
