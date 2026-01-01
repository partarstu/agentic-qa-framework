# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0
FROM agentic-qa-base:latest

ARG WORK_DIR=/app
WORKDIR ${WORK_DIR}

COPY scripts/download_embedding_model.py /app/scripts/download_embedding_model.py
RUN python /app/scripts/download_embedding_model.py

COPY services/embedding_service/ ${WORK_DIR}/embedding_service
COPY common/ ${WORK_DIR}/common
COPY config.py ${WORK_DIR}/config.py

CMD gunicorn -w 1 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT embedding_service.main:app