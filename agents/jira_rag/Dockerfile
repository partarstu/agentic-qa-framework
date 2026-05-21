# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only
FROM agentic-qa-base:latest

ARG WORK_DIR=/app
WORKDIR ${WORK_DIR}

COPY agents/jira_rag/ ${WORK_DIR}/agents/jira_rag
COPY common/ ${WORK_DIR}/common
COPY config.py ${WORK_DIR}/config.py

CMD gunicorn -w 1 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT agents.jira_rag.main:app