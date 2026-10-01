"""
Git-aware incremental indexing helpers.

This module discovers changed files since a snapshot commit and provides
status-aware diff records for incremental graph patching.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


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
    # Strip session-level git overrides — an inherited GIT_DIR/GIT_WORK_TREE
    # (e.g. exported by a parent shell sitting in another repo, or set by an
    # outer build system) would silently redirect these rev-parse calls to a
    # foreign gitdir while cwd points at ours.
    for _k in (
        "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR",
        "GIT_CEILING_DIRECTORIES", "GIT_DISCOVERY_ACROSS_FILESYSTEM",
        "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    ):
        env.pop(_k, None)

    try:
        return subprocess.run(
            [git_bin, *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
            env=env,
            timeout=15,  # a stalled git (NFS/FUSE, credential helper) must not
        )               # block the watcher engine lock indefinitely
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
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


def resolve_git_dir(repo_root: Path) -> tuple[Path, Path] | None:
    """Resolve (git_dir, common_dir) for a repo, or None if not a git worktree.

    ``git_dir`` is the per-worktree private dir (holds ``index``, ``HEAD`` —
    ``<main>/.git/worktrees/<id>`` for linked worktrees); ``common_dir`` is the
    shared dir (holds ``refs/``, ``packed-refs``, ``MERGE_HEAD``, ``hooks/``).
    Both coincide for a regular repo. Never parses gitfiles — ``rev-parse`` is
    the only resolution mechanism.
    """
    res = _run_git(repo_root, ["rev-parse", "--absolute-git-dir"])
    if res is not None and res.stdout.strip():
        git_dir = Path(res.stdout.strip()).resolve()
    else:
        # Fallback for older git without --absolute-git-dir
        res = _run_git(repo_root, ["rev-parse", "--git-dir"])
        if res is None or not res.stdout.strip():
            return None
        git_dir = Path(res.stdout.strip())
        if not git_dir.is_absolute():
            git_dir = (repo_root / git_dir).resolve()

    bare = _run_git(repo_root, ["rev-parse", "--is-bare-repository"])
    if bare is not None and bare.stdout.strip().lower() == "true":
        return None

    cres = _run_git(repo_root, ["rev-parse", "--path-format=absolute", "--git-common-dir"])
    if cres is not None and cres.stdout.strip():
        common_dir = Path(cres.stdout.strip()).resolve()
    else:
        cres = _run_git(repo_root, ["rev-parse", "--git-common-dir"])
        if cres is None or not cres.stdout.strip():
            common_dir = git_dir
        else:
            common_dir = Path(cres.stdout.strip())
            if not common_dir.is_absolute():
                # Output may be relative to git_dir
                common_dir = (git_dir / common_dir).resolve()

    return git_dir, common_dir


def _collect_candidate_files(root: Path, ignore_spec: Any = None) -> list[Path]:
    """Collect all non-ignored files under root using os.scandir for speed.

    ``ignore_spec`` lets callers reuse the exact spec the build path uses
    (config-driven defaults/user patterns + .gitignore); when omitted, a
    default spec is loaded.
    """
    import os
    from batho.utils.ignore import load_ignore_spec, should_ignore_path

    if ignore_spec is None:
        ignore_spec = load_ignore_spec(root)
    candidates = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    full_path = Path(entry.path)
                    if should_ignore_path(full_path, root, ignore_spec, include_hidden=True):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(full_path)
                    elif entry.is_file(follow_symlinks=False):
                        candidates.append(full_path)
        except (OSError, PermissionError):
            continue
    return candidates
