# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""
Configuration class template for a new agent.

Paste into config.py, which already imports `os` and `ThinkingLevel` and defines `DEFAULT_MODEL_NAME`.
Replace <AgentName>, <AGENT_NAME> and <unique_port>.
"""


class <AgentName>AgentConfig:
    THINKING_LEVEL: ThinkingLevel = "medium"
    VERSION = os.environ.get("<AGENT_NAME>_AGENT_VERSION", "1.0")
    OWN_NAME = "<Human-Readable Agent Name>"
    PORT = int(os.environ.get("PORT", "<unique_port>"))
    EXTERNAL_PORT = int(os.environ.get("EXTERNAL_PORT", PORT))
    PROTOCOL = "http"
    MODEL_NAME = DEFAULT_MODEL_NAME
    MAX_REQUESTS_PER_TASK = 30
