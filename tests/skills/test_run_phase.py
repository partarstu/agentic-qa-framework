# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import runpy
from pathlib import Path

SCRIPT_PATH = Path(__file__).parents[2] / ".agents" / "skills" / "implementing-changes" / "scripts" / "run_phase.py"
ROLE_TOOLS = runpy.run_path(str(SCRIPT_PATH))["ROLE_TOOLS"]


def test_tester_may_run_exactly_the_three_dashboard_ui_checks():
    npm_rules = [rule for rule in ROLE_TOOLS["tester"] if "npm" in rule]

    assert npm_rules == [
        "Bash(npm --prefix orchestrator/ui run lint)",
        "Bash(npm --prefix orchestrator/ui run build)",
        "Bash(npm --prefix orchestrator/ui run test)",
    ]


def test_reviewer_may_run_no_npm_command():
    assert not any("npm" in rule for rule in ROLE_TOOLS["reviewer"])
