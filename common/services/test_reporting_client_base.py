# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

from abc import ABC, abstractmethod

from common.models import TestExecutionResult


class TestReportingClientBase(ABC):
    @abstractmethod
    def generate_report(self, test_execution_results: list[TestExecutionResult]):
        raise NotImplementedError
