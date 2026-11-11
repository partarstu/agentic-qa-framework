# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

# =============================================================================
# Stage 1: Build the React UI
# =============================================================================
FROM node:24.21.0-alpine3.24 AS ui-builder

WORKDIR /ui

# Copy package files first for better caching; .npmrc keeps the packages' lifecycle scripts disabled
COPY orchestrator/ui/package*.json orchestrator/ui/.npmrc ./

# Install dependencies
RUN npm ci

# Copy source code
COPY orchestrator/ui/ ./

# Build the production bundle
RUN npm run build

# =============================================================================
# Stage 2: Build a Java runtime with only the modules the Allure command line needs
# =============================================================================
FROM eclipse-temurin:25.0.5_8-jdk-noble AS jre-builder

# The modules found by jdeps in Allure's jars and plugins, plus jdk.unsupported and
# jdk.zipfs, which libraries reach through reflection and service lookup.
RUN jlink \
    --add-modules java.base,java.datatransfer,java.desktop,java.logging,java.management,java.naming,java.rmi,java.scripting,java.security.jgss,java.sql,java.xml,jdk.httpserver,jdk.unsupported,jdk.zipfs \
    --strip-debug --no-man-pages --no-header-files --compress=zip-6 \
    --output /javaruntime

# =============================================================================
# Stage 3: Build the final image
# =============================================================================
FROM agentic-qa-base:latest

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y --no-install-recommends wget unzip && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/opt/java
ENV PATH="${JAVA_HOME}/bin:${PATH}"
COPY --from=jre-builder /javaruntime ${JAVA_HOME}

# Set the Allure version as an argument
ARG ALLURE_VERSION=2.34.1
ARG ALLURE_SHA256=6eb2e037604744d4ba1f9cad3676cf286974aca48f7839d9b2f7688e1efd79f2

# Define environment variables for Allure
ENV ALLURE_HOME=/opt/allure-${ALLURE_VERSION}
ENV PATH="${ALLURE_HOME}/bin:${PATH}"

# Download, extract, and set up Allure Commandline
RUN wget -q https://github.com/allure-framework/allure2/releases/download/${ALLURE_VERSION}/allure-${ALLURE_VERSION}.zip -O /tmp/allure.zip && \
    echo "${ALLURE_SHA256}  /tmp/allure.zip" | sha256sum -c - && \
    unzip /tmp/allure.zip -d /opt && \
    rm /tmp/allure.zip

# Verify Allure installation
RUN allure --version
RUN mkdir "allure-report"

ARG WORK_DIR=/app
WORKDIR ${WORK_DIR}

# Copy Python application
COPY orchestrator/ ${WORK_DIR}/orchestrator
COPY prompts/ ${WORK_DIR}/prompts
COPY common/ ${WORK_DIR}/common
COPY config.py ${WORK_DIR}/config.py

# Copy built UI from the ui-builder stage
COPY --from=ui-builder /ui/dist ${WORK_DIR}/orchestrator/static

CMD ["gunicorn", "-w", "1", "-k", "uvicorn_worker.UvicornWorker", "orchestrator.main:orchestrator_app"]