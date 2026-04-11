"""Git gate — commit/revert decisions in Batho working tree."""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)


def _run_git(
    args: list[str],
    *,
    cwd: Path,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def is_tree_clean(cwd: Path) -> bool:
    """Check if git working tree is clean (no uncommitted changes)."""
    result = _run_git(["status", "--porcelain"], cwd=cwd)
    return result.returncode == 0 and not result.stdout.strip()


def check_tree_clean(cwd: Path, *, allow_dirty: bool = False) -> None:
    """Fail fast if tree is dirty, unless allow_dirty is set."""
    if is_tree_clean(cwd):
        return
    if allow_dirty:
        _LOGGER.warning("working tree is dirty but allow_dirty=True")
        return
    raise RuntimeError(
        "Batho working tree is dirty. Commit or stash changes before running BSGautoresearch."
    )


def accept_candidate(
    batho_root: Path,
    plugin_target_rel: str,
    *,
    iteration: int,
    score: float,
    best_score: float,
    plugin_doc: dict[str, Any],
    accepted_dir: Path,
) -> dict[str, Any]:
    """Accept a candidate: git add + commit the plugin target.

    Returns a decision record dict.
    """

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    delta = score - best_score

    # Copy to accepted archive
    import yaml

    accepted_dir.mkdir(parents=True, exist_ok=True)
    archive_name = f"bsg_autoresearch_{timestamp}.yaml"
    archive_path = accepted_dir / archive_name
    content = yaml.dump(
        plugin_doc, default_flow_style=False, sort_keys=False, allow_unicode=True
    )
    archive_path.write_text(content, encoding="utf-8")

    # Git add + commit
    plugin_target = batho_root / plugin_target_rel
    _run_git(["add", plugin_target_rel], cwd=batho_root)

    # Also add the accepted archive
    archive_rel = archive_path.relative_to(batho_root)
    _run_git(["add", str(archive_rel)], cwd=batho_root)

    commit_msg = f"bsg-autoresearch: accept iter {iteration} (+{delta:.4f})"
    result = _run_git(["commit", "-m", commit_msg], cwd=batho_root)

    if result.returncode != 0:
        _LOGGER.error("git commit failed: %s", result.stderr.strip())
        return {
            "decision": "commit_failed",
            "iteration": iteration,
            "score": score,
            "delta": delta,
            "error": result.stderr.strip(),
        }

    _LOGGER.info("accepted iter %d: score=%.6f delta=+%.4f", iteration, score, delta)

    return {
        "decision": "accepted",
        "iteration": iteration,
        "score": score,
        "best_score": best_score,
        "delta": delta,
        "commit_msg": commit_msg,
        "archive_path": str(archive_rel),
    }


def revert_candidate(
    batho_root: Path,
    plugin_target_rel: str,
    *,
    iteration: int,
    score: float,
    best_score: float,
    reason: str,
) -> dict[str, Any]:
    """Revert a candidate: git restore the plugin target.

    Returns a decision record dict.
    """

    _run_git(["restore", "--source=HEAD", "--", plugin_target_rel], cwd=batho_root)

    delta = score - best_score
    _LOGGER.info(
        "reverted iter %d: score=%.6f best=%.6f delta=%.4f reason=%s",
        iteration,
        score,
        best_score,
        delta,
        reason,
    )

    return {
        "decision": "reverted",
        "iteration": iteration,
        "score": score,
        "best_score": best_score,
        "delta": delta,
        "reason": reason,
    }
