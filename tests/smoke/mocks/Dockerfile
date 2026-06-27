# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

# One image for all three recording mocks; docker-compose overrides `command` to
# pick which app to serve. Built on the shared base, which already provides
# fastapi, uvicorn and the mcp SDK, so no extra dependency install is needed.
FROM agentic-qa-base:latest

ARG WORK_DIR=/app
WORKDIR ${WORK_DIR}

COPY tests/smoke/mocks/ ${WORK_DIR}/mocks/

# Default to the MCP mock; compose overrides this per service.
CMD ["uvicorn", "mocks.jira_mcp_mock:app", "--host", "0.0.0.0", "--port", "9000"]
