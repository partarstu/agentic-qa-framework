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
# The visual model is opt-in: the build arg both installs the visual extra (Pillow
# for image inputs) and turns on the visual model download in the script below.
ARG EMBEDDING_DOWNLOAD_VISUAL_MODEL=false
ARG EMBEDDING_VISUAL_MODEL=
RUN if [ "$EMBEDDING_DOWNLOAD_VISUAL_MODEL" = "true" ]; then \
        uv sync --frozen --no-dev --extra embedding-service --extra embedding-visual; \
    else \
        uv sync --frozen --no-dev --extra embedding-service; \
    fi

COPY services/embedding_service/ ${WORK_DIR}/embedding_service
COPY common/ ${WORK_DIR}/common
COPY config.py ${WORK_DIR}/config.py
COPY scripts/download_embedding_model.py ${WORK_DIR}/scripts/download_embedding_model.py

# Download models: the text model always, the visual model only when the build arg enables it
RUN python ${WORK_DIR}/scripts/download_embedding_model.py

# Fail the build when the model didn't land locally (runtime downloads are disabled).
RUN python -c "import config, os, sys; sys.exit(0 if os.listdir(config.EmbeddingServiceConfig.TEXT_MODEL_PATH) else 1)" \
    || (echo 'embedding model files missing after download' && exit 1)
RUN if [ "$EMBEDDING_DOWNLOAD_VISUAL_MODEL" = "true" ]; then \
        python -c "import config, os, sys; sys.exit(0 if os.listdir(config.EmbeddingServiceConfig.VISUAL_MODEL_PATH) else 1)" \
        || (echo 'visual model files missing after download' && exit 1); \
    fi

CMD gunicorn -w 1 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT embedding_service.main:app
