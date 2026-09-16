# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Snapshot the git working tree, or diff it against an earlier snapshot.

Without a tree id, records the working tree (untracked files included) and prints its tree id. With a tree id, writes
every change made since that snapshot to task.diff in the run directory and prints the changed paths. A separate index
file inside the run directory is used, so the real git index, the working tree and the history stay untouched.
"""

import argparse
import os
import re
import subprocess
from pathlib import Path

GIT_TIMEOUT_SECONDS = 300
SNAPSHOT_INDEX_NAME = "snapshot.index"
DIFF_FILE_NAME = "task.diff"
TREE_ID_PATTERN = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


def _git(run_dir: Path, *args: str) -> bytes:
    environment = {**os.environ, "GIT_INDEX_FILE": str(run_dir.resolve() / SNAPSHOT_INDEX_NAME)}
    completed = subprocess.run(
        ["git", *args], env=environment, check=True, timeout=GIT_TIMEOUT_SECONDS, capture_output=True
    )
    return completed.stdout


def _tree_id(value: str) -> str:
    if not TREE_ID_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError(f"not a git tree id: {value!r}")
    return value


def snapshot(run_dir: Path) -> str:
    """Record the current working tree, untracked files included, and return its tree id."""
    _git(run_dir, "add", "--all")
    return _git(run_dir, "write-tree").decode().strip()


def write_diff(run_dir: Path, base_tree: str) -> str:
    """Write all changes made since ``base_tree`` to the diff file and return the changed paths with their status."""
    snapshot(run_dir)
    # Kept as bytes: changed files are not guaranteed to be UTF-8.
    (run_dir / DIFF_FILE_NAME).write_bytes(_git(run_dir, "diff", "--cached", base_tree))
    return _git(run_dir, "diff", "--cached", "--name-status", base_tree).decode(errors="replace")


def main() -> None:
    """Parse the arguments and take a snapshot or write the diff."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path, help="directory for the snapshot index and the diff file")
    parser.add_argument("base_tree", nargs="?", type=_tree_id, help="tree id printed by an earlier snapshot")
    arguments = parser.parse_args()
    arguments.run_dir.mkdir(parents=True, exist_ok=True)
    if arguments.base_tree is None:
        print(snapshot(arguments.run_dir))
    else:
        print(write_diff(arguments.run_dir, arguments.base_tree), end="")


if __name__ == "__main__":
    main()
