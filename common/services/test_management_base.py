# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

from abc import ABC, abstractmethod
from typing import List, Dict

from common.models import TestCase, TestExecutionResult


class TestManagementClientBase(ABC):
    @abstractmethod
    def create_test_cases(self, test_cases: List[TestCase], project_key: str, user_story_id:int) -> List[str]:
        raise NotImplementedError

    @abstractmethod
    def add_labels_to_test_case(self, test_case_id: str, labels: List[str]) -> None:
        raise NotImplementedError

    @abstractmethod
    def fetch_ready_for_execution_test_cases_by_labels(self, project_key: str, target_labels: List[str], max_results=100) -> Dict[
        str, List[TestCase]]:
        raise NotImplementedError

    @abstractmethod
    def add_test_case_review_comment(self, test_case_key: str, comment: str):
        raise NotImplementedError

    @abstractmethod
    def create_test_execution(self, test_execution_results: List[TestExecutionResult], project_key: str, version_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def create_test_plan(self, project_key: str, name: str, description: str = None) -> str:
        raise NotImplementedError

    @abstractmethod
    def fetch_test_case_by_key(self, test_case_key: str) -> TestCase:
        raise NotImplementedError

    @abstractmethod
    def change_test_case_status(self,  project_key :str,test_case_key: str, new_status: str) -> TestCase:
        raise NotImplementedError

    @abstractmethod
    def fetch_linked_issues(self, test_case_key: str) -> List[Dict]:
        raise NotImplementedError

    @abstractmethod
    def link_issue_to_test_case(self, test_case_key: str, issue_id: int) -> None:       
        raise NotImplementedError
