# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only
FROM agentic-qa-base:latest

ARG WORK_DIR=/app
WORKDIR ${WORK_DIR}

COPY agents/test_case_design/ ${WORK_DIR}/agents/test_case_design
# The design agent runs these agents in-process as its delegates.
COPY agents/test_case_generation/ ${WORK_DIR}/agents/test_case_generation
COPY agents/test_case_review/ ${WORK_DIR}/agents/test_case_review
COPY agents/test_case_classification/ ${WORK_DIR}/agents/test_case_classification
COPY common/ ${WORK_DIR}/common
# The instruction to fetch the configured additional Jira fields is shared with the orchestrator.
COPY orchestrator/prompt.py ${WORK_DIR}/orchestrator/prompt.py
COPY prompts/ ${WORK_DIR}/prompts
COPY config.py ${WORK_DIR}/config.py

CMD gunicorn -w 1 -k uvicorn_worker.UvicornWorker --bind 0.0.0.0:$PORT agents.test_case_design.main:app
