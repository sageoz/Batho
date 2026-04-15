"""
Git-aware incremental indexing helpers.

This module discovers changed files since a snapshot commit and provides
status-aware diff records for incremental graph patching.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SNAPSHOT_ID_RE = re.compile(
    r"^batho_(?P<project>.+)_(?P<commit>[0-9a-f]{7,64}|nogit)_(?P<timestamp>\d{8}T\d{6}(?:\d{6})?Z)$"
)


@dataclass(frozen=True)
class GitDiffEntry:
    status: str
    path: str


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


def parse_snapshot_commit(snapshot_id: str) -> str | None:
    matched = _SNAPSHOT_ID_RE.match(snapshot_id.strip())
    if not matched:
        return None

    commit = matched.group("commit").strip().lower()
    if not commit or commit == "nogit":
        return None
    return commit


def extract_snapshot_commit(
    snapshot_id: str,
    snapshot_payload: dict[str, Any] | None = None,
) -> str | None:
    """
    Extract commit SHA from snapshot ID (new format) or snapshot payload metadata.

    Supports both:
    - new format: batho_{project}_{sha}_{timestamp}
    - legacy snapshots with metadata fields
    """
    commit = parse_snapshot_commit(snapshot_id)
    if commit:
        return commit

    if not isinstance(snapshot_payload, dict):
        return None

    metadata_candidates: list[str | None] = []

    git_metadata = snapshot_payload.get("git_metadata")
    if isinstance(git_metadata, dict):
        metadata_candidates.extend(
            [
                str(git_metadata.get("commit_sha") or "").strip(),
                str(git_metadata.get("commit") or "").strip(),
            ]
        )

    git_section = snapshot_payload.get("git")
    if isinstance(git_section, dict):
        metadata_candidates.extend(
            [
                str(git_section.get("commit_sha") or "").strip(),
                str(git_section.get("commit") or "").strip(),
            ]
        )

    metadata_candidates.append(str(snapshot_payload.get("commit_sha") or "").strip())

    for candidate in metadata_candidates:
        normalized = candidate.lower()
        if re.fullmatch(r"[0-9a-f]{7,64}", normalized):
            return normalized

    return None


def _parse_name_status_output(output: str) -> list[GitDiffEntry]:
    entries: list[GitDiffEntry] = []

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        parts = line.split("\t")
        if len(parts) < 2:
            continue

        raw_status = parts[0].strip().upper()
        status = raw_status[0] if raw_status else ""

        if status == "R" and len(parts) >= 3:
            # Treat rename as delete old + add new for graph patch correctness.
            old_path = parts[1].strip()
            new_path = parts[2].strip()
            if old_path:
                entries.append(GitDiffEntry(status="D", path=old_path))
            if new_path:
                entries.append(GitDiffEntry(status="A", path=new_path))
            continue

        if status == "C" and len(parts) >= 3:
            copied_path = parts[2].strip()
            if copied_path:
                entries.append(GitDiffEntry(status="A", path=copied_path))
            continue

        if status not in {"A", "M", "D", "T"}:
            continue

        target_path = parts[-1].strip()
        if not target_path:
            continue

        entries.append(
            GitDiffEntry(status=("M" if status == "T" else status), path=target_path)
        )

    deduped: dict[tuple[str, str], GitDiffEntry] = {}
    for entry in entries:
        key = (entry.status, entry.path)
        deduped[key] = entry
    return sorted(deduped.values(), key=lambda item: (item.path, item.status))


def get_changed_file_status_since(
    snapshot_id: str,
    repo_root: str | Path,
    snapshot_payload: dict[str, Any] | None = None,
) -> list[GitDiffEntry] | None:
    repo_path = Path(repo_root).resolve()
    if not is_git_repo(repo_path):
        return None

    base_commit = extract_snapshot_commit(snapshot_id, snapshot_payload)
    if not base_commit:
        return None

    result = _run_git(
        repo_path,
        ["diff", "--name-status", "-M", "--diff-filter=ACDMRT", f"{base_commit}..HEAD"],
    )
    if result is None:
        return None

    return _parse_name_status_output(result.stdout)


def get_changed_files_since(
    snapshot_id: str,
    repo_root: str | Path,
    snapshot_payload: dict[str, Any] | None = None,
) -> list[str] | None:
    entries = get_changed_file_status_since(snapshot_id, repo_root, snapshot_payload)
    if entries is None:
        return None

    files = sorted({entry.path for entry in entries if entry.path})
    return files
