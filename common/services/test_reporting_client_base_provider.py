# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import config
from common.services.allure_client import AllureClient


def get_test_reporting_client(reports_root_path: str):
    test_reporter_name = config.TEST_REPORTER
    if test_reporter_name == "allure":
        client = AllureClient(reports_root_path)
    else:
        raise ValueError(f"Unsupported value of the environment variable TEST_REPORTER: {test_reporter_name}")
    return client
