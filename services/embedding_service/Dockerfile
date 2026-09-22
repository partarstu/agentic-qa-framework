# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only
FROM agentic-qa-base:latest

ARG WORK_DIR=/app
WORKDIR ${WORK_DIR}

# Install service-specific (ML) dependencies on top of the shared base. The
# pyproject.toml and uv.lock are already present from the base image, so this
# heavy layer is cached independently of the service source code below.
ARG EMBEDDING_TEXT_MODEL=BAAI/bge-m3
ENV EMBEDDING_TEXT_MODEL=${EMBEDDING_TEXT_MODEL}
ARG EMBEDDING_TEXT_MODEL_REVISION=5617a9f61b028005a4858fdac845db406aefb181
ENV EMBEDDING_TEXT_MODEL_REVISION=${EMBEDDING_TEXT_MODEL_REVISION}
RUN uv sync --frozen --no-dev --extra embedding-service

COPY services/embedding_service/ ${WORK_DIR}/embedding_service
COPY common/ ${WORK_DIR}/common
COPY config.py ${WORK_DIR}/config.py
COPY scripts/download_embedding_model.py ${WORK_DIR}/scripts/download_embedding_model.py

# Download model
RUN python ${WORK_DIR}/scripts/download_embedding_model.py

# Fail the build when the model didn't land locally (runtime downloads are disabled).
RUN python -c "import config, os, sys; sys.exit(0 if os.listdir(config.EmbeddingServiceConfig.TEXT_MODEL_PATH) else 1)" \
    || (echo 'embedding model files missing after download' && exit 1)

CMD gunicorn -w 1 -k uvicorn_worker.UvicornWorker --bind 0.0.0.0:$PORT embedding_service.main:app
