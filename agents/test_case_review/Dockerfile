# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0
FROM agentic-qa-base:latest

ARG WORK_DIR=/app
WORKDIR ${WORK_DIR}

COPY agents/test_case_review/ ${WORK_DIR}/agents/test_case_review
COPY common/ ${WORK_DIR}/common
COPY config.py ${WORK_DIR}/config.py

CMD gunicorn -w 1 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT agents.test_case_review.main:app