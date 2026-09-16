# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Shared Jira REST client factory (WS5).

Every component that talks to the Jira REST API validates the same settings and
builds its client the same way; the factory keeps that in one place.
"""

from jira import JIRA

import config


def build_jira_client() -> JIRA:
    """Builds a Jira REST client from the configured settings.

    Raises:
        RuntimeError: When the Jira configuration is missing.
    """
    if not config.JIRA_BASE_URL or not config.JIRA_USER or not config.JIRA_TOKEN:
        raise RuntimeError("Jira configuration is missing (JIRA_URL, JIRA_USERNAME, or JIRA_API_TOKEN).")
    return JIRA(server=config.JIRA_BASE_URL, basic_auth=(config.JIRA_USER, config.JIRA_TOKEN))
