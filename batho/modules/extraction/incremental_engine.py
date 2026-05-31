from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any
from dataclasses import dataclass

from batho.modules.storage.sqlite_registry.engine import BathoDatabase
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
    """
    Incremental extraction engine.
    Tracks file changes using BathoDatabase's file_tracking table and only re-extracts delta.
    """

    def __init__(self, db: BathoDatabase, run_uuid: str):
        self.db = db
        self.run_uuid = run_uuid

    def scan_changes(
        self,
        root: Path,
        max_file_size_kb: int | None = None,
        strict_hashing: bool = True,
    ) -> list[FileChange]:
        """Scan filesystem for added/modified/deleted files against file_tracking table."""
        from batho.modules.graph.incremental import _collect_candidate_files

        known_tracking = self.db.get_all_file_tracking()
        max_bytes = (max_file_size_kb * 1024) if max_file_size_kb else None
        changes: list[FileChange] = []
        current_files: set[str] = set()

        for abs_path in _collect_candidate_files(root):
            try:
                rel = str(abs_path.relative_to(root))
            except ValueError:
                continue
            current_files.add(rel)

            try:
                st = abs_path.stat()
            except OSError:
                continue

            if max_bytes is not None and st.st_size > max_bytes:
                continue

            tracked = known_tracking.get(rel)
            if tracked is None:
                new_hash = compute_file_hash_cached(str(abs_path), st.st_mtime)
                changes.append(FileChange(rel, FileChangeType.ADDED, new_hash=new_hash))
                continue

            old_hash = tracked["content_hash"]

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

    def update_state(self, fingerprints: List[dict[str, Any]]) -> None:
        """Update incremental state after extraction."""
        if fingerprints:
            self.db.upsert_file_tracking(fingerprints)
            LOGGER.debug(f"Updated {len(fingerprints)} file tracking records.")
            
    def handle_deleted_files(self, deleted_files: Set[str]) -> None:
        """Remove tracking records for deleted files."""
        for file_path in deleted_files:
            self.db.delete_file_tracking(file_path)
        if deleted_files:
            LOGGER.debug(f"Removed {len(deleted_files)} tracking records for deleted files.")

