"""Time Machine utilities for Batho core (DB-backed snapshots and diffs).

- Snapshots are stored in the unified `artifact_<dirname>.batho` SQLite database (snapshots table).
- snapshot_id format: `batho_<uuid>_<timestamp>` (UTC).
- Diff reports entity/relationship deltas and changed files.
- PR patching stub provided for future incremental updates.
- FileChangeTracker for incremental patching via content-based diffing.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from batho.config import SNAPSHOT_SCHEMA_VERSION, get_config_cached
from batho.context.bsg_map import BSGMap
from batho.context.unified_cache import BathoCache
from batho.context.codegraph import IncrementalGraphUpdater, InMemoryGraph
from batho.context.incremental import get_head_commit, is_git_repo
from batho.context.storage import register_artifact
from batho.utils.file_io import _is_binary
from batho.utils.hash import compute_bytes_hash, compute_file_hash
from batho.utils.ignore import is_ignored, load_ignore_spec, walk_ignored_filtered
from batho.utils.logging import get_logger
from batho.utils.patch_errors import (
    PatchConsistencyError,
    PatchFileError,
    PatchSnapshotError,
    PatchTimeoutError,
    PatchValidationError,
    audit_logger,
)

logger = get_logger(__name__, component="time_machine")


def _get_serialization_config() -> dict[str, Any]:
    """Get BSG serialization config from cached config."""
    return get_config_cached().get("bsg", {}).get("serialization", {})


@contextmanager
def timeout_context(timeout_seconds: float):
    """Context manager to enforce operation timeouts."""

    def timeout_handler(signum, frame):
        raise PatchTimeoutError(
            f"Operation timed out after {timeout_seconds} seconds", timeout_seconds
        )

    # Windows doesn't support SIGALRM, use threading.Timer as fallback
    if sys.platform == "win32" or not hasattr(signal, "SIGALRM"):
        import threading

        timer = None
        try:
            timer = threading.Timer(
                timeout_seconds,
                lambda: (_ for _ in ()).throw(
                    PatchTimeoutError(
                        f"Operation timed out after {timeout_seconds} seconds",
                        timeout_seconds,
                    )
                ),
            )
            timer.start()
            yield
        finally:
            if timer:
                timer.cancel()
    else:
        old_handler = signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(int(timeout_seconds))
        try:
            yield
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)


def check_patch_limits(changes: list[FileChange], max_changes: int) -> None:
    """Validate patch size limits."""
    if len(changes) > max_changes:
        raise PatchValidationError(
            f"Too many changes in patch: {len(changes)} > {max_changes}",
            details={"changes_count": len(changes), "max_allowed": max_changes},
        )


def log_change_summary(changes: list[FileChange]) -> None:
    """Log summarized change statistics without spam."""
    added = sum(1 for c in changes if c.change_type == FileChangeType.ADDED)
    modified = sum(1 for c in changes if c.change_type == FileChangeType.MODIFIED)
    deleted = sum(1 for c in changes if c.change_type == FileChangeType.DELETED)

    logger.info(
        "patch_change_summary",
        total_changes=len(changes),
        added_files=added,
        modified_files=modified,
        deleted_files=deleted,
    )


class FileChangeType(Enum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class FileChange:
    path: str
    change_type: FileChangeType
    old_hash: str | None
    new_hash: str | None
    file_size: int | None = None
    mtime: datetime | None = None
    permissions: int | None = None
    is_symlink: bool = False
    symlink_target: str | None = None


@dataclass
class FileChangeSummary:
    total_changes: int
    added: int
    modified: int
    deleted: int
    unchanged: int
    affected_files: list[str]


@dataclass
class FileTrackingConfig:
    """Configuration for file change tracking operations."""

    max_file_size_kb: int = 500
    warn_binary_files: bool = True
    binary_size_threshold_kb: int = 1024
    log_permission_errors: bool = True


@dataclass
class PatchOperation:
    operation_id: str
    base_snapshot_id: str | None
    new_snapshot_id: str | None  # NEW: The snapshot created by this patch
    changes_applied: list[FileChange]
    timestamp: datetime
    checksum: str
    patch_chain: list[str]  # NEW: Chain of parent patches
    operation_type: str  # NEW: "incremental_patch", "diff_patch", "cherry_pick"
    user_info: dict[str, Any]  # NEW: Source: CLI, AI agent
    metrics: dict[str, Any]  # NEW: Token size, affected components, timing

    def validate(self) -> bool:
        data = {k: v for k, v in self.serialize().items() if k != "checksum"}
        computed = compute_bytes_hash(json.dumps(data, sort_keys=True).encode("utf-8"))
        return computed == self.checksum

    def serialize(self) -> dict[str, Any]:
        def change_to_dict(change: FileChange) -> dict[str, Any]:
            d = asdict(change)
            if d.get("change_type"):
                d["change_type"] = (
                    change.change_type.value
                )  # Convert enum to string value
            if d.get("mtime"):
                d["mtime"] = d["mtime"].isoformat()
            return d

        return {
            "operation_id": self.operation_id,
            "base_snapshot_id": self.base_snapshot_id,
            "new_snapshot_id": self.new_snapshot_id,
            "changes_applied": [
                change_to_dict(change) for change in self.changes_applied
            ],
            "timestamp": self.timestamp.isoformat(),
            "checksum": self.checksum,
            "patch_chain": self.patch_chain,
            "operation_type": self.operation_type,
            "user_info": self.user_info,
            "metrics": self.metrics,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PatchOperation":
        """Deserialize PatchOperation from dictionary."""

        def dict_to_change(d: dict[str, Any]) -> FileChange:
            if d.get("change_type"):
                d["change_type"] = FileChangeType(d["change_type"])
            if d.get("mtime"):
                d["mtime"] = datetime.fromisoformat(d["mtime"])
            return FileChange(**d)

        changes_applied = [
            dict_to_change(change) for change in data.get("changes_applied", [])
        ]

        return cls(
            operation_id=data["operation_id"],
            base_snapshot_id=data["base_snapshot_id"],
            new_snapshot_id=data.get("new_snapshot_id"),
            changes_applied=changes_applied,
            timestamp=datetime.fromisoformat(data["timestamp"]),
            checksum=data["checksum"],
            patch_chain=data.get("patch_chain", []),
            operation_type=data.get("operation_type", "incremental_patch"),
            user_info=data.get("user_info", {}),
            metrics=data.get("metrics", {}),
        )


class FileChangeTracker:
    """Tracks file changes via content-based hash comparison for incremental reindexing."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.file_hashes: dict[str, str] = {}
        self._cache: BathoCache | None = None

    def _get_cache(self) -> BathoCache:
        if self._cache is None or getattr(self._cache._db, "_closed", False):
            self._cache = BathoCache(str(self.root))
        return self._cache

    def load(self, cache_path: Path | None = None) -> bool:
        """Load file hashes from SQLite cache. Returns True if loaded successfully."""
        try:
            cache = self._get_cache()
            self.file_hashes = cache.load_all()
            logger.info("file_tracker_loaded", file_count=len(self.file_hashes), source="sqlite")
            return True
        except Exception as e:
            logger.warning("file_tracker_load_failed", error=str(e))
            self.file_hashes = {}
            return False

    def save(self, cache_path: Path | None = None) -> None:
        """Save file hashes to SQLite cache."""
        try:
            cache = self._get_cache()
            cache.save_all(self.file_hashes, self.root)
            logger.debug("file_tracker_saved", file_count=len(self.file_hashes), target="sqlite")
        except Exception as e:
            logger.warning("file_tracker_save_failed", error=str(e))

    def scan_for_changes(
        self,
        max_file_size_kb: int = 500,
        base_snapshot: dict | None = None,
        config: FileTrackingConfig | None = None,
        track_new_files: bool = True,
    ) -> list[FileChange]:
        """
        Scan repository and compute file changes vs stored hashes or provided snapshot.

        Args:
            max_file_size_kb: Skip files larger than this.
            base_snapshot: Optional base snapshot to compare against.
            config: Optional tracking configuration.
            track_new_files: If False, don't report new files as changes. This is useful
                for incremental patching where we only want to track changes to previously
                indexed files, not discover new files.
        """
        changes: list[FileChange] = []

        # Use provided config or create default with backward compatible max_file_size_kb
        tracking_config = config or FileTrackingConfig(
            max_file_size_kb=max_file_size_kb
        )

        ignore_spec = load_ignore_spec(self.root)
        logger.debug(
            "scan_ignore_spec_loaded",
            root=str(self.root),
            patterns_count=len(ignore_spec.patterns) if hasattr(ignore_spec, 'patterns') else 'unknown',
        )
        stored_hashes = (
            base_snapshot.get("file_hashes", {}) if base_snapshot else self.file_hashes
        )

        current_files: dict[str, str] = {}
        stored_paths = set(stored_hashes.keys())

        for dirpath, dirnames, filenames in walk_ignored_filtered(self.root, spec=ignore_spec):
            for filename in filenames:
                file_path = dirpath / filename
                # Handle symlinks separately
                is_symlink = file_path.is_symlink()
                if (
                    not (
                        os.path.isfile(str(file_path))
                        and not os.path.islink(str(file_path))
                    )
                    and not is_symlink
                ):
                    continue

                # Get relative path early for logging
                try:
                    rel_path = str(file_path.relative_to(self.root))
                except ValueError:
                    continue

                # Note: is_ignored check not needed since walk_ignored_filtered already filters

                try:
                    # Use lstat for symlinks to get symlink info, stat for regular files
                    stat_info = file_path.lstat() if is_symlink else file_path.stat()
                    if stat_info.st_size > tracking_config.max_file_size_kb * 1024:
                        logger.debug(
                            "file_too_large",
                            path=rel_path,
                            size_kb=stat_info.st_size / 1024,
                        )
                        continue
                except OSError as e:
                    if tracking_config.log_permission_errors:
                        logger.warning(
                            "file_access_error",
                            path=rel_path,
                            error=str(e),
                            error_type=type(e).__name__,
                        )
                    continue

                # For symlinks, use target path as hash
                symlink_target_path = None
                if is_symlink:
                    try:
                        symlink_target_path = file_path.resolve()
                        relative_target = str(symlink_target_path.relative_to(self.root))
                        file_hash = f"symlink:{relative_target}"
                    except (OSError, ValueError) as e:
                        if tracking_config.log_permission_errors:
                            logger.warning(
                                "symlink_resolve_error",
                                path=rel_path,
                                error=str(e),
                                error_type=type(e).__name__,
                            )
                        file_hash = f"symlink:broken"
                else:
                    file_hash = compute_file_hash(file_path)
                    # Log warning for large binary files
                    if file_hash and tracking_config.warn_binary_files and "_" in file_hash:
                        try:
                            size_str = file_hash.split("_")[0]
                            if size_str.isdigit():
                                size_kb = int(size_str) / 1024
                                if size_kb > tracking_config.binary_size_threshold_kb:
                                    logger.warning(
                                        "large_binary_file_detected",
                                        path=rel_path,
                                        size_kb=round(size_kb, 1),
                                        threshold_kb=tracking_config.binary_size_threshold_kb,
                                    )
                        except (ValueError, IndexError):
                            pass  # Not a size_mtime format, ignore

                if file_hash:
                    current_files[rel_path] = file_hash

        # When using base_snapshot and not tracking new files, filter to only
        # include previously indexed files. This prevents new files from being
        # reported as "added" changes during incremental patching.
        if base_snapshot is not None and not track_new_files:
            current_files = {
                p: h for p, h in current_files.items() if p in stored_paths
            }

        current_paths = set(current_files.keys())
        deleted_paths = stored_paths - current_paths
        added_paths = current_paths - stored_paths
        potentially_modified = current_paths & stored_paths

        for path in deleted_paths:
            changes.append(
                FileChange(
                    path=path,
                    change_type=FileChangeType.DELETED,
                    old_hash=stored_hashes.get(path),
                    new_hash=None,
                )
            )

        for path in added_paths:
            file_path = self.root / path
            try:
                is_symlink = file_path.is_symlink()
                stat = file_path.lstat() if is_symlink else file_path.stat()
                file_size = stat.st_size
                mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
                permissions = stat.st_mode
                symlink_target = None
                if is_symlink:
                    hash_parts = current_files[path].split(":", 1)
                    if len(hash_parts) == 2 and hash_parts[0] == "symlink":
                        symlink_target = (
                            hash_parts[1] if hash_parts[1] != "broken" else None
                        )
            except OSError:
                file_size = mtime = permissions = symlink_target = None
                is_symlink = False
            changes.append(
                FileChange(
                    path=path,
                    change_type=FileChangeType.ADDED,
                    old_hash=None,
                    new_hash=current_files[path],
                    file_size=file_size,
                    mtime=mtime,
                    permissions=permissions,
                    is_symlink=is_symlink,
                    symlink_target=symlink_target,
                )
            )

        for path in sorted(potentially_modified):
            old_hash = stored_hashes.get(path)
            new_hash = current_files.get(path)
            if old_hash != new_hash:
                file_path = self.root / path
                try:
                    is_symlink = file_path.is_symlink()
                    stat = file_path.lstat() if is_symlink else file_path.stat()
                    file_size = stat.st_size
                    mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
                    permissions = stat.st_mode
                    symlink_target = None
                    if is_symlink:
                        hash_parts = current_files[path].split(":", 1)
                        if len(hash_parts) == 2 and hash_parts[0] == "symlink":
                            symlink_target = (
                                hash_parts[1] if hash_parts[1] != "broken" else None
                            )
                except OSError:
                    file_size = mtime = permissions = symlink_target = None
                    is_symlink = False
                changes.append(
                    FileChange(
                        path=path,
                        change_type=FileChangeType.MODIFIED,
                        old_hash=old_hash,
                        new_hash=new_hash,
                        file_size=file_size,
                        mtime=mtime,
                        permissions=permissions,
                        is_symlink=is_symlink,
                        symlink_target=symlink_target,
                    )
                )

        self.file_hashes = current_files
        logger.info(
            "scan_complete",
            changes=len(changes),
            added=len(added_paths),
            modified=len(
                [c for c in changes if c.change_type == FileChangeType.MODIFIED]
            ),
            deleted=len(deleted_paths),
        )
        return changes

    def get_changed_files(self, changes: list[FileChange]) -> list[Path]:
        """Return list of paths for ADDED and MODIFIED files."""
        result = []
        for change in changes:
            if change.change_type in (FileChangeType.ADDED, FileChangeType.MODIFIED):
                result.append(self.root / change.path)
        return result

    def get_deleted_files(self, changes: list[FileChange]) -> list[str]:
        """Return list of file paths for DELETED files."""
        return [
            change.path
            for change in changes
            if change.change_type == FileChangeType.DELETED
        ]


