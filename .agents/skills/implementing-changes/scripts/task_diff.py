# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Snapshot the git working tree of a repository, or diff it against an earlier snapshot.

Without a tree id, records the working tree (untracked files included) and prints its tree id. With a tree id, writes
every change made since that snapshot to a diff file in the run directory (task.diff unless another name is given) and
prints the changed paths. A separate index file inside the run directory is used, so the real git index, the working
tree and the history stay untouched.
"""

import argparse
import os
import re
import subprocess
from pathlib import Path

GIT_TIMEOUT_SECONDS = 300
SNAPSHOT_INDEX_NAME = "snapshot.index"
DEFAULT_DIFF_FILE_NAME = "task.diff"
TREE_ID_PATTERN = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


def _git(repo: Path, run_dir: Path, *args: str) -> bytes:
    environment = {**os.environ, "GIT_INDEX_FILE": str(run_dir.resolve() / SNAPSHOT_INDEX_NAME)}
    completed = subprocess.run(
        ["git", *args], cwd=repo, env=environment, check=True, timeout=GIT_TIMEOUT_SECONDS, capture_output=True
    )
    return completed.stdout


def _tree_id(value: str) -> str:
    if not TREE_ID_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError(f"not a git tree id: {value!r}")
    return value


def _file_name(value: str) -> str:
    if value in ("", ".", "..") or Path(value).name != value:
        raise argparse.ArgumentTypeError(f"not a plain file name: {value!r}")
    return value


def snapshot(repo: Path, run_dir: Path) -> str:
    """Record the current working tree, untracked files included, and return its tree id."""
    if not (run_dir / SNAPSHOT_INDEX_NAME).exists():
        # Starting from HEAD keeps tracked files that an ignore rule matches, which "add --all" skips in an empty index.
        _git(repo, run_dir, "read-tree", "HEAD")
    _git(repo, run_dir, "add", "--all")
    return _git(repo, run_dir, "write-tree").decode().strip()


def write_diff(repo: Path, run_dir: Path, base_tree: str, diff_file_name: str) -> str:
    """Write all changes made since ``base_tree`` to the diff file and return the changed paths with their status."""
    snapshot(repo, run_dir)
    # Kept as bytes: changed files are not guaranteed to be UTF-8.
    (run_dir / diff_file_name).write_bytes(_git(repo, run_dir, "diff", "--cached", base_tree))
    return _git(repo, run_dir, "diff", "--cached", "--name-status", base_tree).decode(errors="replace")


def main() -> None:
    """Parse the arguments and take a snapshot or write the diff."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path, help="root directory of the git repository")
    parser.add_argument("run_dir", type=Path, help="directory for the snapshot index and the diff file")
    parser.add_argument("base_tree", nargs="?", type=_tree_id, help="tree id printed by an earlier snapshot")
    parser.add_argument(
        "diff_file_name", nargs="?", type=_file_name, default=DEFAULT_DIFF_FILE_NAME, help="name of the diff file"
    )
    arguments = parser.parse_args()
    if not arguments.repo.is_dir():
        parser.error(f"not a directory: {arguments.repo}")
    arguments.run_dir.mkdir(parents=True, exist_ok=True)
    if arguments.base_tree is None:
        print(snapshot(arguments.repo, arguments.run_dir))
    else:
        print(write_diff(arguments.repo, arguments.run_dir, arguments.base_tree, arguments.diff_file_name), end="")


if __name__ == "__main__":
    main()
