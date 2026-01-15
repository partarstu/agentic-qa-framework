# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

# =============================================================================
# Stage 1: Build the React UI
# =============================================================================
FROM node:20-alpine AS ui-builder

WORKDIR /ui

# Copy package files first for better caching
COPY orchestrator/ui/package*.json ./

# Install dependencies
RUN npm ci

# Copy source code
COPY orchestrator/ui/ ./

# Build the production bundle
RUN npm run build

# =============================================================================
# Stage 2: Build the final image
# =============================================================================
FROM agentic-qa-base:latest

ENV DEBIAN_FRONTEND=noninteractive

# Create man directories to prevent potential dependency issues with ca-certificates
RUN mkdir -p /usr/share/man/man1 /usr/share/man/man2 && \
    apt-get update && \
    apt-get install -y --no-install-recommends openjdk-25-jre-headless wget unzip && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Set the Allure version as an argument
ARG ALLURE_VERSION=2.34.1

# Define environment variables for Allure
ENV ALLURE_HOME=/opt/allure-${ALLURE_VERSION}
ENV PATH="${ALLURE_HOME}/bin:${PATH}"

# Download, extract, and set up Allure Commandline
RUN wget -q https://github.com/allure-framework/allure2/releases/download/${ALLURE_VERSION}/allure-${ALLURE_VERSION}.zip -O /tmp/allure.zip && \
    unzip /tmp/allure.zip -d /opt && \
    rm /tmp/allure.zip

# Verify Allure installation
RUN allure --version
RUN mkdir "allure-report"

ARG WORK_DIR=/app
WORKDIR ${WORK_DIR}

# Copy Python application
COPY orchestrator/ ${WORK_DIR}/orchestrator
COPY common/ ${WORK_DIR}/common
COPY config.py ${WORK_DIR}/config.py

# Copy built UI from the ui-builder stage
COPY --from=ui-builder /ui/dist ${WORK_DIR}/orchestrator/static

CMD ["gunicorn", "-w", "1", "-k", "uvicorn.workers.UvicornWorker", "orchestrator.main:orchestrator_app"]