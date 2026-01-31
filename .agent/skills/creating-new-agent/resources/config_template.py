# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

"""
Configuration class template for a new agent.

Replace <AgentName> with your agent's name (e.g., RequirementsReview).
Replace <unique_port> with a unique port number (e.g., 8008).
"""

import os


class <AgentName>AgentConfig:
    THINKING_BUDGET = 2000  # Token budget for thinking (0 to disable)
    OWN_NAME = "<Human-Readable Agent Name>"
    PORT = int(os.environ.get("PORT", "<unique_port>"))  # e.g., 8008
    EXTERNAL_PORT = int(os.environ.get("EXTERNAL_PORT", PORT))
    PROTOCOL = "http"
    MODEL_NAME = "google-gla:gemini-3-flash-preview"
    MAX_REQUESTS_PER_TASK = 30  # Maximum tool calls per task
