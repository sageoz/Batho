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
    import os
    import shutil

    # Construct a safe platform-specific PATH to mitigate command injection/path exploitation
    if os.name == "nt":
        prog_files = os.environ.get("ProgramFiles", "C:\\Program Files")
        prog_files_x86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")
        system_root = os.environ.get("SystemRoot", "C:\\Windows")
        safe_path = ";".join([
            f"{system_root}\\System32",
            system_root,
            f"{system_root}\\System32\\Wbem",
            f"{prog_files}\\Git\\cmd",
            f"{prog_files}\\Git\\bin",
            f"{prog_files_x86}\\Git\\cmd",
            f"{prog_files_x86}\\Git\\bin",
        ])
    else:
        safe_path = "/usr/bin:/usr/local/bin:/usr/sbin:/sbin:/bin"

    git_bin = shutil.which("git", path=safe_path) or "git"

    env = os.environ.copy()
    env["PATH"] = safe_path
    env["GIT_PAGER"] = "cat"

    try:
        return subprocess.run(
            [git_bin, *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
            env=env,
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
    """Collect all non-ignored files under root using os.scandir for speed."""
    import os
    from batho.utils.ignore import load_ignore_spec, should_ignore_path

    spec = load_ignore_spec(root)
    candidates = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    full_path = Path(entry.path)
                    if should_ignore_path(full_path, root, spec, include_hidden=True):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(full_path)
                    elif entry.is_file(follow_symlinks=False):
                        candidates.append(full_path)
        except (OSError, PermissionError):
            continue
    return candidates
