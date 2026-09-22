# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only
FROM agentic-qa-base:latest

ARG WORK_DIR=/app
WORKDIR ${WORK_DIR}

# Install service-specific (ML) dependencies on top of the shared base. The
# pyproject.toml and uv.lock are already present from the base image, so this
# heavy layer is cached independently of the service source code below.
ARG PROMPT_INJECTION_MODEL_NAME=ProtectAI/deberta-v3-base-prompt-injection-v2
ENV PROMPT_INJECTION_MODEL_NAME=${PROMPT_INJECTION_MODEL_NAME}
ARG PROMPT_INJECTION_MODEL_REVISION=90c9989b1a342275dd0d1a95aad283c04e075671
ENV PROMPT_INJECTION_MODEL_REVISION=${PROMPT_INJECTION_MODEL_REVISION}
RUN uv sync --frozen --no-dev --extra prompt-guard-service

COPY services/prompt_guard_service/ ${WORK_DIR}/prompt_guard_service
COPY common/ ${WORK_DIR}/common
COPY config.py ${WORK_DIR}/config.py
COPY scripts/download_prompt_guard_model.py ${WORK_DIR}/scripts/download_prompt_guard_model.py

# Download model
RUN python ${WORK_DIR}/scripts/download_prompt_guard_model.py

CMD gunicorn -w 1 -k uvicorn_worker.UvicornWorker --bind 0.0.0.0:$PORT prompt_guard_service.main:app
