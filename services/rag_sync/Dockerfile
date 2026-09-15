# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only
FROM agentic-qa-base:latest

ARG WORK_DIR=/app
WORKDIR ${WORK_DIR}

# The sync job needs the Jira client and the Cloud Run Admin SDK (both are shared
# dependencies), plus the PDF/OCR/office stack in later phases.
COPY services/rag_sync/ ${WORK_DIR}/rag_sync
COPY common/ ${WORK_DIR}/common
COPY config.py ${WORK_DIR}/config.py

# The Cloud Run Job runs the command-line runner for one scope to completion; the
# orchestrator passes the scope options and the lock token as container arguments.
ENTRYPOINT ["python", "-m", "rag_sync.cli"]
