"""
Git-aware incremental indexing helpers.

This module discovers changed files since a snapshot commit and provides
status-aware diff records for incremental graph patching.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _run_git(
    repo_root: Path, args: list[str]
) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def is_git_repo(repo_root: Path) -> bool:
    result = _run_git(repo_root, ["rev-parse", "--is-inside-work-tree"])
    if result is None:
        return False
    return result.stdout.strip().lower() == "true"


def get_head_commit(repo_root: Path) -> str | None:
    result = _run_git(repo_root, ["rev-parse", "HEAD"])
    if result is None:
        return None
    commit = result.stdout.strip().lower()
    return commit if commit else None


def get_current_branch(repo_root: Path) -> str | None:
    result = _run_git(repo_root, ["rev-parse", "--abbrev-ref", "HEAD"])
    if result is None:
        return None
    branch = result.stdout.strip()
    return branch if branch else None


def _collect_candidate_files(root: Path) -> list[Path]:
    """Collect all non-ignored files under root."""
    from batho.utils.ignore import walk_ignored_filtered
    candidates = []
    for dirpath, dirnames, filenames in walk_ignored_filtered(root):
        for filename in filenames:
            file_path = dirpath / filename
            if file_path.is_file():
                candidates.append(file_path)
    return candidates
