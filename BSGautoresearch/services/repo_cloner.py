"""Shallow clone / update target repositories."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)


def _run_git(
    args: list[str], *, cwd: Path | None = None, timeout: int = 120
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def ensure_repo(
    repo: dict[str, Any],
    clone_root: Path,
    *,
    depth: int = 1,
) -> Path:
    """Clone (or fetch+reset) a repository into clone_root/<name>.

    Returns the resolved path to the cloned directory.
    """

    repo_name = repo["name"]
    repo_url = repo["url"]
    branch = repo.get("branch", "main")
    target = clone_root / repo_name

    if target.exists() and (target / ".git").is_dir():
        _LOGGER.info("fetching %s (branch=%s)", repo_name, branch)
        _run_git(["fetch", "--depth", str(depth), "origin", branch], cwd=target)
        _run_git(["checkout", branch], cwd=target)
        _run_git(["reset", "--hard", f"origin/{branch}"], cwd=target)
    else:
        _LOGGER.info("cloning %s → %s (depth=%d)", repo_url, target, depth)
        target.parent.mkdir(parents=True, exist_ok=True)
        result = _run_git(
            [
                "clone",
                "--depth",
                str(depth),
                "--branch",
                branch,
                "--single-branch",
                repo_url,
                str(target),
            ]
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"git clone failed for {repo_name}: {result.stderr.strip()}"
            )

    pinned_commit = repo.get("commit")
    if pinned_commit:
        _LOGGER.info("pinning %s to commit %s", repo_name, pinned_commit)
        _run_git(["checkout", pinned_commit], cwd=target)

    return target


def ensure_all_repos(
    repos: list[dict[str, Any]],
    clone_root: Path,
    *,
    depth: int = 1,
) -> dict[str, Path]:
    """Clone/update all repos. Returns {name: path} mapping."""

    paths: dict[str, Path] = {}
    for repo in repos:
        path = ensure_repo(repo, clone_root, depth=depth)
        paths[repo["name"]] = path
    return paths
