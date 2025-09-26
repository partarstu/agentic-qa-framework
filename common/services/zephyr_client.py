# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

from collections import defaultdict
from typing import List, Dict

import dateutil
import httpx

import config
from common import utils
from common.models import TestCase, TestStep, TestExecutionResult
from common.services.test_management_base import TestManagementClientBase

CLIENT_TIMEOUT = config.ZEPHYR_CLIENT_TIMEOUT_SECONDS
COMMENTS_CUSTOM_FIELD_NAME = config.ZEPHYR_COMMENTS_CUSTOM_FIELD_NAME

logger = utils.get_logger(__name__)


class ZephyrClient(TestManagementClientBase):
    """
    A client for interacting with the Zephyr Scale Cloud API.
    """

    def __init__(self):
        """
        Initializes the ZephyrClient.
        It expects ZEPHYR_BASE_URL and ZEPHYR_API_TOKEN to be set as environment variables.
        """
        self.base_url = config.ZEPHYR_BASE_URL
        if not self.base_url:
            raise ValueError("ZEPHYR_BASE_URL is not configured in config.py or environment variables.")
        logger.debug(f"Zephyr Base URL: {self.base_url}")
        self.api_token = config.ZEPHYR_API_TOKEN
        if not self.api_token:
            raise ValueError("ZEPHYR_API_TOKEN is not configured in config.py or environment variables.")
        self.headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }

    def add_test_case_review_comment(self, test_case_key: str, comment: str):
        with httpx.Client() as client:
            tc_url = self._get_test_case_url(test_case_key)
            logger.info(f"Adding review comment to test case {test_case_key} at {tc_url}")
            test_case_data = self._get_test_case_data(client, tc_url)
            custom_fields = test_case_data.get(config.ZEPHYR_CUSTOM_FIELDS_JSON_FIELD_NAME, {})
            if not custom_fields:
                logger.error(f"No custom fields found for test case {test_case_key}.")
                raise RuntimeError(f"No custom fields found in test case {test_case_key}, "
                                   f"seems like a Zephyr configuration issue")
            if COMMENTS_CUSTOM_FIELD_NAME not in custom_fields:
                logger.error(f"Custom field '{COMMENTS_CUSTOM_FIELD_NAME}' not found for test case {test_case_key}.")
                raise RuntimeError(f"Custom field for test review comments '{COMMENTS_CUSTOM_FIELD_NAME}' not found "
                                   f"for test case {test_case_key}, please add this field on Zephyr configuration page.")

            existing_comments = custom_fields.get(COMMENTS_CUSTOM_FIELD_NAME, "")
            comment = comment.replace('\n', '<br>')
            if not existing_comments:
                existing_comments = comment
                logger.debug(f"No existing comments found for {test_case_key}. Adding new comment.")
            else:
                existing_comments = f"{existing_comments}<br>{comment}"
                logger.debug(f"Appending new comment to existing comments for {test_case_key}.")
            test_case_data[config.ZEPHYR_CUSTOM_FIELDS_JSON_FIELD_NAME][COMMENTS_CUSTOM_FIELD_NAME] = existing_comments
            self._update_test_case(client, tc_url, test_case_data)
            logger.info(f"Successfully added review comment to test case {test_case_key}.")

    def create_test_cases(self, test_cases: List[TestCase], project_key: str, user_story_id: int) -> List[str]:
        """
        Creates test cases in Zephyr.

        Args:
            test_cases: A list of TestCase objects to create.
            project_key: The project key for the test cases.
            user_story_id: ID of the Jira user story

        Returns:
            A list of keys of the created test cases.
        """
        created_test_case_keys = []
        with httpx.Client() as client:
            for test_case in test_cases:
                logger.info(f"Attempting to create test case: {test_case.name} in project {project_key}")
                payload = {
                    "projectKey": project_key,
                    "name": test_case.name,
                    "objective": test_case.summary,
                    "precondition": test_case.preconditions,
                }
                response = client.post(f"{self.base_url}/testcases", headers=self.headers, json=payload,
                                       timeout=CLIENT_TIMEOUT)
                logger.debug(f"Zephyr API response status for test case creation: {response.status_code}")
                response.raise_for_status()
                created_test_case = response.json()

                tc_key = created_test_case.get('key', "")
                if tc_key and test_case.steps:
                    logger.info(f"Adding {len(test_case.steps)} test steps to test case {tc_key}")
                    steps_payload = {
                        "mode": "OVERWRITE",
                        "items": [
                            {
                                "inline": {
                                    "description": step.action,
                                    "expectedResult": step.expected_results.replace("\n", "<br>"),
                                    "testData": "<br>".join(step.test_data).replace("\n", "")
                                }
                            } for step in test_case.steps
                        ]
                    }
                    steps_response = client.post(f"{self.base_url}/testcases/{tc_key}/teststeps",
                                                 headers=self.headers,
                                                 json=steps_payload,
                                                 timeout=CLIENT_TIMEOUT)
                    steps_response.raise_for_status()
                    logger.info(f"Successfully added test steps to test case {tc_key}")

                logger.info(f"Test case '{test_case.name}' created with key: {tc_key}")
                if tc_key:
                    created_test_case_keys.append(tc_key)
                    logger.info(f"Linking test case {tc_key} to Jira issue {user_story_id}")
                    issue_link_response = client.post(f"{self.base_url}/testcases/{tc_key}/links/issues",
                                                      headers=self.headers,
                                                      json={"issueId": user_story_id},
                                                      timeout=CLIENT_TIMEOUT)
                    issue_link_response.raise_for_status()
                    logger.info(f"Successfully linked test case {tc_key} to Jira issue {user_story_id}")
        return created_test_case_keys

    def fetch_test_cases_by_jira_issue(self, issue_key: str) -> List[TestCase]:
        """
        Fetches test cases linked to a specific Jira issue.

        Args:
            issue_key: The key of the Jira issue.

        Returns:
            A list of TestCase objects.
        """
        url = f"{self.base_url}/issuelinks/{issue_key}/testcases"
        logger.info(f"Fetching test cases linked to Jira issue: {issue_key} from {url}")
        with httpx.Client() as client:
            response = client.get(url, headers=self.headers)
            logger.debug(f"Zephyr API response status for fetching linked test cases: {response.status_code}")
            response.raise_for_status()
            test_case_keys = [response_object['key'] for response_object in response.json()]
            logger.info(f"Found {len(test_case_keys)} test cases linked to {issue_key}: {test_case_keys}")
            test_case_jsons = []
            for test_case_key in test_case_keys:
                url = self._get_test_case_url(test_case_key)
                logger.debug(f"Fetching details for test case: {test_case_key} from {url}")
                test_case_jsons.append(self._get_test_case_data(client, url))
            logger.info(f"Successfully fetched details for all linked test cases for {issue_key}.")
            return [self._parse_tc_json(client, issue_key, tc) for tc in test_case_jsons]

    def add_labels_to_test_case(self, test_case_key: str, labels: List[str]) -> None:
        """
        Adds labels to an existing test case.

        Args:
            test_case_key: The ID or key of the test case to update.
            labels: A list of labels to add.
        """
        with httpx.Client() as client:
            logger.info(f"Adding labels {labels} to test case {test_case_key}")
            tc_url = self._get_test_case_url(test_case_key)
            logger.debug(f"Fetching current labels for test case {test_case_key} from {tc_url}")
            test_case_data = self._get_test_case_data(client, tc_url)
            existing_labels = set(test_case_data.get("labels", []))
            logger.debug(f"Existing labels for {test_case_key}: {existing_labels}")
            existing_labels.update(labels)
            test_case_data["labels"] = list(existing_labels)
            self._update_test_case(client, tc_url, test_case_data)
            logger.info(f"Successfully added labels to test case {test_case_key}.")

    def fetch_test_cases_by_labels(self, project_key: str, target_labels: List[str],
                                   max_results=100) -> Dict[str, List[TestCase]]:
        """
        Fetches test cases that have specific labels.

        Args:
            project_key: A Jira project key.
            target_labels: A list of labels to search for.
            max_results: Max amount of results to fetch in one round.

        Returns:
            A list of test case data dictionaries.
        """
        search_url = f"{self.base_url}/testcases"
        test_cases_by_label = defaultdict(list)
        logger.info(f"Fetching test cases with labels {target_labels} for project {project_key}")
        start_at = 0
        while True:
            params = {
                "projectKey": project_key,
                "maxResults": max_results,
                "startAt": start_at
            }

            logger.debug(f"Fetching test cases with params: {params}")
            with httpx.Client() as client:
                response = client.get(search_url, headers=self.headers, params=params)
                logger.debug(f"Zephyr API response status for fetching by labels: {response.status_code}")
                response.raise_for_status()
                data = response.json()
                if data['maxResults']:
                    max_results = data['maxResults']
                for tc in data.get('values', []):
                    labels = tc.get("labels", [])
                    logger.debug(f"Test case {tc.get('key')} has labels: {labels}")
                    for target_label in target_labels:
                        if target_label in labels:
                            logger.debug(f"Test case {tc.get('key')} matches target label: {target_label}")
                            test_cases_by_label[target_label].append(self._parse_tc_json(client, None, tc))
                if data.get('isLast', True):
                    logger.debug("Reached the last page of results when fetching by labels.")
                    break
                else:
                    logger.debug(f"Fetched {len(data.get('values', []))} test cases, total so far: "
                                 f"{sum(len(item_list) for item_list in test_cases_by_label.values())}")
                start_at += max_results
        logger.info(f"Fetched {len(data.get('values', []))} test cases.")
        return dict(test_cases_by_label)

    def change_test_case_status(self, project_key: str, test_case_key: str, new_status_name: str) -> None:
        """
        Changes the status of a specific test case.

        This method first fetches all available test case statuses for the given project,
        finds the ID of the target status by its name, and then sends a request to update
        the test case with the new status.

       Args:
            test_case_key: The key or ID of the test case to update.
            project_key: The key of the project the test case belongs to.
            new_status_name: The name of the desired new status (e.g., 'Approved').

        Raises:
            ValueError: If the specified status name cannot be found in the project.
            httpx.HTTPStatusError: If any of the API requests fail.
        """

        logger.info(f"Attempting to change status for test case {test_case_key} to '{new_status_name}'")
        params = {
            "projectKey": project_key,
            "maxResults": 1000,
            "startAt": 0
        }
        with httpx.Client() as client:
            statuses_url = f"{self.base_url}/statuses?maxResults=100&statusType=TEST_CASE"
            logger.debug(f"Fetching statuses from {statuses_url}")
            statuses_response = client.get(statuses_url, headers=self.headers, params=params)
            statuses_response.raise_for_status()
            response_json = statuses_response.json()
            logger.debug(f"Zephyr API response for fetching statuses: {response_json}")

            statuses = response_json.get("values", [])
            logger.debug(f"Found {len(statuses)} statuses")
            target_status_id = next(
                (status.get("id") for status in statuses if status.get("name", "").lower() == new_status_name.lower()),
                None)
            if not target_status_id:
                logger.error(f"Test case status '{new_status_name}' not found.")
                raise ValueError(f"Status '{new_status_name}' is not a valid test case status.")
            logger.info(f"Found status ID '{target_status_id}' for status name '{new_status_name}'.")

            tc_url = self._get_test_case_url(test_case_key)
            test_case_data = self._get_test_case_data(client, tc_url)
            test_case_data["status"] = {"id": target_status_id}
            self._update_test_case(client, tc_url, test_case_data)
            logger.info(f"Successfully changed status of test case {test_case_key} to '{new_status_name}'.")

    def create_test_execution(self, test_execution_results: List[TestExecutionResult], project_key: str,
                              test_cycle_key: str, version_id: str = None) -> None:
        """
        Creates test executions in Zephyr based on the provided test execution results.

        Args:
            test_execution_results: A list of TestExecutionResult objects.
            project_key: The project key for the test executions.
            test_cycle_key: The test cycle key for the test execution.
            version_id: Optional. The ID of the version to associate with the test execution.
        """
        with httpx.Client() as client:
            for result in test_execution_results:
                logger.info(f"Creating test execution for test case: {result.testCaseName} "
                            f"with status: {result.testExecutionStatus}")

                test_script_results = []
                for step_result in result.stepResults:
                    step_status = "Pass" if step_result.success else "Fail"
                    if step_result.errorMessage:
                        actual_result_comment = step_result.errorMessage
                    else:
                        actual_result_comment = step_result.actualResults
                    test_script_results.append({
                        "statusName": step_status,
                        "actualResult": actual_result_comment
                    })

                test_case_key = result.testCaseKey
                step_data = self._get_test_steps(client, test_case_key)
                total_steps = len(step_data.get('values', []))
                num_executed_steps = len(test_script_results)
                if num_executed_steps < total_steps:
                    for _ in range(total_steps - num_executed_steps):
                        test_script_results.append({
                            "statusName": "Not Executed",
                            "actualResult": "This step was not executed because a previous step failed."
                        })

                actual_start_date = self._parse_timestamp(result.start_timestamp)
                actual_end_date = self._parse_timestamp(result.end_timestamp)
                overall_status = "Pass" if result.testExecutionStatus == 'passed' else "Fail"
                comment = result.generalErrorMessage if result.testExecutionStatus != 'passed' else ""
                payload = {
                    "projectKey": project_key,
                    "testCaseKey": test_case_key,
                    "testCycleKey": test_cycle_key,
                    "statusName": overall_status,
                    "comment": comment,
                    "actualStartDate": actual_start_date,
                    "actualEndDate": actual_end_date,
                    "testScriptResults": test_script_results
                }
                if version_id:
                    payload["versionId"] = version_id

                response = client.post(f"{self.base_url}/testexecutions", headers=self.headers, json=payload,
                                       timeout=CLIENT_TIMEOUT)
                logger.debug(f"Zephyr API response status for test execution creation: {response.status_code}")
                response.raise_for_status()
                execution_id = response.json().get("id")
                logger.info(f"Test execution created with ID: {execution_id}")

    def _get_test_steps(self, client, test_case_key):
        logger.debug(f"Fetching test steps of test case: {test_case_key} in order update their "
                     f"test execution status")
        steps_url = f"{self.base_url}/testcases/{test_case_key}/teststeps?maxResults=1000"
        test_step_response = client.get(steps_url, headers=self.headers)
        test_step_response.raise_for_status()
        step_data = test_step_response.json()
        return step_data

    def create_test_plan(self, project_key: str, name: str, description: str = None) -> str:
        """
        Creates a new test cycle in Zephyr.

        Args:
            project_key: The project key for the test cycle.
            name: The name of the test cycle.
            description: Optional. The description of the test cycle.

        Returns:
            The key of the created test cycle.
        """
        with httpx.Client() as client:
            logger.info(f"Creating test cycle: {name} for project {project_key}")
            payload = {
                "projectKey": project_key,
                "name": name,
                "statusName": "Not executed"
            }
            if description:
                payload["description"] = description

            response = client.post(f"{self.base_url}/testcycles", headers=self.headers, json=payload,
                                   timeout=CLIENT_TIMEOUT)
            logger.debug(f"Zephyr API response status for test cycle creation: {response.status_code}")
            response.raise_for_status()
            test_cycle_key = response.json().get("key")
            if not test_cycle_key:
                raise RuntimeError("Failed to retrieve test cycle key from Zephyr API response.")
            logger.info(f"Successfully created test cycle with key: {test_cycle_key}")
            return test_cycle_key

    def _update_test_case(self, client, tc_url, test_case_data):
        logger.debug(f"Updating test case using {tc_url}.")
        put_response = client.put(tc_url, headers=self.headers, json=test_case_data, timeout=CLIENT_TIMEOUT)
        put_response.raise_for_status()

    def _parse_tc_json(self, client, issue_key, tc) -> TestCase:
        steps_url = f"{self.base_url}/testcases/{tc['key']}/teststeps?maxResults=1000"
        logger.debug(f"Fetching test steps for test case {tc['key']} from {steps_url}")
        test_step_response = client.get(steps_url, headers=self.headers)
        test_step_response.raise_for_status()
        logger.debug(f"Successfully fetched test steps for {tc['key']}.")
        step_data = test_step_response.json()
        steps: List[TestStep] = []
        for step in step_data.get('values', []):
            inline_data = step.get('inline', {})
            steps.append(TestStep(
                action=inline_data.get('description', ''),
                expected_results=inline_data.get('expectedResult', '').replace("<br>", "\n"),
                test_data=inline_data.get('testData', '').split('<br>')
            ))
        logger.debug(f"Parsed test case {tc.get('key')} with {len(steps)} steps.")
        return TestCase(
            key=tc.get('key'),
            name=tc.get('name', ''),
            summary=tc.get('objective', ''),
            preconditions=tc.get('precondition'),
            steps=steps,
            parent_issue_key=issue_key,
            labels=tc.get('labels', []),
            comment=""
        )

    def _get_test_case_url(self, test_case_key):
        return f"{self.base_url}/testcases/{test_case_key}"

    def _get_test_case_data(self, client, tc_url):
        logger.debug(f"Fetching current data for test case from {tc_url}")
        test_case_response = client.get(tc_url, headers=self.headers, timeout=CLIENT_TIMEOUT)
        test_case_response.raise_for_status()
        return test_case_response.json()

    @staticmethod
    def _parse_timestamp(timestamp_str: str) -> str:
        try:
            timestamp = dateutil.parser.parse(timestamp_str)
            return timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError as e:
            logger.error(f"Could not parse timestamp '{timestamp_str}': {e}")
            raise

    def fetch_test_case_by_key(self, test_case_key: str) -> TestCase:
        """
        Fetches a single test case by its key.

        Args:
            test_case_key: The key of the test case to fetch.

        Returns:
            A TestCase object.
        """
        with httpx.Client() as client:
            url = self._get_test_case_url(test_case_key)
            logger.info(f"Fetching test case: {test_case_key} from {url}")
            test_case_data = self._get_test_case_data(client, url)
            return self._parse_tc_json(client, None, test_case_data)
