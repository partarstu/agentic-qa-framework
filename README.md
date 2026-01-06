# Agentic QA Framework

A framework for building and orchestrating AI agents, focusing on automating software testing processes starting with
software requirements review and up to generating test execution reports.

The corresponding article on Medium can be
found [here](https://medium.com/@partarstu/the-next-evolution-in-software-testing-from-automation-to-autonomy-1bd7767802e1).

## Demo

Watch a demo of the project in action:

[Agentic QA Framework Demo](https://youtu.be/jd8s0fLdxLA)

## Features

* **Modular Agent Architecture:** Includes specialized agents for:
    * Requirements Review
    * Test Case Generation
    * Test Case Classification
    * Test Case Review
    * UI Test Execution
    * Incident Creation (automatic bug reporting for failed tests)
    * Jira RAG Update (vector database synchronization for semantic search)
* **Prompt Injection Protection:** Built-in safeguards to detect and prevent prompt injection attacks.
* **A2A and MCP - compliant:** Adheres to the specifications of Agent2Agent and Model Context protocols.
* **Orchestration Layer:** A central orchestrator manages agent registration, task routing, and workflow execution.
* **Integration with External Systems:** Supports integration with Jira by utilizing its MCP server.
* **Vector Database Integration:** Uses Qdrant for semantic search capabilities, enabling intelligent duplicate detection and RAG-based features.
* **Embedding Service:** Dedicated microservice for generating text embeddings using SentenceTransformer models.
* **Test Management System Integration:** Integrates with Zephyr for operations related to test case management.
* **Test Reporting:** Generates detailed Allure reports for test execution results.
* **Extensible:** Designed for easy addition of new agents, tools, and integrations.

## Architecture

The orchestrator acts as the central hub, managing the lifecycle and interactions of various specialized agents. Agents
expose details about their capabilities to the orchestrator and allow it to identify the tasks they can handle.

When an event occurs (e.g., a Jira webhook indicating new requirements), the orchestrator:

1. Receives the event.
2. Identifies the appropriate agent(s) based on the task description and registered agent capabilities.
3. Routes the task to the selected agent(s).
4. Monitors the task execution and collects results.
5. Triggers subsequent agents or workflows as needed (e.g., after test case generation, trigger test case
   classification).

For a visual representation of the system's architecture and data flow, please refer to the following diagrams:

* [Architectural Diagram](architectural_diagram.html) ([German Version](architectural_diagram_DE.html))
* [Flow Diagram](flow_diagram.html) ([German Version](flow_diagram_DE.html))

## Getting Started

### Prerequisites

* Python 3.13+
* Docker
* `pip` (Python package installer)
* `virtualenv` (or `conda` for environment management)

### Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/partarstu/agentic-qa-framework.git
   cd agentic-qa-framework
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

### Docker Images

The project utilizes Docker for containerization of the orchestrator and agent services. A common base image, `agentic-qa-base:latest`, is built from `Dockerfile.base` to ensure consistency and reduce build times.

Each service runs using `gunicorn` as the WSGI server. The command for agents is
`gunicorn -w 1 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT agents.<agent_name>.main:app`, and for the
orchestrator, it is `gunicorn -w 1 -k uvicorn.workers.UvicornWorker orchestrator.main:orchestrator_app`. Note that
`$PORT` refers to the internal port the agent listens on, while the `AgentCard` will use the `EXTERNAL_PORT` for its
URL.

### Environment Variables

Create a `.env` file in the project root and configure the following environment variables. These variables control the
behavior of the orchestrator and agents.

```
# Logging
LOG_LEVEL=INFO # Default: INFO. Controls the verbosity of logging.
GOOGLE_CLOUD_LOGGING_ENABLED=False # Default: False. Set to "True" to enable Google Cloud Logging.

# Orchestrator
ORCHESTRATOR_HOST=localhost # Default: localhost. The host where the orchestrator runs.
ORCHESTRATOR_PORT=8000 # Default: 8000. The port the orchestrator listens on.
ORCHESTRATOR_URL=http://localhost:8000 # Default: http://localhost:8000. The full URL of the orchestrator.
ORCHESTRATOR_API_KEY=YOUR_ORCHESTRATOR_API_KEY # Optional. Set this to activate API key authentication for the orchestrator.
                                 # If set, requests to the orchestrator must include an 'X-API-Key' header with this value.
                                 # This corresponds to OrchestratorConfig.API_KEY.
JIRA_MCP_SERVER_URL=http://localhost:9000/sse # Default: http://localhost:9000/sse. The URL of the Jira MCP server.

# Dashboard Authentication
# These settings control access to the UI monitoring dashboard at /api/dashboard/*
DASHBOARD_USERNAME=admin # Default: admin. Username for dashboard login.
DASHBOARD_PASSWORD=admin # Default: admin. Password for dashboard login. CHANGE THIS IN PRODUCTION!
DASHBOARD_JWT_SECRET=change-me-in-production-please # Default: change-me-in-production-please. Secret key for JWT token signing. CHANGE THIS IN PRODUCTION!
DASHBOARD_JWT_EXPIRE_HOURS=24 # Default: 24. Number of hours before JWT tokens expire.

# Zephyr Test Management System
ZEPHYR_BASE_URL=YOUR_ZEPHYR_BASE_URL # Required. The base URL of your Zephyr instance.
ZEPHYR_API_TOKEN=YOUR_ZEPHYR_API_TOKEN # Required. API token for Zephyr authentication.

# Agent Configuration
AGENT_BASE_URL=http://localhost # Default: http://localhost. Base URL for agents.
PORT=8001 # Default: 8001. The internal port an agent listens on.
EXTERNAL_PORT=8001 # Default: 8001. The externally accessible port for the agent.

# Agent Discovery (for remote agents)
REMOTE_EXECUTION_AGENT_HOSTS=http://localhost # Default: http://localhost. Comma-separated URLs of remote agent hosts.
AGENT_DISCOVERY_PORTS=8001-8007 # Default: 8001-8007. Port range for agent discovery.

# Google Cloud Storage (via Volume Mounts)
# In cloud deployments, GCS buckets are mounted as local folders via Cloud Run volume mounts.
# The following variables configure the local paths where attachments are accessed:
ATTACHMENTS_LOCAL_DESTINATION_FOLDER_PATH=/tmp # Default: /tmp. Path where attachments are read from.
MCP_SERVER_ATTACHMENTS_FOLDER_PATH=/tmp # Default: /tmp. Path where MCP server stores attachments.
JIRA_ATTACHMENT_SKIP_POSTFIX=_SKIP # Default: _SKIP. Attachments with filenames ending in this postfix (before the extension) 
                                   # will be excluded from agent analysis. Case-insensitive. Example: "mockup_SKIP.png" is skipped.

# OpenTelemetry (for tracing and metrics)
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 # Default: http://localhost:4317. Endpoint for OpenTelemetry collector.

# Test Management System
TEST_MANAGEMENT_SYSTEM=zephyr # Default: zephyr. Specifies the test management system in use.

# Test Reporting
TEST_REPORTER=allure # Default: allure. Specifies the test reporting tool.
ALLURE_RESULTS_DIR=allure-results # Default: allure-results. Directory for Allure test results.
ALLURE_REPORT_DIR=allure-report # Default: allure-report. Directory for generated Allure reports.

# Common Model Configuration
TOP_P=1.0 # Default: 1.0. Top-p sampling parameter for models.
TEMPERATURE=0.0 # Default: 0.0. Temperature parameter for models.

# Qdrant Vector Database (for RAG and semantic search)
QDRANT_URL=http://localhost # Default: http://localhost. URL of the Qdrant server.
QDRANT_PORT=6333 # Default: 6333. Port of the Qdrant server.
QDRANT_API_KEY= # Optional. API key for Qdrant authentication.
QDRANT_COLLECTION_NAME=jira_issues # Default: jira_issues. Name of the main collection for Jira issues.
QDRANT_METADATA_COLLECTION_NAME=rag_metadata # Default: rag_metadata. Name of the collection for RAG metadata.
RAG_MIN_SIMILARITY_SCORE=0.7 # Default: 0.7. Minimum similarity score for vector search results.
RAG_MAX_RESULTS=5 # Default: 5. Maximum number of results to return from vector search.
RAG_EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B # Default: Qwen/Qwen3-Embedding-0.6B. SentenceTransformer model for embeddings.
EMBEDDING_SERVICE_URL= # Optional. URL of the embedding service for remote embedding generation.
EMBEDDING_SERVICE_TIMEOUT_SECONDS=60.0 # Default: 60.0. Timeout for embedding service requests.

# Incident Creation Agent Configuration
INCIDENT_AGENT_MIN_SIMILARITY_SCORE=0.7 # Default: 0.7. Minimum score for duplicate detection.
ISSUE_PRIORITY_FIELD_ID=priority # Default: priority. Jira field ID for issue priority.
ISSUE_SEVERITY_FIELD_NAME=customfield_10124 # Default: customfield_10124. Jira custom field name for severity.

# Prompt Injection Detection
PROMPT_INJECTION_CHECK_ENABLED=False # Default: False. Set to "True" to enable prompt injection detection.
PROMPT_GUARD_PROVIDER=protect_ai # Default: protect_ai. The provider for prompt injection detection.
PROMPT_INJECTION_MIN_SCORE=0.8 # Default: 0.8. The minimum score for a prompt to be considered an injection.
PROMPT_INJECTION_MODEL_NAME=ProtectAI/deberta-v3-base-prompt-injection-v2 # Default: ProtectAI/deberta-v3-base-prompt-injection-v2. The name of the model used for prompt injection detection.

**Note on Local Models:**
If you are running the orchestrator or agents locally (not in a Docker container deployed to the cloud), you must manually download the necessary models:
1. **Prompt Injection Detection Model:** Required if `PROMPT_INJECTION_CHECK_ENABLED` is set to `True`. Run `scripts/download_prompt_guard_model.py`.
2. **Embedding Model:** Required for agents using Vector DB (e.g. Incident Creation, Jira RAG Update) and Orchestrator. Run `scripts/download_embedding_model.py`.

When deploying to cloud environments via Docker, the model downloads are handled automatically as part of the Docker image build process.
# Specific Agent Model Names (example values, adjust as needed)
# These specify the AI model to be used by each component.
# Refer to your model provider's documentation for available model names.
ORCHESTRATOR_MODEL_NAME=google-gla:gemini-2.5-flash
REQUIREMENTS_REVIEW_AGENT_MODEL_NAME=google-gla:gemini-2.5-pro
TEST_CASE_CLASSIFICATION_AGENT_MODEL_NAME=google-gla:gemini-2.5-flash
TEST_CASE_GENERATION_AGENT_MODEL_NAME=google-gla:gemini-2.5-flash
INCIDENT_CREATION_AGENT_MODEL_NAME=google-gla:gemini-2.5-flash
JIRA_RAG_UPDATE_AGENT_MODEL_NAME=google-gla:gemini-2.5-flash
TEST_CASE_REVIEW_AGENT_MODEL_NAME=google-gla:gemini-2.5-pro
```

### Jira MCP Server Setup

The Agentic Framework integrates with Jira via a Model Context Protocol (MCP) server. This server acts as an
intermediary, handling communication between Jira webhooks and the orchestrator.

To run the Jira MCP server, you will need Docker installed.

1. **Create a `.env` file for the MCP server:**
   The MCP server uses its own `.env` file for configuration. Create a file named `.env` in the `mcp/jira/` directory
   with the following content:

   ```
   JIRA_URL=YOUR_JIRA_INSTANCE_URL
   JIRA_API_TOKEN=YOUR_JIRA_API_TOKEN
   JIRA_USERNAME=YOUR_JIRA_USERNAME   
   ```
    * `JIRA_URL`: The base URL of your Jira instance (e.g., `https://your-company.atlassian.net`).
    * `JIRA_API_TOKEN`: A Jira API token for authentication. You can generate one in your Atlassian account settings.
    * `JIRA_USERNAME`: The email address associated with your Jira account.

2. **Run the MCP Server using Docker:**
   Navigate to the `mcp/jira/` directory and execute the `start_mcp_server.bat` script (valid only for Windows
   platform):

   ```bash
   cd mcp/jira
   start_mcp_server.bat
   ```
   This command will start the Docker container for the MCP server, mapping port `9000` on your host to the container's
   port `9000`. It also mounts a local directory (`D:\temp` in the example, corresponding to
   `ATTACHMENTS_LOCAL_DESTINATION_FOLDER_PATH` in your main `.env` file) to `/tmp` inside the container (corresponding to
   `MCP_SERVER_ATTACHMENTS_FOLDER_PATH`). Ensure this local directory exists and has appropriate permissions. Such an
   approach is needed because the current implementation of Jira MCP server only downloads the attachments locally on
   the server and doesn't transfer them to the agent. That's why those downloaded attachments need to be retrieved and
   volume mapping is the current solution for that. Within the cloud setup, a cloud storage could be mapped to the
   docker
   container and then downloaded attachments could be retrieved by the agent from the cloud storage.

### Starting agents locally

1. **Start Qdrant Vector Database (required for RAG features):**
   The Incident Creation and Jira RAG Update agents require a running Qdrant instance for vector database operations.
   ```bash
   scripts/start_qdrant.bat
   ```
   This script will start Qdrant in a Docker container on port 6333.

2. **Start the Embedding Service (optional):**
   If you want to use a dedicated embedding service instead of loading the model in each agent:
   ```bash
   python services/embedding_service/main.py
   ```

3. **Start Individual Agents:**
   Open separate terminal windows for each agent you want to run:

    * **Requirements Review Agent:**
      ```bash
      python agents/requirements_review/main.py
      ```
    * **Test Case Generation Agent:**
      ```bash
      python agents/test_case_generation/main.py
      ```
    * **Test Case Classification Agent:**
      ```bash
      python agents/test_case_classification/main.py
      ```
    * **Test Case Review Agent:**
      ```bash
      python agents/test_case_review/main.py
      ```
    * **Incident Creation Agent:**
      ```bash
      python agents/incident_creation/main.py
      ```
    * **Jira RAG Update Agent:**
      ```bash
      python agents/jira_rag/main.py
      ```

4. **Start the Orchestrator:**
   ```bash
   python orchestrator/main.py
   ```

### Deployment to Google Cloud Run

This project is already configured for deployment to Google Cloud Run. The `cloudbuild.yaml` file orchestrates the
building of Docker images and their deployment as separate services. You need to have the gcloud CLI installed before
you run any of the commands below.

#### Preconditions:

1. Existing VPC network. This one can be created with the following commands:
    ```bash
   gcloud compute networks create agent-network --subnet-mode=custom
   gcloud compute networks subnets create SUBNET_NAME --network=NETWORK_NAME --range=IP_RANGE --region=REGION
    ```
   The target subnetwork network also must have Private Google Access activated so that agents running in Google Cloud
   Run could reach
   other agents which have "internal" ingress (basically all agents have it except orchestrator).
2. Access to the Secrets Manager. This one can be created with the following command:
    ```bash
   gcloud projects add-iam-policy-binding <project_id> --member="serviceAccount:<project_number>-compute@developer.gserviceaccount.com" --role="roles/secretmanager.secretAccessor" 
    ```
3. Cloud NAT in order to route requests from the VPC network out to the internet. This one can be created with the
   following commands:
    ```bash
   gcloud compute routers create ROUTER_NAME --network=NETWORK_NAME --region=REGION
   gcloud compute routers nats create NAT_GATEWAY_NAME --router=ROUTER_NAME --region=REGION --nat-all-subnet-ip-ranges 
    ```
4. The following **secrets in the Google Secrets Manager** with corresponding values need to be added:
    * `GOOGLE_API_KEY`
    * `JIRA_API_TOKEN`
    * `JIRA_USERNAME`
    * `JIRA_URL`
    * `ZEPHYR_API_TOKEN`
    * `ZEPHYR_BASE_URL`
    * `JIRA_MCP_SERVER_URL`
    * `ORCHESTRATOR_API_KEY`
5. Cloud Storage bucket for general operations (with all needed folders created, see "Substitution Variables").
6. Cloud Storage bucket for storing and publicly serving test execution reports (this bucket needs to have public
   access)

#### Deployment:

After having all preconditions fulfilled, you can execute the following command:

```bash
gcloud builds submit --config 'path/to/your/cloudbuild.yaml' --substitutions "^;^_BUCKET_NAME=YOUR_GCS_BUCKET_NAME;_ALLURE_REPORTS_BUCKET=YOUR_ALLURE_REPORTS_BUCKET_NAME;_REQUIREMENTS_REVIEW_AGENT_BASE_URL=YOUR_REQUIREMENTS_REVIEW_AGENT_URL;_TEST_CASE_GENERATION_AGENT_BASE_URL=YOUR_TEST_CASE_GENERATION_AGENT_URL;_TEST_CASE_CLASSIFICATION_AGENT_BASE_URL=YOUR_TEST_CASE_CLASSIFICATION_AGENT_URL;_TEST_CASE_REVIEW_AGENT_BASE_URL=YOUR_TEST_CASE_REVIEW_AGENT_URL;_REMOTE_EXECUTION_AGENT_HOSTS=YOUR_COMMA_SEPARATED_AGENT_HOSTS" .
```

```powershell
gcloud builds submit --config 'path/to/your/cloudbuild.yaml' --substitutions "`^;`^_BUCKET_NAME=YOUR_GCS_BUCKET_NAME;_ALLURE_REPORTS_BUCKET=YOUR_ALLURE_REPORTS_BUCKET_NAME;_REQUIREMENTS_REVIEW_AGENT_BASE_URL=YOUR_REQUIREMENTS_REVIEW_AGENT_URL;_TEST_CASE_GENERATION_AGENT_BASE_URL=YOUR_TEST_CASE_GENERATION_AGENT_URL;_TEST_CASE_CLASSIFICATION_AGENT_BASE_URL=YOUR_TEST_CASE_CLASSIFICATION_AGENT_URL;_TEST_CASE_REVIEW_AGENT_BASE_URL=YOUR_TEST_CASE_REVIEW_AGENT_URL;_REMOTE_EXECUTION_AGENT_HOSTS=YOUR_COMMA_SEPARATED_AGENT_HOSTS" .
```

**Substitution Variables:**
* `_BUCKET_NAME`: The name of the Google Cloud Storage bucket used for storing attachments downloaded by Jira MCP
  server.
* `_JIRA_ATTACHMENTS_FOLDER`: The name of the folder where attachments from Jira MCP server will be saved, must be the
  same as 'JIRA_ATTACHMENTS_CLOUD_STORAGE_FOLDER' environment variable
* `_ALLURE_REPORTS_BUCKET`: The GCS bucket where test execution HTML reports will be stored.
* `_REQUIREMENTS_REVIEW_AGENT_BASE_URL`: The URL of the deployed Requirements Review Agent.
* `_TEST_CASE_GENERATION_AGENT_BASE_URL`: The URL of the deployed Test Case Generation Agent.
* `_TEST_CASE_CLASSIFICATION_AGENT_BASE_URL`: The URL of the deployed Test Case Classification Agent.
* `_TEST_CASE_REVIEW_AGENT_BASE_URL`: The URL of the deployed Test Case Review Agent.
* `_INCIDENT_CREATION_AGENT_BASE_URL`: The URL of the deployed Incident Creation Agent.
* `_JIRA_RAG_UPDATE_AGENT_BASE_URL`: The URL of the deployed Jira RAG Update Agent.
* `_REMOTE_EXECUTION_AGENT_HOSTS`: A comma-separated list of URLs for all deployed agents that the orchestrator will
  interact with.

**Important**: Before the initial deployment of the framework into Google Cloud Run it's quite hard to know which URL
will be assigned to each agent and orchestrator. That's why most probably you'll have to run the deployment command
once, then identify the assigned URL of each service, update the substitution values in the command and run it again.

## Invoking Orchestrator Workflows

### Triggering Workflows via Jira Webhooks

The orchestrator listens for webhooks from Jira or CI/CD systems to initiate automated workflows.

* **New Requirements Available (Requirements Review):**
  Send a POST request to `/new-requirements-available` with a JSON payload containing the `issue_key` of the Jira user
  story.

  Example payload:
  ```json
  {
      "issue_key": "SCRUM-1"
  }
  ```

* **Story Ready for Test Case Generation:**
  Send a POST request to `/story-ready-for-test-case-generation` with a JSON payload containing the `issue_key` of the
  Jira user story. This triggers the test case generation, classification, and review workflows.

  Example payload:
  ```json
  {
      "issue_key": "SCRUM-1"
  }
  ```

### Executing Automated Tests

You can trigger the execution of automated tests for a specific project.

* **Execute Tests:**
  Send a POST request to `/execute-tests` with a JSON payload containing the `project_key` of the Jira project. This
  will execute all test cases labeled as "automated" within that project. For any failed tests, the orchestrator will
  automatically trigger incident creation using the Incident Creation Agent.

  Example payload:
  ```json
  {
      "project_key": "SCRUM"
  }
  ```
  The results will be reported back to Zephyr and an Allure report will be generated.

### Updating the RAG Vector Database

To keep the vector database synchronized with Jira issues for duplicate detection:

* **Update RAG DB:**
  Send a POST request to `/update-rag-db` with a JSON payload containing the `project_key` of the Jira project. This
  will sync all bug issues from Jira to the Qdrant vector database, enabling semantic search for duplicate detection.

  Example payload:
  ```json
  {
      "project_key": "SCRUM"
  }
  ```

## Running Tests

The project includes a comprehensive test suite. To run the tests:

```bash
# Run all tests
pytest

# Run tests with verbose output
pytest -v

# Run tests for a specific module
pytest tests/agents/
pytest tests/orchestrator/
pytest tests/common/
```

## Contributing

We welcome contributions to the Agentic Framework! Please see our [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on
how to contribute.

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.
