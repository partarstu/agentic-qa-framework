# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Run one headless phase of an implementing-changes run: a reviewer or a tester in its own ``claude -p`` process.

The brief file is the prompt, the role's instruction file (resources/<role>.md) is appended to the system prompt, and
the process is confined so that it can edit only the run directory. The raw JSON output of the run is kept in
<run dir>/logs/<brief name>.json; only a one-line summary is printed. The exit code is the one of ``claude``.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
ROLE_TOOLS = {
    "reviewer": ["Bash(uv run ruff *)"],
    "tester": ["Bash(uv run *)", "Bash(env UV_PROJECT_ENVIRONMENT=* uv run *)"],
}


def _absolute_rule_path(directory: Path) -> str:
    """Return the directory in the ``//`` form the permission rules use for absolute paths."""
    resolved = directory.resolve()
    if resolved.drive:
        return f"//{resolved.drive[0].lower()}{resolved.as_posix()[len(resolved.drive) :]}"
    return f"/{resolved.as_posix()}"


def _child_environment() -> dict[str, str]:
    """Return the environment without the variables that make ``claude`` refuse to start inside a running session."""
    return {name: value for name, value in os.environ.items() if not name.startswith("CLAUDE")}


def main() -> None:
    """Parse the arguments, run the phase and print its summary line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=sorted(ROLE_TOOLS), help="the headless role to run")
    parser.add_argument("run_dir", type=Path, help="run directory of the implementing-changes run")
    parser.add_argument("brief_file", type=Path, help="brief file the lead wrote for this phase; it is the prompt")
    parser.add_argument("--model", required=True, help="model alias or ID for the role")
    parser.add_argument("--effort", required=True, choices=["low", "medium", "high", "xhigh", "max"])
    arguments = parser.parse_args()
    if not arguments.run_dir.is_dir():
        parser.error(f"not a directory: {arguments.run_dir}")
    if not arguments.brief_file.is_file():
        parser.error(f"not a file: {arguments.brief_file}")
    claude = shutil.which("claude")
    if claude is None:
        sys.exit("claude is not on the PATH")

    run_dir = arguments.run_dir.resolve()
    allowed_tools = [f"Edit({_absolute_rule_path(run_dir)}/**)", *ROLE_TOOLS[arguments.role]]
    command = [
        claude,
        "-p",
        "--model",
        arguments.model,
        "--effort",
        arguments.effort,
        "--append-system-prompt-file",
        str(SKILL_DIR / "resources" / f"{arguments.role}.md"),
        "--add-dir",
        str(run_dir),
        "--permission-mode",
        "dontAsk",
        "--permission-prompts",
        "none",
        "--allowedTools",
        *allowed_tools,
        # The allow rules are written for Bash; the PowerShell tool would only be denied.
        "--disallowedTools",
        "PowerShell",
        "--no-session-persistence",
        "--output-format",
        "json",
    ]
    completed = subprocess.run(
        command,
        input=arguments.brief_file.read_text(encoding="utf-8"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_child_environment(),
    )
    log_dir = run_dir / "logs"
    log_dir.mkdir(exist_ok=True)
    (log_dir / f"{arguments.brief_file.stem}.json").write_text(completed.stdout, encoding="utf-8")
    if completed.stderr.strip():
        (log_dir / f"{arguments.brief_file.stem}.stderr").write_text(completed.stderr, encoding="utf-8")

    try:
        output = json.loads(completed.stdout)
        summary = f"turns={output.get('num_turns')} cost=${output.get('total_cost_usd', 0):.2f}: {output.get('result')}"
    except ValueError:
        summary = f"no JSON result; last output: {completed.stdout[-500:]!r} {completed.stderr[-500:]!r}"
    print(f"{arguments.role} exit={completed.returncode} {summary}")
    sys.exit(completed.returncode)


if __name__ == "__main__":
    main()
