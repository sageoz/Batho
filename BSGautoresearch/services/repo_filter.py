"""Filter repositories by size/file/binary thresholds."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)


def _dir_size_mb(path: Path) -> float:
    total = 0
    for f in path.rglob("*"):
        if f.is_file():
            total += f.stat().st_size
    return total / (1024 * 1024)


def _count_files(path: Path) -> int:
    count = 0
    for f in path.rglob("*"):
        if f.is_file():
            count += 1
    return count


def check_repo(
    repo: dict[str, Any],
    repo_path: Path,
    *,
    max_size_mb: float = 500,
    max_files: int = 200000,
    max_single_file_mb: float = 10,
) -> tuple[bool, list[str]]:
    """Check a repo against size/file thresholds.

    Returns (passes, reasons) where reasons lists any violations.
    """

    reasons: list[str] = []

    size = _dir_size_mb(repo_path)
    if size > max_size_mb:
        reasons.append(f"repo size {size:.1f}MB > {max_size_mb}MB limit")

    file_count = _count_files(repo_path)
    if file_count > max_files:
        reasons.append(f"file count {file_count} > {max_files} limit")

    for f in repo_path.rglob("*"):
        if f.is_file():
            fsize_mb = f.stat().st_size / (1024 * 1024)
            if fsize_mb > max_single_file_mb:
                reasons.append(
                    f"file {f} is {fsize_mb:.1f}MB > {max_single_file_mb}MB limit"
                )
                break  # one violation is enough

    return len(reasons) == 0, reasons


def collect_source_files(
    repo_path: Path,
    include_globs: list[str],
    exclude_globs: list[str],
) -> list[Path]:
    """Collect source files matching include/exclude globs."""

    import fnmatch

    matched: list[Path] = []
    for pattern in include_globs:
        for fpath in repo_path.glob(pattern):
            if not fpath.is_file():
                continue
            rel = fpath.relative_to(repo_path)
            rel_str = rel.as_posix()
            excluded = False
            for excl in exclude_globs:
                if fnmatch.fnmatch(rel_str, excl):
                    excluded = True
                    break
            if not excluded:
                matched.append(fpath)
    return sorted(set(matched))
