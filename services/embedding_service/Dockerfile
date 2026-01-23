# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0
FROM agentic-qa-base:latest

ARG WORK_DIR=/app
WORKDIR ${WORK_DIR}

# Install dependencies
COPY services/embedding_service/ ${WORK_DIR}/embedding_service
COPY common/ ${WORK_DIR}/common
COPY config.py ${WORK_DIR}/config.py
COPY scripts/download_embedding_model.py ${WORK_DIR}/scripts/download_embedding_model.py
RUN pip install --no-cache-dir -r ${WORK_DIR}/services/embedding_service/requirements.txt

# Download model
RUN python ${WORK_DIR}/scripts/download_embedding_model.py

CMD gunicorn -w 1 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT embedding_service.main:app
