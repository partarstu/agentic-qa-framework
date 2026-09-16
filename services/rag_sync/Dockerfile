# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only
FROM agentic-qa-base:latest

ARG WORK_DIR=/app
WORKDIR ${WORK_DIR}

# Install only the sync runtime's locked optional dependencies. The OCR models ship
# inside the rapidocr wheel, so nothing is downloaded at build time or at runtime.
RUN uv sync --frozen --no-dev --no-install-project --extra rag-sync

# LibreOffice performs the office-to-PDF conversion. Metric-compatible Microsoft
# font substitutes plus Noto keep page layout and broad-Unicode text stable.
# libgl1 is required by OpenCV, which RapidOCR uses for image preprocessing.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libreoffice-writer \
    libreoffice-impress \
    libreoffice-calc \
    fonts-crosextra-carlito \
    fonts-crosextra-caladea \
    fonts-liberation \
    fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

COPY services/rag_sync/ ${WORK_DIR}/rag_sync
COPY common/ ${WORK_DIR}/common
COPY config.py ${WORK_DIR}/config.py

# The Cloud Run Job runs the command-line runner for one scope to completion; the
# orchestrator passes the scope options and the lock token as container arguments.
ENTRYPOINT ["python", "-m", "rag_sync.cli"]
