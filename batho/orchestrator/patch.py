"""Orchestrator for `batho patch` — incremental index update for existing databases.

Detects changes (git-first, hash-scan fallback), applies incremental graph updates,
and refreshes all DB artifacts (entities, relationships, BSG, context outputs, snapshot, file tracking).
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from batho.config import get_config_cached
from batho.utils.logging import get_logger
from batho.storage.engine import BathoDatabase
from batho.time_machine import (
    FileChange,
    FileChangeType,
    FileChangeTracker,
    incremental_patch,
    load_snapshot,
)
from batho.context.incremental import (
    get_changed_file_status_since,
    GitDiffEntry,
    PatchMode,
    get_changed_files_by_mode,
)
from batho.context.bsg_map import BSGMap
from batho.context.codegraph import InMemoryGraph
from batho.utils.hash import compute_file_hash

LOGGER = get_logger(__name__, component="orchestrator.patch")


# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------


@dataclass
class PatchOptions:
    """Configuration for a patch run."""

    root: Path
    verbose: bool = False
    max_file_size_kb: int | None = None
    mode: PatchMode = PatchMode.AUTO


@dataclass
class PatchResult:
    """Outcome of a patch run."""

    success: bool
    run_id: str = ""
    base_snapshot_id: str = ""
    new_snapshot_id: str = ""
    changes_applied: int = 0
    added: int = 0
    modified: int = 0
    deleted: int = 0
    entity_count: int = 0
    relationship_count: int = 0
    duration_ms: int = 0
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _generate_run_id() -> str:
    """Generate a unique run ID (timestamp + short uuid) for patch."""
    ts = int(time.time())
    short = uuid.uuid4().hex[:8]
    return f"patch_{ts}_{short}"


def _git_entries_to_file_changes(
    entries: list[GitDiffEntry], root: Path, max_file_size_kb: int | None = None
) -> list[FileChange]:
    """Convert GitDiffEntry list to FileChange list."""
    mapping = {
        "A": FileChangeType.ADDED,
        "M": FileChangeType.MODIFIED,
        "D": FileChangeType.DELETED,
    }
    changes = []
    max_bytes = (max_file_size_kb * 1024) if max_file_size_kb else None
    for entry in entries:
        change_type = mapping.get(entry.status)
        if not change_type:
            continue
        full = root / entry.path
        new_hash = None
        if full.exists():
            # Skip hashing for files exceeding size limit
            if max_bytes is not None:
                try:
                    file_size = full.stat().st_size
                    if file_size > max_bytes:
                        LOGGER.debug("skipping_hash_large_file", path=entry.path, size_kb=file_size // 1024)
                        new_hash = None
                    else:
                        new_hash = compute_file_hash(full)
                except (OSError, IOError):
                    new_hash = None
            else:
                new_hash = compute_file_hash(full)
        changes.append(
            FileChange(
                path=entry.path,
                change_type=change_type,
                old_hash=None,
                new_hash=new_hash,
            )
        )
    return changes


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


def run_patch(options: PatchOptions) -> PatchResult:
    """Incremental patch of an existing .batho database."""
    from batho.storage.engine import artifact_filename, get_database
    t0 = time.monotonic()
    root = options.root.resolve()
    db_path = root / artifact_filename(root)

    # 1. Resolve root, validate database exists
    if not db_path.exists():
        msg = f"No artifact database found at {root}. Run: batho build --root {root}"
        LOGGER.error("patch_failed_no_db", root=str(root))
        return PatchResult(
            success=False,
            warnings=[msg],
        )

    # 2. Open DB, get latest snapshot
    db = get_database(root)
    try:
        snapshots = db.list_snapshots()
        if not snapshots:
            msg = f"No baseline snapshot found. Run: batho build --root {root} --full"
            LOGGER.error("patch_failed_no_snapshot", root=str(root))
            return PatchResult(
                success=False,
                warnings=[msg],
            )

        # Sort snapshots by created_at ascending so that [-1] is the newest
        snapshots_sorted = sorted(snapshots, key=lambda s: s.get("created_at", ""))
        latest_snap = snapshots_sorted[-1]
        base_snapshot_id = latest_snap["snapshot_id"]
        base_snapshot = load_snapshot(root, base_snapshot_id)
        if base_snapshot is None:
            LOGGER.error("patch_failed_load_snapshot", snapshot_id=base_snapshot_id)
            return PatchResult(
                success=False,
                base_snapshot_id=base_snapshot_id,
                warnings=[f"Failed to load baseline snapshot: {base_snapshot_id}"],
            )

        # Get base run ID before we start the new run (fixes concurrent race condition)
        base_run_id = db.get_latest_run_id()

        # Compute max_file_size_kb early for use in both git and fallback paths
        max_file_size_kb = options.max_file_size_kb or \
            get_config_cached().get("indexer", {}).get("max_file_size_kb", 500)

        # 3. Detect changes based on mode
        if options.mode == PatchMode.COMMIT:
            # Original commit-based detection
            git_entries = get_changed_file_status_since(
                base_snapshot_id, root, base_snapshot
            )
        else:
            # Staged/Modified/Auto mode - compare against HEAD
            git_entries = get_changed_files_by_mode(options.mode, root)

        if git_entries is not None:
            changes = _git_entries_to_file_changes(git_entries, root, max_file_size_kb)
        else:
            # FALLBACK: Hash scan (works for all modes)
            if base_snapshot is None:
                error_msg = f"Failed to load baseline snapshot for hash scan: {base_snapshot_id}"
                LOGGER.error("patch_failed_base_snapshot_none", snapshot_id=base_snapshot_id)
                return PatchResult(
                    success=False,
                    base_snapshot_id=base_snapshot_id,
                    warnings=[error_msg],
                )
            tracker = FileChangeTracker(root)
            tracker.load()
            changes = tracker.scan_for_changes(
                max_file_size_kb=max_file_size_kb,
                base_snapshot=base_snapshot,
            )

        # 4. No changes?
        if not changes:
            LOGGER.info("patch_no_changes", root=str(root))
            return PatchResult(
                success=True,
                base_snapshot_id=base_snapshot_id,
                warnings=["No changes detected since last build/patch"],
            )

        # 5. Create new run in DB
        run_id = _generate_run_id()
        from batho.context.incremental import get_head_commit, is_git_repo
        from batho.time_machine import _git_branch_name
        git_commit = get_head_commit(root) if is_git_repo(root) else None
        git_branch = _git_branch_name(root) if is_git_repo(root) else None
        db.create_run(
            run_id,
            schema_version="batho-db.v1",
            root_path=str(root),
            git_commit=git_commit,
            git_branch=git_branch,
        )
        LOGGER.info("patch_started", root=str(root), run_id=run_id, base_snapshot_id=base_snapshot_id)

        # 6. Apply incremental patch via time_machine
        patch_op_result = incremental_patch(root, base_snapshot_id, changes)
        if not patch_op_result.get("success"):
            error_msg = patch_op_result.get("error", "Incremental patch execution failed.")
            LOGGER.error("patch_engine_failed", error=error_msg)
            db.fail_run(run_id, error_message=error_msg)
            return PatchResult(
                success=False,
                run_id=run_id,
                base_snapshot_id=base_snapshot_id,
                warnings=[error_msg],
            )

        new_snapshot_id = patch_op_result["new_snapshot_id"]

        # 7. Refresh BSG entries in DB for changed files (BUG FIX)
        new_snapshot = load_snapshot(root, new_snapshot_id)
        if new_snapshot is None:
            error_msg = f"Failed to load newly created snapshot: {new_snapshot_id}"
            LOGGER.error("patch_failed_load_new_snapshot", snapshot_id=new_snapshot_id)
            db.fail_run(run_id, error_message=error_msg)
            return PatchResult(
                success=False,
                run_id=run_id,
                base_snapshot_id=base_snapshot_id,
                new_snapshot_id=new_snapshot_id,
                warnings=[error_msg],
            )

        patched_graph = InMemoryGraph.from_dict(new_snapshot["graph"])

        opaque_snapshots = []
        try:
            from batho.context.unified_cache import BathoCache
            cache = BathoCache(str(db_path))
            try:
                all_snaps_dict = cache.get_all_file_snapshots()
                if all_snaps_dict:
                    opaque_snapshots = [s for s in all_snaps_dict.values() if not s.entity_ids]
            finally:
                cache.close()
        except Exception as exc:
            LOGGER.warning("patch_opaque_snapshots_failed", error=str(exc))

        bsg_map = BSGMap.build(patched_graph, str(root), opaque_snapshots=opaque_snapshots)

        # Copy all BSG entries from base run
        if base_run_id:
            with db.connection() as conn:
                conn.execute(
                    """INSERT INTO bsg_entries(run_id, file_path, view_type, bsg_json, token_count, node_count, checksum)
                       SELECT ? as run_id, file_path, view_type, bsg_json, token_count, node_count, checksum
                       FROM bsg_entries WHERE run_id = ?""",
                    (run_id, base_run_id)
                )
                conn.commit()

        # Delete old BSG entries for changed files under the new run ID
        from batho.context.bsg_map.relativizer import PathRelativizer
        path_rel = PathRelativizer(root)

        with db.connection() as conn:
            for change in changes:
                conn.execute(
                    "DELETE FROM bsg_entries WHERE run_id = ? AND file_path = ?",
                    (run_id, path_rel(change.path))
                )
            conn.commit()

        # Insert new BSG entries for changed files
        bsg_entries_to_insert = []
        for change in changes:
            if change.change_type == FileChangeType.DELETED:
                continue
            change_rel = path_rel(change.path)
            entities = bsg_map._by_file.get(change_rel)
            if entities is not None:
                bsg_json_data = json.dumps(
                    [e.to_dict(view="agent") for e in entities],
                    ensure_ascii=True,
                )
                checksum = hashlib.sha256(bsg_json_data.encode()).hexdigest()
                bsg_entries_to_insert.append({
                    "file_path": change_rel,
                    "view_type": "agent",
                    "bsg_json": bsg_json_data,
                    "node_count": len(entities),
                    "checksum": checksum,
                })
        if bsg_entries_to_insert:
            db.insert_bsg_entries(run_id, bsg_entries_to_insert)

        # 8. Refresh context outputs
        from batho.orchestrator.build import _build_context_overview, _build_context_files
        overview_data = _build_context_overview(patched_graph, root)
        files_data = _build_context_files(patched_graph, root)
        db.set_context_output(run_id, "overview", json.dumps(overview_data, ensure_ascii=True))
        db.set_context_output(run_id, "files", json.dumps(files_data, ensure_ascii=True))

        # 9. Update file tracking
        def _rel(fp):
            try:
                return str(Path(fp).relative_to(root))
            except ValueError:
                return str(fp)

        for change in changes:
            if change.change_type == FileChangeType.DELETED:
                db.delete_file_tracking(change.path)
            elif change.change_type in (FileChangeType.ADDED, FileChangeType.MODIFIED):
                full_path = root / change.path
                if full_path.exists():
                    try:
                        stat = full_path.stat()
                        rel_path = str(Path(change.path))
                        has_entities = any(_rel(e.file) == rel_path for e in patched_graph.entities.values())
                        is_indexed = 1 if has_entities else 0
                        content_hash = change.new_hash or compute_file_hash(full_path) or ""
                        record = {
                            "file_path": change.path,
                            "content_hash": content_hash,
                            "mtime": stat.st_mtime,
                            "size": stat.st_size,
                            "is_indexed": is_indexed,
                            "last_run_id": run_id,
                        }
                        db.upsert_file_tracking([record])
                    except OSError:
                        pass

        # 10. Persist updated entities/relationships
        if base_run_id:
            with db.connection() as conn:
                conn.execute(
                    """INSERT INTO graph_entities(
                        run_id, entity_id, entity_type, name, file_path,
                        start_line, end_line, start_byte, end_byte,
                        signature, parent_id, content_hash, ast_node_type, metadata_json
                    )
                    SELECT ? as run_id, entity_id, entity_type, name, file_path,
                           start_line, end_line, start_byte, end_byte,
                           signature, parent_id, content_hash, ast_node_type, metadata_json
                    FROM graph_entities WHERE run_id = ?""",
                    (run_id, base_run_id)
                )
                conn.execute(
                    """INSERT INTO graph_relationships(
                        run_id, relationship_id, relationship_type, source_id, target_id, metadata_json
                    )
                    SELECT ? as run_id, relationship_id, relationship_type, source_id, target_id, metadata_json
                    FROM graph_relationships WHERE run_id = ?""",
                    (run_id, base_run_id)
                )
                conn.commit()

        # Apply changes (delete changed files' entities and relationships)
        with db.connection() as conn:
            for change in changes:
                abs_path = str((root / change.path).resolve())
                conn.execute(
                    """DELETE FROM graph_relationships
                       WHERE run_id = ? AND (
                           source_id IN (SELECT entity_id FROM graph_entities WHERE run_id = ? AND file_path = ?)
                           OR
                           target_id IN (SELECT entity_id FROM graph_entities WHERE run_id = ? AND file_path = ?)
                       )""",
                    (run_id, run_id, abs_path, run_id, abs_path)
                )
                conn.execute(
                    "DELETE FROM graph_entities WHERE run_id = ? AND file_path = ?",
                    (run_id, abs_path)
                )
            conn.commit()

        # Insert new entities and relationships from the patched graph
        changed_abs_paths = {str((root / c.path).resolve()) for c in changes if c.change_type in (FileChangeType.ADDED, FileChangeType.MODIFIED)}
        new_entities = []
        changed_entity_ids = set()
        for entity in patched_graph.entities.values():
            if str(Path(entity.file).resolve()) in changed_abs_paths:
                new_entities.append(entity.to_dict())
                changed_entity_ids.add(entity.id)

        new_relationships = []
        for r in patched_graph.relationships:
            if r.source_id in changed_entity_ids or r.target_id in changed_entity_ids:
                new_relationships.append(r.to_dict())

        if new_entities:
            db.insert_entities(run_id, new_entities)
        if new_relationships:
            db.insert_relationships(run_id, new_relationships)

        # 11. Complete run
        entity_count = db.get_entity_count(run_id)
        rel_count = db.get_relationship_count(run_id)

        with db.connection(read_only=True) as conn:
            row = conn.execute(
                "SELECT COUNT(DISTINCT file_path) as cnt FROM bsg_entries WHERE run_id = ?",
                (run_id,)
            ).fetchone()
            file_count = row["cnt"] if row else 0

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        db.complete_run(
            run_id,
            entity_count=entity_count,
            rel_count=rel_count,
            file_count=file_count,
            duration_ms=elapsed_ms,
        )

        LOGGER.info(
            "patch_complete",
            run_id=run_id,
            entities=entity_count,
            relationships=rel_count,
            files=file_count,
            duration_ms=elapsed_ms,
        )

        # 12. Return PatchResult
        return PatchResult(
            success=True,
            run_id=run_id,
            base_snapshot_id=base_snapshot_id,
            new_snapshot_id=new_snapshot_id,
            changes_applied=len(changes),
            added=sum(1 for c in changes if c.change_type == FileChangeType.ADDED),
            modified=sum(1 for c in changes if c.change_type == FileChangeType.MODIFIED),
            deleted=sum(1 for c in changes if c.change_type == FileChangeType.DELETED),
            entity_count=entity_count,
            relationship_count=rel_count,
            duration_ms=elapsed_ms,
        )
    finally:
        pass
