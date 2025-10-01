# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

from collections import defaultdict
from typing import List, Dict, Any

import httpx

import config
from common import utils
from common.models import TestCase, TestStep, TestExecutionResult
from common.services.test_management_base import TestManagementClientBase

logger = utils.get_logger(__name__)

PRECONDITIONS_FIELD_ID = config.XRAY_PRECONDITIONS_FIELD_ID


class XrayClient(TestManagementClientBase):
    """
    A client for interacting with the Xray Cloud API.
    """

    def __init__(self):
        """
        Initializes the XrayClient.
        It expects XRAY_BASE_URL, XRAY_CLIENT_ID, XRAY_CLIENT_SECRET,
        JIRA_BASE_URL, JIRA_USER, and JIRA_TOKEN to be set as environment variables.
        """
        self.base_url = config.XRAY_BASE_URL
        if not self.base_url:
            raise ValueError("XRAY_BASE_URL is not configured in config.py or environment variables.")
        logger.debug(f"Xray Base URL: {self.base_url}")

        self.client_id = config.XRAY_CLIENT_ID
        if not self.client_id:
            raise ValueError("XRAY_CLIENT_ID is not configured in config.py or environment variables.")

        self.client_secret = config.XRAY_CLIENT_SECRET
        if not self.client_secret:
            raise ValueError("XRAY_CLIENT_SECRET is not configured in config.py or environment variables.")

        self.jira_base_url = config.JIRA_BASE_URL
        if not self.jira_base_url:
            raise ValueError("JIRA_URL is not configured in config.py or environment variables.")

        self.jira_user = config.JIRA_USER
        if not self.jira_user:
            raise ValueError("JIRA_USERNAME is not configured in config.py or environment variables.")

        self.jira_token = config.JIRA_TOKEN
        if not self.jira_token:
            raise ValueError("JIRA_API_TOKEN is not configured in config.py or environment variables.")

        self.xray_headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json"
        }
        self.jira_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        self.jira_auth = (self.jira_user, self.jira_token)

    def add_test_case_review_comment(self, test_case_key: str, comment: str):
        logger.info(f"Adding comment to test case {test_case_key}")
        endpoint = f"issue/{test_case_key}/comment"
        payload = {"body": {"type": "doc", "version": 1,
                            "content": [{"type": "paragraph", "content": [{"type": "text", "text": comment}]}]}}
        self._execute_jira_request("POST", endpoint, json=payload)

    def create_test_cases(self, test_cases: List[TestCase], project_key: str, user_story_id: str) -> List[str]:
        logger.info(f"Creating {len(test_cases)} test cases in project {project_key}")

        issue_updates = []
        for test_case in test_cases:
            issue_updates.append({
                "fields": {
                    "summary": test_case.name,
                    "description": test_case.summary or "",
                    "issuetype": {"name": "Test"},
                    "project": {"key": project_key},
                }
            })

        # Create the test issues in Jira in bulk
        bulk_payload = {"issueUpdates": issue_updates}

        jira_issues_response = self._execute_jira_request("POST", "issue/bulk", json=bulk_payload)
        created_issues = jira_issues_response["issues"]
        created_test_case_keys = [issue["key"] for issue in created_issues]

        # Add steps to each created test case
        for i, issue in enumerate(created_issues):
            test_case_data = test_cases[i]
            if test_case_data.steps:
                self._add_steps_to_test_case(issue["id"], test_case_data.steps)

        # Link to user story
        for test_case_key in created_test_case_keys:
            link_payload = {
                "type": {"name": "Relates"},
                "inwardIssue": {"key": test_case_key},
                "outwardIssue": {"key": user_story_id}
            }
            self._execute_jira_request("POST", "issueLink", json=link_payload)
            logger.info(f"Linking test case {test_case_key} to user story {user_story_id}")

        logger.info(f"Successfully created {len(created_test_case_keys)} test cases.")
        return created_test_case_keys

    def fetch_test_cases_by_jira_issue(self, issue_key: str) -> List[TestCase]:
        jql = f"'parent' = {issue_key} AND issuetype = 'Test'"
        return self._fetch_test_cases_by_jql(jql)

    def add_labels_to_test_case(self, test_case_key: str, labels: List[str]) -> None:
        logger.info(f"Adding labels {labels} to test case {test_case_key}")
        endpoint = f"issue/{test_case_key}"
        payload = {"update": {"labels": [{"add": label} for label in labels]}}
        self._execute_jira_request("PUT", endpoint, json=payload)

    def fetch_ready_for_execution_test_cases_by_labels(self, project_key: str, target_labels: List[str],
                                                       max_results=100) -> Dict[str, List[TestCase]]:
        jql = f"project = {project_key} AND labels in ({', '.join(f'"{label}"' for label in target_labels)})"
        test_cases = self._fetch_test_cases_by_jql(jql)
        test_cases_by_label = defaultdict(list)
        for tc in test_cases:
            for label in tc.labels:
                if label in target_labels:
                    test_cases_by_label[label].append(tc)
        return dict(test_cases_by_label)

    def change_test_case_status(self, project_key: str, test_case_key: str, new_status_name: str) -> None:
        logger.info(f"Changing status of {test_case_key} to {new_status_name}")
        # Get available transitions
        endpoint = f"issue/{test_case_key}/transitions"
        transitions = self._execute_jira_request("GET", endpoint)["transitions"]
        # Find the transition ID for the new status
        transition_id = next((t['id'] for t in transitions if t['to']['name'] == new_status_name), None)
        if not transition_id:
            raise ValueError(f"Status '{new_status_name}' is not a valid transition for issue {test_case_key}")
        # Perform the transition
        payload = {"transition": {"id": transition_id}}
        self._execute_jira_request("POST", endpoint, json=payload)

    def create_test_execution(self, test_execution_results: List[TestExecutionResult], project_key: str,
                              test_plan_key: str, version_id: str = None) -> None:
        logger.info(f"Creating test execution for test plan {test_plan_key}")

        from datetime import datetime

        test_execution_info = {
            "summary": f"Execution of automated tests for Test Plan {test_plan_key}",
            "project": {"key": project_key},
            "testPlanKey": test_plan_key,
        }

        if test_execution_results:
            earliest_start_time = min(datetime.fromisoformat(r.start_timestamp) for r in test_execution_results)
            latest_finish_time = max(datetime.fromisoformat(r.end_timestamp) for r in test_execution_results)
            test_execution_info["startDate"] = earliest_start_time.isoformat()
            test_execution_info["finishDate"] = latest_finish_time.isoformat()

        if version_id:
            test_execution_info["version"] = version_id

        tests = []
        for result in test_execution_results:
            test_steps = []
            for step_result in result.stepResults:
                test_steps.append({
                    "status": "PASS" if step_result.success else "FAIL",
                    "comment": step_result.errorMessage if not step_result.success else "",
                    "actualResults": step_result.actualResults
                })

            test_data = {
                "testKey": result.testCaseKey,
                "status": result.testExecutionStatus.upper(),
                "start": datetime.fromisoformat(result.start_timestamp).isoformat(),
                "finish": datetime.fromisoformat(result.end_timestamp).isoformat(),
                "steps": test_steps,
                "evidences": [{"filename": art.name, "data": art.bytes, "contentType": art.mimeType} for art in
                              result.artifacts] if result.artifacts else []
            }
            if result.testExecutionStatus.lower() in ["failed", "error"]:
                test_data["comment"] = result.generalErrorMessage
            tests.append(test_data)

        payload = {
            "info": test_execution_info,
            "tests": tests
        }

        self._execute_xray_request("POST", "import/execution", json=payload)

    def create_test_plan(self, project_key: str, name: str, description: str = None,
                         test_case_keys: List[str] = None) -> str:
        logger.info(f"Creating test plan '{name}' in project {project_key}")

        mutation = """
        mutation CreateTestPlan($testPlan: TestPlanInput!) {
            createTestPlan(testPlan: $testPlan) {
                testPlan {
                    issueId
                    jira(fields: ["key"])
                }
                warnings
            }
        }
        """

        test_plan_input: Dict[str, Any] = {
            "jira": {
                "fields": {
                    "project": {"key": project_key},
                    "summary": name,
                    "issuetype": {"name": "Test Plan"},
                    "description": description or ""
                }
            }
        }

        if test_case_keys:
            test_plan_input["testIssueIds"] = test_case_keys

        variables = {"testPlan": test_plan_input}

        response = self._execute_graphql_query(mutation, variables)
        test_plan_key = response["data"]["createTestPlan"]["testPlan"]["jira"]["key"]
        logger.info(f"Successfully created test plan with key: {test_plan_key}")
        return test_plan_key

    def fetch_test_case_by_key(self, test_case_key: str) -> TestCase:
        jql = f"issue = {test_case_key}"
        results = self._fetch_test_cases_by_jql(jql)
        if not results:
            raise ValueError(f"Test case with key {test_case_key} not found.")
        return results[0]

    def _fetch_test_cases_by_jql(self, jql: str, max_results=100) -> List[TestCase]:
        query = f"""
        query getTests($jql: String!, $limit: Int!) {{
            getTests(jql: $jql, limit: $limit) {{
                results {{
                    issueId
                    projectId
                    testType {{
                        name
                    }}
                    steps {{
                        id
                        action
                        data
                        result
                    }}
                    jira(fields: ["summary", "labels", "parent", "{PRECONDITIONS_FIELD_ID}"])
                }}
            }}
        }}
        """
        variables = {"jql": jql, "limit": max_results}
        response = self._execute_graphql_query(query, variables)
        test_cases = []
        for result in response.get("data", {}).get("getTests", {}).get("results", []):
            jira_fields = result.get("jira", {})
            summary = jira_fields.get("summary", "")
            preconditions = jira_fields.get(PRECONDITIONS_FIELD_ID, "")

            steps = []
            for step in result.get("steps", []):
                steps.append(TestStep(action=step["action"], expected_results=step["result"], test_data=[step["data"]]))

            test_cases.append(
                TestCase(
                    key=result["issueId"],
                    name=summary,
                    summary=summary,
                    preconditions=preconditions,
                    steps=steps,
                    parent_issue_key=jira_fields.get("parent", {}).get("key"),
                    labels=jira_fields.get("labels", []),
                    comment=""  # Comments are not typically fetched with the issue
                )
            )
        return test_cases

    def _get_token(self) -> str:
        auth_url = f"{self.base_url}/api/v2/authenticate"
        auth_data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }
        with httpx.Client() as client:
            response = client.post(auth_url, json=auth_data)
            response.raise_for_status()
            return response.text.strip().replace('"', '')

    def _execute_graphql_query(self, query: str, variables: Dict = None):
        graphql_url = f"{self.base_url}/api/v2/graphql"
        payload: Dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        with httpx.Client() as client:
            response = client.post(graphql_url, headers=self.xray_headers, json=payload)
            response.raise_for_status()
            response_json = response.json()
            if "errors" in response_json:
                raise Exception(f"GraphQL query failed: {response_json['errors']}")
            return response_json

    def _execute_jira_request(self, method: str, endpoint: str, **kwargs):
        url = f"{self.jira_base_url}/rest/api/3/{endpoint}"
        with httpx.Client() as client:
            response = client.request(method, url, auth=self.jira_auth, headers=self.jira_headers, **kwargs)
            response.raise_for_status()
            return response.json() if response.status_code != 204 else None

    def _execute_xray_request(self, method: str, endpoint: str, **kwargs):
        url = f"{self.base_url}/api/v2/{endpoint}"
        with httpx.Client() as client:
            response = client.request(method, url, headers=self.xray_headers, **kwargs)
            response.raise_for_status()
            return response.json() if response.status_code != 204 else None

    def _add_steps_to_test_case(self, issue_id: str, steps: List[TestStep]):
        logger.info(f"Adding {len(steps)} steps to test case {issue_id}")
        mutation = """
        mutation updateTestSteps($issueId: String!, $steps: [TestStepInput!]!) {
            updateTest(
                issueId: $issueId,
                test: {
                    steps: {
                        update: $steps
                    }
                }
            ) {
                test {
                    issueId
                }
                warnings
            }
        }
        """

        step_payloads = []
        for step in steps:
            step_payloads.append({
                "action": step.action,
                "data": "",  # Assuming data is not used in this context
                "result": step.expected_results
            })

        variables = {
            "issueId": issue_id,
            "steps": step_payloads
        }

        self._execute_graphql_query(mutation, variables)
