# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

import base64
import os
import shutil
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import List

from allure_commons.logger import AllureFileLogger
from allure_commons.model2 import TestResult, TestStepResult, StatusDetails, Status, Attachment

import config
from common import utils
from common.models import TestExecutionResult
from common.services.test_reporting_client_base import TestReportingClientBase

logger = utils.get_logger(__name__)


class AllureClient(TestReportingClientBase):
    def __init__(self, path: str):
        if not os.path.exists(path):
            raise ValueError(f"The provided path does not exist: {path}")
        self.results_dir = Path(os.path.join(path, config.ALLURE_RESULTS_DIR)).resolve()
        self.report_dir = Path(os.path.join(path, config.ALLURE_REPORT_DIR)).resolve()
        os.makedirs(self.results_dir, exist_ok=True)
        self.file_logger = AllureFileLogger(self.results_dir)

    def generate_report(self, test_execution_results: List[TestExecutionResult]):
        logger.info("Generating Allure report...")
        self._clean_directories()
        for test_execution_result in test_execution_results:
            self._process_test_execution_result(test_execution_result)
        self._generate_html()
        return "Allure report generation initiated."

    def _process_test_execution_result(self, test_execution_result: TestExecutionResult):
        test_result = TestResult()
        test_result.name = test_execution_result.testCaseName
        test_result.uuid = str(uuid.uuid4())
        test_result.start = int(
            datetime.fromisoformat(test_execution_result.start_timestamp.replace("Z", "+00:00")).timestamp() * 1000)

        # Extract logs from artifacts if available using the common utility
        logs = utils.get_execution_logs_from_artifacts(test_execution_result.artifacts)

        # Map test status
        if test_execution_result.testExecutionStatus == "passed":
            test_result.status = Status.PASSED
        elif test_execution_result.testExecutionStatus == "failed":
            test_result.status = Status.FAILED
            test_result.statusDetails = StatusDetails(message=test_execution_result.generalErrorMessage,
                                                      trace=logs)
        elif test_execution_result.testExecutionStatus == "error":
            test_result.status = Status.BROKEN
            test_result.statusDetails = StatusDetails(message=test_execution_result.generalErrorMessage,
                                                      trace=logs)

        # Add steps
        for step_result in test_execution_result.stepResults:
            step = TestStepResult()
            step.name = step_result.stepDescription
            step.status = Status.PASSED if step_result.success else Status.FAILED
            if step_result.success:
                step.statusDetails = StatusDetails(message=step_result.actualResults)
            else:
                step.statusDetails = StatusDetails(message=step_result.errorMessage)
            test_result.steps.append(step)
        end_timestamp_utc = test_execution_result.end_timestamp.replace("Z", "+00:00")
        test_result.stop = int(datetime.fromisoformat(end_timestamp_utc).timestamp() * 1000)

        if test_execution_result.artifacts:
            for artifact in test_execution_result.artifacts:
                if artifact.bytes:
                    decoded_bytes = base64.b64decode(artifact.bytes)
                    extension = artifact.mime_type.split('/')[-1] if artifact.mime_type else 'bin'
                    unique_filename = f"{uuid.uuid4()}-attachment.{extension}"
                    attachment_file_path = self.results_dir / unique_filename
                    with open(attachment_file_path, 'wb') as f:
                        f.write(decoded_bytes)
                    test_result.attachments.append(
                        Attachment(name=artifact.name, source=unique_filename, type=artifact.mime_type))
        self.file_logger.report_result(test_result)

    def _generate_html(self):
        logger.info(f"Generating Allure HTML report in {self.report_dir}...")
        try:
            allure_home = os.environ.get('ALLURE_HOME')
            if allure_home:
                allure_executable = os.path.join(allure_home, 'bin', 'allure')
            else:
                allure_executable = 'allure'
                logger.warning("ALLURE_HOME environment variable not set. Assuming 'allure' is in the system's PATH.")

            command = [allure_executable, '-v', "generate", "-o", str(self.report_dir), "--clean", '--single-file',
                       str(self.results_dir)]
            subprocess.run(command, check=True, capture_output=True, text=True)
            logger.info("Allure report generated successfully.")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to generate Allure report: {e}")
            logger.error(f"Stdout: {e.stdout}")
            logger.error(f"Stderr: {e.stderr}")
            raise
        except FileNotFoundError:
            logger.error("Allure command not found. Please ensure Allure is installed and ALLURE_HOME is set, "
                         "or that 'allure' is in your PATH.")
            raise

    def _clean_directories(self):
        logger.info(f"Cleaning up {self.results_dir} and {self.report_dir} folders before report generation.")
        if self.results_dir.exists():
            for item in self.results_dir.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
            logger.info(f"Cleaned up {self.results_dir}.")

        if self.report_dir.exists():
            for item in self.report_dir.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
            logger.info(f"Cleaned up {self.report_dir}.")
