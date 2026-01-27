# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

import config
from common.services.test_management_base import TestManagementClientBase
from common.services.xray_client import XrayClient
from common.services.zephyr_client import ZephyrClient


def get_test_management_client() -> TestManagementClientBase:
    test_management_system = config.TEST_MANAGEMENT_SYSTEM
    if test_management_system == "zephyr":
        client = ZephyrClient()
    elif test_management_system == "xray":
        client = XrayClient()
    else:
        raise ValueError(f"Unsupported value of the environment variable JIRA_TEST_MANAGEMENT_SYSTEM: "
                         f"{test_management_system}")
    return client
