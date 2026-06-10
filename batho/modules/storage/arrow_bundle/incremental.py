"""Incremental change detection engine backed by Arrow Bundle file_tracking.

Replaces batho/modules/extraction/incremental_engine.py — no SQLite dependency.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from batho.utils.hash import compute_file_hash_cached

LOGGER = logging.getLogger(__name__)


class FileChangeType:
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"


@dataclass
class FileChange:
    path: str
    change_type: str
    old_hash: str | None = None
    new_hash: str | None = None


class IncrementalEngine:
    """Incremental extraction engine backed by BathoBundle file_tracking."""

    def __init__(self, bundle: Any, run_uuid: str) -> None:
        self.db = bundle
        self.run_uuid = run_uuid

    def scan_changes(
        self,
        root: Path,
        max_file_size_kb: int | None = None,
        strict_hashing: bool = True,
    ) -> list[FileChange]:
        """Scan filesystem for added/modified/deleted files."""
        from batho.modules.graph.incremental import _collect_candidate_files

        known_tracking = self.db.get_all_file_tracking()
        max_bytes = (max_file_size_kb * 1024) if max_file_size_kb else None
        changes: list[FileChange] = []
        current_files: set[str] = set()

        for abs_path in _collect_candidate_files(root):
            try:
                rel = abs_path.relative_to(root).as_posix()
            except ValueError:
                continue
            current_files.add(rel)

            try:
                st = abs_path.stat()
            except OSError:
                continue

            tracked = known_tracking.get(rel)
            old_hash = tracked["content_hash"] if tracked else None

            if max_bytes is not None and st.st_size > max_bytes:
                if tracked and tracked.get("is_indexed"):
                    changes.append(FileChange(rel, FileChangeType.MODIFIED, old_hash=old_hash))
                continue

            if tracked is None:
                new_hash = compute_file_hash_cached(str(abs_path), st.st_mtime)
                changes.append(FileChange(rel, FileChangeType.ADDED, new_hash=new_hash))
                continue

            if not strict_hashing:
                tracked_mtime_ns = tracked.get("mtime_ns")
                tracked_ino = tracked.get("inode")
                tracked_size = tracked.get("size")
                st_mtime_ns = getattr(st, "st_mtime_ns", None)
                st_ino = getattr(st, "st_ino", None)

                if (
                    tracked_mtime_ns is not None
                    and tracked_ino is not None
                    and tracked_size is not None
                    and st_mtime_ns is not None
                    and st_ino is not None
                    and st_mtime_ns == tracked_mtime_ns
                    and st_ino == tracked_ino
                    and st.st_size == tracked_size
                ):
                    continue

            try:
                new_hash = compute_file_hash_cached(str(abs_path), st.st_mtime)
            except OSError:
                continue

            if old_hash != new_hash:
                changes.append(FileChange(rel, FileChangeType.MODIFIED, old_hash=old_hash, new_hash=new_hash))

        for rel, tracked in known_tracking.items():
            if rel not in current_files:
                changes.append(FileChange(rel, FileChangeType.DELETED, old_hash=tracked["content_hash"]))

        return changes

    def update_state(self, fingerprints: list[dict[str, Any]]) -> None:
        if fingerprints:
            self.db.upsert_file_tracking(fingerprints)
            LOGGER.debug("Updated %d file tracking records.", len(fingerprints))

    def handle_deleted_files(self, deleted_files: set[str]) -> None:
        if not deleted_files:
            return
        deleted_count = self.db.delete_file_tracking_batch(list(deleted_files))
        LOGGER.debug("Removed %d tracking records for %d deleted files.", deleted_count, len(deleted_files))
