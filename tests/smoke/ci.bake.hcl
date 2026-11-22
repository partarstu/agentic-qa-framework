# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

# CI-only overlay on docker-compose.smoke.yml: builds every smoke image with the GitHub Actions cache and
# feeds the base image to the others as a Bake target, since the cache-capable builder can't see local images.
# Tags follow Compose's <project>-<service> naming, so the smoke job pins COMPOSE_PROJECT_NAME to "smoke".

target "base" {
  context    = "."
  dockerfile = "Dockerfile.base"
  cache-from = ["type=gha,scope=smoke-base"]
  cache-to   = ["type=gha,mode=max,scope=smoke-base"]
}

target "jira_mcp_mock" {
  contexts   = { "agentic-qa-base" = "target:base" }
  cache-from = ["type=gha,scope=smoke-mocks"]
  cache-to   = ["type=gha,mode=max,scope=smoke-mocks"]
}

target "execution_agent" {
  contexts   = { "agentic-qa-base" = "target:base" }
  cache-from = ["type=gha,scope=smoke-execution-agent"]
  cache-to   = ["type=gha,mode=max,scope=smoke-execution-agent"]
}

target "rag_sync_local" {
  tags       = ["smoke-rag_sync_local"]
  contexts   = { "agentic-qa-base" = "target:base" }
  cache-from = ["type=gha,scope=smoke-rag-sync"]
  cache-to   = ["type=gha,mode=max,scope=smoke-rag-sync"]
}

target "requirements_review" {
  tags       = ["smoke-requirements_review"]
  contexts   = { "agentic-qa-base" = "target:base" }
  cache-from = ["type=gha,scope=smoke-requirements-review"]
  cache-to   = ["type=gha,mode=max,scope=smoke-requirements-review"]
}

target "test_case_design" {
  tags       = ["smoke-test_case_design"]
  contexts   = { "agentic-qa-base" = "target:base" }
  cache-from = ["type=gha,scope=smoke-test-case-design"]
  cache-to   = ["type=gha,mode=max,scope=smoke-test-case-design"]
}

target "incident_creation" {
  tags       = ["smoke-incident_creation"]
  contexts   = { "agentic-qa-base" = "target:base" }
  cache-from = ["type=gha,scope=smoke-incident-creation"]
  cache-to   = ["type=gha,mode=max,scope=smoke-incident-creation"]
}

target "orchestrator" {
  tags       = ["smoke-orchestrator"]
  contexts   = { "agentic-qa-base" = "target:base" }
  cache-from = ["type=gha,scope=smoke-orchestrator"]
  cache-to   = ["type=gha,mode=max,scope=smoke-orchestrator"]
}
