# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

# /// script
# requires-python = ">=3.10"
# dependencies = ["diff-cover==10.5.1"]
# ///

"""Measure the line coverage of the pytest-cov report of a repository, and of the source lines a diff changes.

Reads coverage.xml in the repository root and prints the total line coverage. With a diff file, also runs diff-cover
over the changed lines and prints the coverage of the changed source lines and the uncovered ones; the tests and the
code templates of the skills are not source. coverage.py does not report a module in a directory without __init__.py
that no test imports, and diff-cover silently skips files without coverage data, so a changed source file without
coverage data is an error.
"""

import argparse
import json
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path
from xml.etree import ElementTree

COVERAGE_REPORT_NAME = "coverage.xml"
NON_SOURCE_PATTERNS = ("tests/*", ".agents/skills/*/resources/*")
CHANGED_FILE_PREFIX = "+++ b/"
DIFF_COVER_REPORT_NAME = "diff-cover.json"
# diff-cover only parses the report and the diff, which takes seconds; the limit only stops a hung process.
DIFF_COVER_TIMEOUT_SECONDS = 300


def _percent(covered: int, total: int) -> str:
    # Rounded down, so that a value just below a threshold is never shown as reaching it.
    hundredths = covered * 10000 // total
    return f"{hundredths // 100}.{hundredths % 100:02d}%"


def total_line_coverage(report: ElementTree.Element) -> tuple[int, int]:
    """Return the number of covered lines and the total number of lines of the report."""
    return int(report.get("lines-covered")), int(report.get("lines-valid"))


def changed_source_files(diff_file: Path) -> list[str]:
    """Return the repository-relative paths of the Python source files the diff adds or changes."""
    lines = diff_file.read_bytes().decode(errors="replace").splitlines()
    paths = (line.removeprefix(CHANGED_FILE_PREFIX) for line in lines if line.startswith(CHANGED_FILE_PREFIX))
    return [
        path
        for path in paths
        if path.endswith(".py") and not any(fnmatch(path, pattern) for pattern in NON_SOURCE_PATTERNS)
    ]


def files_without_coverage_data(report: ElementTree.Element, changed_sources: list[str]) -> list[str]:
    """Return the changed source files the report has no coverage data for."""
    measured = {element.get("filename") for element in report.iter("class")}
    return [path for path in changed_sources if path not in measured]


def changed_line_coverage(repo: Path, report_file: Path, diff_file: Path) -> dict:
    """Run diff-cover over the diff and return its JSON report."""
    json_report = diff_file.parent / DIFF_COVER_REPORT_NAME
    subprocess.run(
        [
            sys.executable,
            "-m",
            "diff_cover.diff_cover_tool",
            str(report_file),
            "--diff-file",
            str(diff_file),
            "--format",
            f"json:{json_report}",
            "--quiet",
        ],
        cwd=repo,
        check=True,
        timeout=DIFF_COVER_TIMEOUT_SECONDS,
    )
    return json.loads(json_report.read_text(encoding="utf-8"))


def main() -> None:
    """Parse the arguments and print the total coverage and, with a diff file, the changed-line coverage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path, help="root directory of the repository")
    parser.add_argument("diff_file", nargs="?", type=Path, help="diff whose changed lines are measured")
    arguments = parser.parse_args()
    if not arguments.repo.is_dir():
        parser.error(f"not a directory: {arguments.repo}")
    if arguments.diff_file is not None and not arguments.diff_file.is_file():
        parser.error(f"not a file: {arguments.diff_file}")

    report_file = arguments.repo / COVERAGE_REPORT_NAME
    if not report_file.is_file():
        sys.exit(f"No {COVERAGE_REPORT_NAME} in {arguments.repo}: run the unit tests with coverage first.")
    report = ElementTree.parse(report_file).getroot()
    covered, total = total_line_coverage(report)
    print(f"TOTAL COVERAGE: {_percent(covered, total)} ({covered} of {total} lines)")
    if arguments.diff_file is None:
        return

    changed_sources = changed_source_files(arguments.diff_file)
    missing = files_without_coverage_data(report, changed_sources)
    if missing:
        sys.exit(f"No coverage data for changed source files, e.g. because no test imports them: {', '.join(missing)}")
    diff_cover_report = changed_line_coverage(arguments.repo, report_file, arguments.diff_file)
    # On Windows diff-cover reports the paths in lower case; the diff keeps their real case.
    real_paths = {path.lower(): path for path in changed_sources}
    source_stats = {
        real_paths[path.lower()]: stats
        for path, stats in diff_cover_report["src_stats"].items()
        if path.lower() in real_paths
    }
    covered_changed = sum(len(stats["covered_lines"]) for stats in source_stats.values())
    measured = covered_changed + sum(len(stats["violation_lines"]) for stats in source_stats.values())
    if measured == 0:
        print("CHANGED-LINE COVERAGE: no changed lines with coverage data")
        return
    print(f"CHANGED-LINE COVERAGE: {_percent(covered_changed, measured)} ({covered_changed} of {measured} lines)")
    uncovered_files = {
        path: stats["violation_lines"] for path, stats in source_stats.items() if stats["violation_lines"]
    }
    if uncovered_files:
        print("UNCOVERED CHANGED LINES:")
        for path, lines in sorted(uncovered_files.items()):
            print(f"- {path}: {', '.join(map(str, lines))}")


if __name__ == "__main__":
    main()
