"""Repository registry — deterministic train/holdout split."""

from __future__ import annotations

import hashlib
from typing import Any


def _repo_hash(repo: dict[str, Any]) -> str:
    key = f"{repo['name']}:{repo['url']}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def split_repos(
    repos: list[dict[str, Any]],
    holdout_count: int = 2,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (train, holdout) split deterministic by repo name+url hash."""

    sorted_repos = sorted(repos, key=lambda r: _repo_hash(r))
    holdout = sorted_repos[:holdout_count]
    train = sorted_repos[holdout_count:]
    return train, holdout


def repo_display_name(repo: dict[str, Any]) -> str:
    return f"{repo['name']} ({repo['language']})"