def _get_db(ctn_dir: Path):
    """Get the BathoDatabase for the given root or legacy ctn_dir."""
    from batho.context.storage import get_artifact_registry
    return get_artifact_registry(ctn_dir)


def _sanitize_project_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "project"


def _git_branch_name(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None

    branch = result.stdout.strip()
    return branch or None


def generate_snapshot_id(root: Path | None = None) -> str:
    """
    Generate snapshot IDs.

    - Legacy/default mode (root is None): batho_<uuid>_<timestamp>
    - Repo-aware mode (root provided): batho_<project>_<sha32|nogit>_<timestamp>
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    if root is None:
        return f"batho_{uuid.uuid4().hex}_{ts}"

    repo_root = root.resolve()
    project = _sanitize_project_slug(repo_root.name)
    commit = get_head_commit(repo_root) if is_git_repo(repo_root) else None
    commit_fragment = commit[:32].lower() if commit else "nogit"
    return f"batho_{project}_{commit_fragment}_{ts}"


def create_snapshot(
    ctn_dir: Path,
    root: Path,
    graph: InMemoryGraph,
    bsg_map: BSGMap,
    label: str | None = None,
) -> str:
    """Persist a snapshot to the artifact database."""
    repo_root = root.resolve()
    snapshot_id = generate_snapshot_id(repo_root)

    git_repo = is_git_repo(repo_root)
    head_commit = get_head_commit(repo_root) if git_repo else None
    git_branch = _git_branch_name(repo_root) if git_repo else None

    file_hashes: dict[str, str] = {}
    for entity in graph.entities.values():
        entity_file = entity.file
        if entity_file:
            try:
                rel_path = Path(entity_file).relative_to(repo_root)
                file_path = str(rel_path)
            except ValueError:
                file_path = entity_file
            if file_path and file_path not in file_hashes:
                full_path = repo_root / file_path
                if full_path.exists():
                    try:
                        file_hashes[file_path] = compute_bytes_hash(full_path.read_bytes())
                    except OSError:
                        pass

    stats = {
        "entity_count": len(graph.entities),
        "relationship_count": len(graph.relationships),
        "file_count": len(bsg_map._by_file),
        "file_hashes": file_hashes,
        "graph": graph.to_dict(),
        "bsg": bsg_map.render_json(
            default_index_id=snapshot_id,
            default_service_tag=repo_root.name,
        ),
    }

    checksum = compute_bytes_hash(
        json.dumps(stats, sort_keys=True, ensure_ascii=True).encode("utf-8")
    )

    db = _get_db(ctn_dir)
    db.create_snapshot({
        "snapshot_id": snapshot_id,
        "parent_id": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "label": label or "",
        "git_commit": head_commit,
        "git_branch": git_branch,
        "root_path": str(repo_root),
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "stats": stats,
        "checksum": checksum,
    })

    logger.info("snapshot_created", snapshot_id=snapshot_id)
    return snapshot_id


def list_snapshots(ctn_dir: Path) -> list[dict[str, Any]]:
    """List all snapshots from the artifact database."""
    db = _get_db(ctn_dir)
    rows = db.list_snapshots()
    return [
        {
            "snapshot_id": row.get("snapshot_id", ""),
            "created_at": row.get("created_at"),
            "label": row.get("label", ""),
            "git_commit": row.get("git_commit"),
            "git_branch": row.get("git_branch"),
        }
        for row in rows
    ]


def load_snapshot(ctn_dir: Path, snapshot_id: str) -> dict[str, Any] | None:
    """Load a snapshot from the artifact database."""
    db = _get_db(ctn_dir)
    row = db.get_snapshot(snapshot_id)
    if row is None:
        return None

    # Reconstruct the legacy payload format from stored data
    stats_json = row.get("stats_json", "{}")
    stats = json.loads(stats_json) if isinstance(stats_json, str) else stats_json

    data: dict[str, Any] = {
        "schema_version": row.get("schema_version", SNAPSHOT_SCHEMA_VERSION),
        "snapshot_id": row["snapshot_id"],
        "created_at": row.get("created_at"),
        "root": row.get("root_path", ""),
        "label": row.get("label", ""),
        "git_metadata": {
            "is_git_repo": bool(row.get("git_commit")),
            "commit_sha": row.get("git_commit"),
            "branch": row.get("git_branch"),
        },
        "_checksum": row.get("checksum", ""),
        "stats": {
            "entity_count": stats.get("entity_count", 0),
            "relationship_count": stats.get("relationship_count", 0),
            "file_count": stats.get("file_count", 0),
        },
        "file_hashes": stats.get("file_hashes", {}),
        "graph": stats.get("graph", {}),
        "bsg": stats.get("bsg", {}),
    }
    return data


def diff_snapshots(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    stats_a = a.get("stats", {})
    stats_b = b.get("stats", {})
    entity_delta = stats_b.get("entity_count", 0) - stats_a.get("entity_count", 0)
    relationship_delta = stats_b.get("relationship_count", 0) - stats_a.get(
        "relationship_count", 0
    )
    bsg_a = a.get("bsg", {}) if isinstance(a.get("bsg"), dict) else {}
    bsg_b = b.get("bsg", {}) if isinstance(b.get("bsg"), dict) else {}

    files_a = set((bsg_a.get("indexes", {}) or {}).get("nodes_by_file", {}).keys())
    files_b = set((bsg_b.get("indexes", {}) or {}).get("nodes_by_file", {}).keys())

    # Fallback for malformed payloads without indexes
    if not files_a and isinstance(bsg_a.get("nodes"), list):
        files_a = {
            str(node.get("file", ""))
            for node in bsg_a.get("nodes", [])
            if isinstance(node, dict) and node.get("file")
        }
    if not files_b and isinstance(bsg_b.get("nodes"), list):
        files_b = {
            str(node.get("file", ""))
            for node in bsg_b.get("nodes", [])
            if isinstance(node, dict) and node.get("file")
        }

    added_files = sorted(path for path in files_b if path not in files_a)
    removed_files = sorted(path for path in files_a if path not in files_b)
    return {
        "entity_delta": entity_delta,
        "relationship_delta": relationship_delta,
        "added_files": added_files,
        "removed_files": removed_files,
    }


def compare_file_lists(
    current_files: dict[str, str], snapshot_files: dict[str, str]
) -> list[FileChange]:
    """Compare two file lists and return FileChange objects."""
    changes = []
    for path in current_files:
        if path not in snapshot_files:
            changes.append(
                FileChange(
                    path=path,
                    change_type=FileChangeType.ADDED,
                    old_hash=None,
                    new_hash=current_files[path],
                )
            )
        elif snapshot_files[path] != current_files[path]:
            changes.append(
                FileChange(
                    path=path,
                    change_type=FileChangeType.MODIFIED,
                    old_hash=snapshot_files[path],
                    new_hash=current_files[path],
                )
            )
    for path in snapshot_files:
        if path not in current_files:
            changes.append(
                FileChange(
                    path=path,
                    change_type=FileChangeType.DELETED,
                    old_hash=snapshot_files[path],
                    new_hash=None,
                )
            )
    return changes


def aggregate_changes(changes: list[FileChange]) -> list[FileChange]:
    """Batch related changes and prioritize: deletions first, then modifications, additions."""
    order = {
        FileChangeType.DELETED: 0,
        FileChangeType.MODIFIED: 1,
        FileChangeType.ADDED: 2,
    }
    return sorted(changes, key=lambda c: (order[c.change_type], c.path))


def parse_git_diff(diff_output: str) -> list[FileChange]:
    """Parse git diff --name-status output and convert to FileChange list."""
    changes = []
    for line in diff_output.strip().split("\n"):
        if not line:
            continue
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        status, path = parts
        if status == "A":
            change_type = FileChangeType.ADDED
        elif status == "M":
            change_type = FileChangeType.MODIFIED
        elif status == "D":
            change_type = FileChangeType.DELETED
        else:
            continue
        changes.append(
            FileChange(path=path, change_type=change_type, old_hash=None, new_hash=None)
        )
    return changes


def compute_staleness(
    prev_entry: dict[str, Any] | None,
    current_repo_hash: str,
    stats: dict[str, Any] | None = None,
) -> float:
    """
    Compute staleness using repo hash equality + change ratio + age + error rate.

    Returns float in [0,1], where 1 is fully stale.
    """

    if not prev_entry:
        return 1.0

    prev_repo_hash = (
        prev_entry.get("repo_hash") if isinstance(prev_entry, dict) else None
    )
    if prev_repo_hash and prev_repo_hash == current_repo_hash:
        base = 0.1
    else:
        base = 0.6

    prev_file_count = (
        max(1, int(prev_entry.get("file_count", 1)))
        if isinstance(prev_entry, dict)
        else 1
    )
    parsed = int(stats.get("files_parsed", 0)) if stats else 0
    change_ratio = min(1.0, parsed / prev_file_count) if prev_file_count else 0.0

    errors = int(stats.get("errors", 0)) if stats else 0
    error_factor = min(1.0, errors / max(parsed, 1)) if parsed else 0.0

    age_factor = 0.0
    try:
        prev_ts_str = prev_entry.get("timestamp") if prev_entry else None
        prev_ts = datetime.fromisoformat(prev_ts_str) if prev_ts_str else None
        if prev_ts:
            age_hours = (datetime.now(timezone.utc) - prev_ts).total_seconds() / 3600
            age_factor = min(1.0, age_hours / 24)  # age out over a day
    except Exception:
        age_factor = 0.0

    score = min(1.0, base + 0.3 * change_ratio + 0.2 * error_factor + 0.1 * age_factor)
    return round(score, 3)


def incremental_patch(
    ctn_dir: Path,
    base_snapshot_id: str,
    changes: list[FileChange],
) -> dict[str, Any]:
    """
    Apply incremental updates to a base snapshot with enhanced error handling, logging, and limits.

    Loads the base snapshot, applies changes using IncrementalGraphUpdater,
    updates bsg, and creates a new snapshot. Includes rollback mechanism
    on failure, timeout handling, size limits, and detailed progress logging.

    Args:
        ctn_dir: Path to .ctn directory containing snapshots
        base_snapshot_id: ID of the base snapshot to patch
        changes: List of file changes to apply

    Returns:
        Dict with operation results including new snapshot ID or error details
    """
    config = get_config_cached()
    patch_config = config.get("patch", {})
    timeout_seconds = patch_config.get("timeout_seconds", 300)
    max_changes = patch_config.get("max_changes", 10000)

    # Validate inputs
    try:
        check_patch_limits(changes, max_changes)
    except PatchValidationError as exc:
        logger.error("patch_validation_failed", error=str(exc), details=exc.details)
        return {
            "success": False,
            "error": str(exc),
            "operation_id": generate_snapshot_id(),
        }

    # Log change summary
    log_change_summary(changes)

    start_time = time.perf_counter()

    # Start audit logging
    audit_entry = audit_logger.start_operation(
        operation_id=generate_snapshot_id(),
        operation_type="incremental_patch",
        base_snapshot_id=base_snapshot_id,
        metadata={"expected_changes": len(changes)},
    )

    try:
        # Enforce timeout
        with timeout_context(timeout_seconds):
            logger.info(
                "patch_operation_start",
                base_snapshot_id=base_snapshot_id,
                change_count=len(changes),
            )

            # Load base snapshot
            base_snapshot = load_snapshot(ctn_dir, base_snapshot_id)
            if base_snapshot is None:
                raise PatchSnapshotError(
                    f"Base snapshot {base_snapshot_id} not found", base_snapshot_id
                )

            # Reconstruct base graph and bsg map
            base_graph = InMemoryGraph.from_dict(base_snapshot["graph"])
            base_bsg = BSGMap.from_dict(
                base_snapshot["bsg"], serialization_config=_get_serialization_config()
            )
            base_bsg._root = base_snapshot["root"]  # Set the root path

            # Initialize updater
            updater = IncrementalGraphUpdater()

            # Get root path
            root_path = Path(base_snapshot["root"])

            # Create file change tracker for validation
            tracker = FileChangeTracker(root_path)
            tracker.load()
            cache = tracker._get_cache()

            # Apply changes in order: deletions first, then modifications, then additions
            ordered_changes = aggregate_changes(changes)

            applied_changes = []
            rollback_actions = []

            batch_size = max(
                100, len(ordered_changes) // 10
            )  # Progress logging batches

            for i, change in enumerate(ordered_changes):
                try:
                    abs_path = root_path / change.path

                    if change.change_type == FileChangeType.DELETED:
                        updater.remove_entities_for_file(base_graph, str(abs_path))
                        cache.delete_file_snapshot(str(abs_path))
                        rollback_actions.append(("add_file", change.path))

                    elif change.change_type == FileChangeType.MODIFIED:
                        # For modified files, we need an extractor
                        from batho.context.languages.detector import default_detector
                        from batho.context.languages.registry import get_extractor

                        extractor = default_detector.get_extractor(
                            abs_path, b""
                        ) or get_extractor(abs_path.suffix.lower())
                        if extractor:
                            updater.update_entities_for_file(
                                base_graph, str(abs_path), extractor
                            )
                            rollback_actions.append(
                                ("restore_file", change.path, change.old_hash)
                            )
                        else:
                            logger.warning(
                                "no_extractor_for_modified_file", path=change.path
                            )
                            try:
                                stat_info = abs_path.stat()
                                size = stat_info.st_size
                                content = abs_path.read_bytes()
                                from batho.context.schema import FileSnapshot
                                # Retrieve old snapshot for rollback
                                old_snap = cache.get_file_snapshot(str(abs_path))
                                _snap = FileSnapshot.create_opaque(
                                    file_path=str(abs_path),
                                    content=content,
                                    file_size=size,
                                )
                                cache.set_file_snapshot(_snap)
                                rollback_actions.append(
                                    ("restore_opaque_file", change.path, old_snap)
                                )
                            except (OSError, IOError) as e:
                                logger.warning(
                                    "opaque_file_read_failed",
                                    path=change.path,
                                    error=str(e),
                                )

                    elif change.change_type == FileChangeType.ADDED:
                        # For new files, we need an extractor
                        from batho.context.languages.detector import default_detector
                        from batho.context.languages.registry import get_extractor

                        extractor = default_detector.get_extractor(
                            abs_path, b""
                        ) or get_extractor(abs_path.suffix.lower())
                        if extractor:
                            updater.add_entities_for_file(
                                base_graph, str(abs_path), extractor
                            )
                            rollback_actions.append(("delete_file", change.path))
                        else:
                            try:
                                stat_info = abs_path.stat()
                                size = stat_info.st_size
                                content = abs_path.read_bytes()
                                from batho.context.schema import FileSnapshot
                                _snap = FileSnapshot.create_opaque(
                                    file_path=str(abs_path),
                                    content=content,
                                    file_size=size,
                                )
                                cache.set_file_snapshot(_snap)
                                rollback_actions.append(
                                    ("delete_opaque_file", change.path)
                                )
                            except (OSError, IOError) as e:
                                logger.warning(
                                    "opaque_file_read_failed",
                                    path=change.path,
                                    error=str(e),
                                )

                    applied_changes.append(change)

                    # Progress logging - avoid spam with batching
                    if (i + 1) % batch_size == 0 or i == len(ordered_changes) - 1:
                        elapsed = time.perf_counter() - start_time
                        progress = (i + 1) / len(ordered_changes)
                        logger.info(
                            "patch_progress",
                            processed=i + 1,
                            total=len(ordered_changes),
                            progress_pct=round(progress * 100, 2),
                            elapsed_seconds=round(elapsed, 2),
                        )

                except Exception as exc:
                    logger.error(
                        "change_application_failed", change=change.path, error=str(exc)
                    )
                    # Attempt rollback
                    _rollback_changes(
                        base_graph,
                        applied_changes,
                        rollback_actions,
                        updater,
                        root_path,
                        cache=cache,
                    )
                    raise PatchFileError(
                        f"Failed to apply change to {change.path}: {str(exc)}",
                        file_path=change.path,
                        operation=change.change_type.value,
                    ) from exc


            # Resolve imports and apply semantic overlay (same as build_graph)
            from batho.context.symbol_index import SymbolIndex
            from batho.context.codegraph import CodeGraphIndexer

            symbol_index = SymbolIndex.build(base_graph)
            with CodeGraphIndexer(cache_path=str(root_path), root=str(root_path)) as indexer:
                base_graph, _, _ = indexer._resolve_imports(base_graph, symbol_index=symbol_index)
            from batho.bsg import apply_semantic_overlay

            apply_semantic_overlay(graph=base_graph, root_path=root_path, logger=logger)

            # Validate graph consistency
            # Note: Some inconsistencies may exist in base snapshot or from unresolved imports
            # We log warnings but continue to allow incremental patching to succeed
            is_valid = updater.validate_graph_consistency(base_graph)
            if not is_valid:
                logger.warning(
                    "graph_inconsistency_after_patch",
                    base_snapshot_id=base_snapshot_id,
                    change_count=len(applied_changes),
                    note="continuing despite inconsistencies; may indicate unresolved imports or pre-existing issues",
                )

            # Update bsg map
            base_bsg.patch(changes, base_graph, cache=tracker._get_cache())

            # Create new snapshot
            new_snapshot_id = create_snapshot(
                ctn_dir,
                root_path,
                base_graph,
                base_bsg,
                label=f"Incremental patch of {base_snapshot_id}",
            )

            # Update file tracker
            for change in applied_changes:
                if change.change_type == FileChangeType.DELETED:
                    tracker.file_hashes.pop(change.path, None)
                else:
                    tracker.file_hashes[change.path] = change.new_hash or ""

            tracker.save()

            # Create patch operation record
            operation_id = generate_snapshot_id()
            patch_chain = build_patch_chain(ctn_dir, base_snapshot_id, operation_id)
            elapsed = time.perf_counter() - start_time

            operation = PatchOperation(
                operation_id=operation_id,
                base_snapshot_id=base_snapshot_id,
                new_snapshot_id=new_snapshot_id,
                changes_applied=applied_changes,
                timestamp=datetime.now(timezone.utc),
                checksum="",  # Will be computed below
                patch_chain=patch_chain,
                operation_type="incremental_patch",
                user_info={"source": "cli", "command": "patch"},
                metrics={
                    "token_size": estimate_token_changes(applied_changes),
                    "affected_files": len(applied_changes),
                    "elapsed_seconds": round(elapsed, 4),
                    "added_files": sum(
                        1
                        for c in applied_changes
                        if c.change_type == FileChangeType.ADDED
                    ),
                    "modified_files": sum(
                        1
                        for c in applied_changes
                        if c.change_type == FileChangeType.MODIFIED
                    ),
                    "deleted_files": sum(
                        1
                        for c in applied_changes
                        if c.change_type == FileChangeType.DELETED
                    ),
                },
            )
            # Compute checksum
            data = {k: v for k, v in operation.serialize().items() if k != "checksum"}
            operation.checksum = compute_bytes_hash(
                json.dumps(data, sort_keys=True).encode("utf-8")
            )

            # Save patch operation
            save_patch_operation(ctn_dir, operation)

            logger.info(
                "incremental_patch_complete",
                base_snapshot_id=base_snapshot_id,
                new_snapshot_id=new_snapshot_id,
                applied_changes=len(applied_changes),
                elapsed_seconds=round(elapsed, 4),
            )

            # Complete audit
            audit_logger.complete_operation(
                operation_id=audit_entry.operation_id,
                success=True,
                new_snapshot_id=new_snapshot_id,
                change_count=len(applied_changes),
                metadata={"elapsed_seconds": round(elapsed, 4)},
            )

            return {
                "success": True,
                "new_snapshot_id": new_snapshot_id,
                "operation_id": operation.operation_id,
                "applied_changes": len(applied_changes),
                "base_snapshot_id": base_snapshot_id,
                "elapsed_seconds": round(elapsed, 4),
            }

    except PatchTimeoutError as exc:
        logger.error("patch_timeout", error=str(exc), timeout_seconds=timeout_seconds)
        audit_logger.complete_operation(
            operation_id=audit_entry.operation_id,
            success=False,
            error_message=str(exc),
            metadata={"timeout_seconds": timeout_seconds},
        )
        return {
            "success": False,
            "error": str(exc),
            "operation_id": audit_entry.operation_id,
        }
    except PatchValidationError as exc:
        logger.error("patch_validation_error", error=str(exc), details=exc.details)
        audit_logger.complete_operation(
            operation_id=audit_entry.operation_id,
            success=False,
            error_message=str(exc),
            metadata=exc.details,
        )
        return {
            "success": False,
            "error": str(exc),
            "operation_id": audit_entry.operation_id,
        }
    except PatchConsistencyError as exc:
        logger.error("patch_consistency_error", error=str(exc))
        audit_logger.complete_operation(
            operation_id=audit_entry.operation_id,
            success=False,
            error_message=str(exc),
        )
        return {
            "success": False,
            "error": str(exc),
            "operation_id": audit_entry.operation_id,
        }
    except PatchSnapshotError as exc:
        logger.error(
            "patch_snapshot_error", error=str(exc), snapshot_id=exc.snapshot_id
        )
        audit_logger.complete_operation(
            operation_id=audit_entry.operation_id,
            success=False,
            error_message=str(exc),
        )
        return {
            "success": False,
            "error": str(exc),
            "operation_id": audit_entry.operation_id,
        }
    except PatchFileError as exc:
        logger.error(
            "patch_file_error",
            error=str(exc),
            file_path=exc.file_path,
            operation=exc.operation,
        )
        audit_logger.complete_operation(
            operation_id=audit_entry.operation_id,
            success=False,
            error_message=str(exc),
        )
        return {
            "success": False,
            "error": str(exc),
            "operation_id": audit_entry.operation_id,
        }
    except Exception as exc:
        error_msg = f"Unexpected error during patch: {str(exc)}"
        logger.error(
            "patch_unexpected_error", error=error_msg, exception_type=type(exc).__name__
        )
        audit_logger.complete_operation(
            operation_id=audit_entry.operation_id,
            success=False,
            error_message=error_msg,
        )
        return {
            "success": False,
            "error": error_msg,
            "operation_id": audit_entry.operation_id,
        }



def _rollback_changes(
    graph: InMemoryGraph,
    applied_changes: list[FileChange],
    rollback_actions: list[tuple],
    updater: IncrementalGraphUpdater,
    root_path: Path,
    cache: Any = None,
) -> None:
    """Rollback applied changes in reverse order."""
    logger.info("rollback_start", applied_count=len(applied_changes))

    for action in reversed(rollback_actions):
        try:
            action_type, path, *args = action
            abs_path = root_path / path

            if action_type == "add_file":
                # File was deleted, need to restore it
                # Note: This is a simplified rollback - full restoration would need the original content
                logger.warning(
                    "rollback_add_file_not_implemented",
                    path=path,
                    note="Full restoration of deleted files requires original content backup"
                )
                # Skip this rollback action - the file will need to be re-parsed from disk

            elif action_type == "restore_file":
                # File was modified, restore to previous state
                old_hash = args[0] if args else None
                # Simplified - would need to restore from backup or re-parse original

            elif action_type == "delete_file":
                # File was added, remove it
                updater.remove_entities_for_file(graph, str(abs_path))

            elif action_type == "delete_opaque_file":
                if cache is not None:
                    cache.delete_file_snapshot(str(abs_path))
                else:
                    logger.warning(
                        "rollback_delete_opaque_file_no_cache",
                        path=path,
                        note="Cache required for opaque file rollback but not provided"
                    )

            elif action_type == "restore_opaque_file":
                if cache is not None:
                    old_snap = args[0] if args else None
                    if old_snap is not None:
                        cache.set_file_snapshot(old_snap)
                    else:
                        cache.delete_file_snapshot(str(abs_path))
                else:
                    logger.warning(
                        "rollback_restore_opaque_file_no_cache",
                        path=path,
                        note="Cache required for opaque file rollback but not provided"
                    )

        except Exception as exc:
            logger.error("rollback_action_failed", action=action, error=str(exc))

    logger.info("rollback_complete")


# ---------------------------------------------------------------------------
# Patch Persistence Functions
# ---------------------------------------------------------------------------


def save_patch_operation(ctn_dir: Path, operation: PatchOperation) -> None:
    """Save a patch operation to the artifact database."""
    db = _get_db(ctn_dir)
    patch_data = operation.serialize()
    db.register_artifact(
        operation.operation_id,
        artifact_type="patch_operation_json",
        logical_path=f"patch_{operation.operation_id}",
        size_bytes=len(json.dumps(patch_data).encode("utf-8")),
        schema_version="patch-operation.v1",
        producer="time_machine.save_patch_operation",
        metadata=patch_data,
        retention_class="patch",
    )
    logger.info("patch_operation_saved", operation_id=operation.operation_id)


def load_patch_operation(ctn_dir: Path, operation_id: str) -> PatchOperation | None:
    """Load a patch operation from the artifact database."""
    db = _get_db(ctn_dir)
    with db.connection(read_only=True) as conn:
        row = conn.execute(
            """SELECT metadata_json FROM artifacts
            WHERE artifact_id = ? AND artifact_type = 'patch_operation_json'
            AND deleted = 0""",
            (operation_id,),
        ).fetchone()

    if row is None:
        logger.warning("patch_operation_not_found", operation_id=operation_id)
        return None

    try:
        data = json.loads(row["metadata_json"])
        operation = PatchOperation.from_dict(data)
        if not operation.validate():
            logger.warning(
                "patch_operation_checksum_invalid", operation_id=operation_id
            )
            return None
        return operation
    except Exception as exc:
        logger.error(
            "patch_operation_load_failed", operation_id=operation_id, error=str(exc)
        )
        return None


def update_patch_index(ctn_dir: Path, operation: PatchOperation) -> None:
    """No-op: patch operations are stored individually in the DB."""
    pass


def list_patch_operations(
    ctn_dir: Path, filters: dict[str, Any] | None = None
) -> list[PatchOperation]:
    """List patch operations from the artifact database."""
    db = _get_db(ctn_dir)
    with db.connection(read_only=True) as conn:
        rows = conn.execute(
            """SELECT artifact_id, metadata_json FROM artifacts
            WHERE artifact_type = 'patch_operation_json' AND deleted = 0
            ORDER BY updated_at DESC"""
        ).fetchall()

    patches: list[PatchOperation] = []
    for row in rows:
        try:
            data = json.loads(row["metadata_json"])
            op = PatchOperation.from_dict(data)

            if filters:
                if "operation_type" in filters and op.operation_type != filters["operation_type"]:
                    continue
                if "base_snapshot_id" in filters and op.base_snapshot_id != filters["base_snapshot_id"]:
                    continue
                if "new_snapshot_id" in filters and op.new_snapshot_id != filters["new_snapshot_id"]:
                    continue

            patches.append(op)
        except Exception:
            continue

    return patches


def get_patches_for_snapshot(ctn_dir: Path, snapshot_id: str) -> list[PatchOperation]:
    """Get all patch operations that led to a snapshot."""
    patches = list_patch_operations(ctn_dir)
    result = []

    for patch in patches:
        if patch.new_snapshot_id == snapshot_id:
            result.append(patch)

    return result


def cleanup_old_patches(ctn_dir: Path, config: dict[str, Any]) -> int:
    """Clean up old patches based on retention policy (soft-delete in DB)."""
    max_days = config.get("max_patch_history_days", 90)
    max_count = config.get("max_patch_count", 1000)

    cutoff_time = datetime.now(timezone.utc) - timedelta(days=max_days)
    patches = list_patch_operations(ctn_dir)
    cleaned_count = 0

    patches.sort(key=lambda x: x.timestamp, reverse=True)

    db = _get_db(ctn_dir)
    for i, patch in enumerate(patches):
        if i >= max_count or patch.timestamp < cutoff_time:
            # Soft-delete in the DB
            with db.connection() as conn:
                conn.execute(
                    "UPDATE artifacts SET deleted = 1, updated_at = ? WHERE artifact_id = ?",
                    (datetime.now(timezone.utc).isoformat(), patch.operation_id),
                )
                conn.commit()
            cleaned_count += 1

    if cleaned_count > 0:
        logger.info("patches_cleaned", cleaned_count=cleaned_count)

    return cleaned_count


def build_patch_chain(
    ctn_dir: Path, base_snapshot_id: str, current_operation_id: str
) -> list[str]:
    """Build the patch chain for a new patch operation."""
    # Get patches for the base snapshot
    base_patches = get_patches_for_snapshot(ctn_dir, base_snapshot_id)

    if not base_patches:
        # Base snapshot has no patches (initial snapshot)
        return [current_operation_id]

    # Get the patch chain from the most recent patch that created the base snapshot
    latest_base_patch = max(base_patches, key=lambda x: x.timestamp)
    chain = latest_base_patch.patch_chain.copy()
    chain.append(current_operation_id)

    return chain


def estimate_token_changes(changes: list[FileChange]) -> int:
    """Estimate token size for a set of file changes."""
    # Simple heuristic: ~4 tokens per line of code
    total_tokens = 0
    for change in changes:
        if change.file_size:
            # Estimate lines from file size (assuming ~50 bytes per line)
            estimated_lines = max(1, change.file_size // 50)
            total_tokens += estimated_lines * 4
        else:
            # Default estimate for unknown file size
            total_tokens += 100  # ~25 lines * 4 tokens
    return total_tokens


# ---------------------------------------------------------------------------
# Patch Application Functions (Phase 5)
# ---------------------------------------------------------------------------


def parse_unified_diff(diff_content: str) -> list[FileChange]:
    """Parse a unified diff into FileChange objects."""
    changes = []
    lines = diff_content.split("\n")
    current_file = None
    old_hash = None
    new_hash = None

    for line in lines:
        if line.startswith("diff --git"):
            # Parse file path from git diff header
            parts = line.split()
            if len(parts) >= 4:
                current_file = parts[3][2:]  # Remove 'b/' prefix
        elif line.startswith("index "):
            # Parse file hashes
            hash_parts = line.split()[1].split("..")
            if len(hash_parts) == 2:
                old_hash, new_hash = hash_parts
        elif line.startswith("new file mode"):
            # New file detected
            if current_file:
                changes.append(
                    FileChange(
                        path=current_file,
                        change_type=FileChangeType.ADDED,
                        old_hash=None,
                        new_hash=new_hash,
                    )
                )
        elif line.startswith("deleted file mode"):
            # Deleted file detected
            if current_file:
                changes.append(
                    FileChange(
                        path=current_file,
                        change_type=FileChangeType.DELETED,
                        old_hash=old_hash,
                        new_hash=None,
                    )
                )
        elif line.startswith("@@"):
            # Modified file (has hunks)
            if current_file and old_hash and new_hash:
                # Check if this is actually a modification or just file metadata change
                if not any(c.path == current_file for c in changes):
                    changes.append(
                        FileChange(
                            path=current_file,
                            change_type=FileChangeType.MODIFIED,
                            old_hash=old_hash,
                            new_hash=new_hash,
                        )
                    )

    return changes


def validate_patch_compatibility(
    patch_data: dict[str, Any], base_snapshot_id: str, ctn_dir: Path
) -> bool:
    """Validate that a patch can be applied to a base snapshot.

    Performs sophisticated validation including:
    - Required fields check
    - File existence in base snapshot
    - Patch consistency checks
    - Dependency validation

    Args:
        patch_data: Patch operation data to validate
        base_snapshot_id: ID of the base snapshot
        ctn_dir: Path to .ctn directory containing snapshots

    Returns:
        True if patch is compatible, False otherwise
    """
    logger = get_logger(__name__, component="patch_validation")

    # Basic validation - check required fields
    required_fields = ["changes_applied", "operation_type"]
    for field in required_fields:
        if field not in patch_data:
            logger.error("patch_missing_required_field", field=field)
            return False

    # Load base snapshot for validation
    base_snapshot = load_snapshot(ctn_dir, base_snapshot_id)
    if base_snapshot is None:
        logger.error(
            "patch_validation_base_snapshot_not_found", snapshot_id=base_snapshot_id
        )
        return False

    # Extract file paths from base snapshot
    base_files = set()
    if "graph" in base_snapshot and "entities" in base_snapshot["graph"]:
        for entity in base_snapshot["graph"]["entities"]:
            if "file_path" in entity:
                base_files.add(entity["file_path"])

    # Validate each change in the patch
    changes_applied = patch_data.get("changes_applied", [])
    for change in changes_applied:
        if isinstance(change, dict):
            change_path = change.get("path")
            change_type = change.get("change_type")
        else:
            # Handle FileChange objects
            change_path = getattr(change, "path", None)
            change_type = getattr(change, "change_type", None)

        if not change_path or not change_type:
            logger.error("patch_invalid_change", change=change)
            return False

        # Validate file operations based on change type
        if change_type in ["MODIFIED", "DELETED"]:
            # For modifications and deletions, file must exist in base snapshot
            if change_path not in base_files:
                logger.error(
                    "patch_file_not_in_base",
                    path=change_path,
                    change_type=change_type,
                    available_files=list(base_files)[:10],
                )  # Log first 10 for debugging
                return False

        elif change_type == "ADDED":
            # For additions, file should not exist in base snapshot (unless it's a re-add)
            if change_path in base_files:
                logger.warning("patch_adding_existing_file", path=change_path)
                # This is not necessarily an error - could be a re-add after deletion

    # Check for patch dependencies if specified
    if "dependencies" in patch_data:
        dependencies = patch_data["dependencies"]
        if not _validate_patch_dependencies(dependencies, base_snapshot_id, ctn_dir):
            logger.error("patch_dependencies_not_satisfied", dependencies=dependencies)
            return False

    logger.info(
        "patch_validation_success",
        changes_count=len(changes_applied),
        base_snapshot=base_snapshot_id,
    )
    return True


def _validate_patch_dependencies(
    dependencies: list[str], base_snapshot_id: str, ctn_dir: Path
) -> bool:
    """Validate that all patch dependencies are satisfied.

    Args:
        dependencies: List of patch IDs that this patch depends on
        base_snapshot_id: Base snapshot ID
        ctn_dir: Repository root path (legacy name, actually repo root)

    Returns:
        True if all dependencies are satisfied, False otherwise
    """
    logger = get_logger(__name__, component="patch_validation")

    for dep_patch_id in dependencies:
        # Check if dependency patch exists in database
        dep_patch = load_patch_operation(ctn_dir, dep_patch_id)
        if dep_patch is None:
            logger.error("patch_dependency_not_found", dependency=dep_patch_id)
            return False

        # Validate dependency patch was successful
        if not dep_patch.validate():
            logger.error("patch_dependency_checksum_invalid", dependency=dep_patch_id)
            return False

    return True


def extract_patch_deltas(operation: PatchOperation) -> dict[str, Any]:
    """Extract reusable deltas from a patch operation."""
    return {
        "operation_id": operation.operation_id,
        "changes_applied": operation.changes_applied,
        "operation_type": operation.operation_type,
        "metrics": operation.metrics,
        "timestamp": operation.timestamp.isoformat(),
    }


def apply_deltas_to_snapshot(
    ctn_dir: Path, base_snapshot_id: str, deltas: dict[str, Any]
) -> str | None:
    """Apply patch deltas to a base snapshot and return new snapshot ID."""
    try:
        # Validate patch compatibility before applying
        if not validate_patch_compatibility(deltas, base_snapshot_id, ctn_dir):
            logger.error(
                "patch_delta_validation_failed",
                base_snapshot=base_snapshot_id,
                operation_id=deltas.get("operation_id"),
            )
            return None

        # Load base snapshot
        base_snapshot = load_snapshot(ctn_dir, base_snapshot_id)
        if not base_snapshot:
            logger.error("base_snapshot_not_found", snapshot_id=base_snapshot_id)
            return None

        # Convert deltas back to FileChange objects
        changes = []
        for change_data in deltas["changes_applied"]:
            if isinstance(change_data, dict):
                changes.append(FileChange.from_dict(change_data))
            else:
                changes.append(change_data)

        # Apply changes using incremental_patch
        result = incremental_patch(ctn_dir, base_snapshot_id, changes)

        if result.get("success"):
            return result.get("new_snapshot_id")
        else:
            logger.error("delta_application_failed", error=result.get("error"))
            return None

    except Exception as exc:
        logger.error("apply_deltas_error", error=str(exc))
        return None
