# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only
FROM agentic-qa-base:latest

ARG WORK_DIR=/app
WORKDIR ${WORK_DIR}

# Install service-specific (ML) dependencies on top of the shared base. The
# pyproject.toml and uv.lock are already present from the base image, so this
# heavy layer is cached independently of the service source code below.
RUN uv sync --frozen --no-dev --extra embedding-service

COPY services/embedding_service/ ${WORK_DIR}/embedding_service
COPY common/ ${WORK_DIR}/common
COPY config.py ${WORK_DIR}/config.py
COPY scripts/download_embedding_model.py ${WORK_DIR}/scripts/download_embedding_model.py

# Download model
RUN python ${WORK_DIR}/scripts/download_embedding_model.py

CMD gunicorn -w 1 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT embedding_service.main:app
