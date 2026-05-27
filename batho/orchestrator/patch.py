"""Orchestrator for `batho patch` — incremental index update (v3.0).

Uses native hash-based change detection against the file_tracking table.
Git is no longer used for change detection; it is only captured for metadata.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from batho.core.config import get_config_cached, set_active_root
from batho.utils.logging import get_logger

from batho.modules.compression.bsg_map import BSGMap
from batho.modules.graph.builder.codegraph import InMemoryGraph
from batho.utils.hash import compute_file_hash

LOGGER = get_logger(__name__, component="orchestrator.patch")


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


@dataclass
class PatchOptions:
    """Configuration for a patch run."""

    root: Path
    verbose: bool = False
    max_file_size_kb: int | None = None


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
    nodes_added: int = 0
    nodes_removed: int = 0
    nodes_modified: int = 0
    nodes_renamed: int = 0


def _generate_run_id() -> str:
    ts = int(time.time())
    short = uuid.uuid4().hex[:8]
    return f"patch_{ts}_{short}"



def _hash_scan_changes(
    root: Path,
    known_tracking: dict[str, dict],
    max_file_size_kb: int | None = None,
    strict_hashing: bool = True,
) -> list[FileChange]:
    """Fallback: scan filesystem for added/modified/deleted files.

    known_tracking maps relative path -> {"content_hash": str, "mtime": float, "size": int}.
    
    Args:
        root: Root directory to scan.
        known_tracking: Dictionary of tracked files with their metadata.
        max_file_size_kb: Maximum file size to consider.
        strict_hashing: If True, always compute content hash regardless of mtime/size.
                       If False, skip hashing when mtime/size unchanged (faster but
                       may miss content changes with preserved timestamps.
    """
    from batho.modules.graph.incremental import _collect_candidate_files

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
            new_hash = compute_file_hash(abs_path)
            changes.append(FileChange(rel, FileChangeType.ADDED, new_hash=new_hash))
            continue

        old_hash = tracked["content_hash"]

        # Strict hashing: always compute hash to catch content changes with preserved timestamps
        # Non-strict: skip hashing when mtime/size unchanged for performance
        if not strict_hashing:
            tracked_mtime_ns = tracked.get("mtime_ns")
            if tracked_mtime_ns is None:
                tracked_mtime = tracked.get("mtime")
                if tracked_mtime is not None:
                    tracked_mtime_ns = int(tracked_mtime * 1e9)
            tracked_ino = tracked.get("inode")

            # Cheap pre-filter: skip hashing when mtime/size (and inode when known) are unchanged.
            if tracked_mtime_ns is not None and tracked_ino is not None:
                if (
                    st.st_mtime_ns == tracked_mtime_ns
                    and st.st_ino == tracked_ino
                    and st.st_size == tracked.get("size")
                ):
                    continue
            else:
                if st.st_mtime == tracked.get("mtime") and st.st_size == tracked.get("size"):
                    continue

        # Compute hash, catching errors (e.g., file modified concurrently)
        try:
            new_hash = compute_file_hash(abs_path)
        except OSError:
            continue

        if old_hash != new_hash:
            changes.append(FileChange(rel, FileChangeType.MODIFIED, old_hash=old_hash, new_hash=new_hash))

    for rel, tracked in known_tracking.items():
        if rel not in current_files:
            changes.append(FileChange(rel, FileChangeType.DELETED, old_hash=tracked["content_hash"]))

    return changes


def run_patch(options: PatchOptions) -> PatchResult:
    """Incremental patch of an existing .batho database."""
    from batho.modules.storage.sqlite_registry.engine import resolve_db_path, get_database

    t0 = time.monotonic()
    root = options.root.resolve()
    
    if not root.exists():
        return PatchResult(
            success=False,
            warnings=[f"Repository root does not exist: {root}"],
        )
    if not root.is_dir():
        return PatchResult(
            success=False,
            warnings=[f"Repository root is not a directory: {root}"],
        )

    set_active_root(root)
    db_path = resolve_db_path(root)

    if not db_path.exists():
        msg = f"No artifact database found at {root}. Run: batho build --root {root}"
        LOGGER.error("patch_failed_no_db", root=str(root))
        return PatchResult(success=False, warnings=[msg])

    db = None
    run_uuid = ""
    base_run_uuid = ""
    try:
        db = get_database(root)
        base_run_uuid = db.get_latest_run_id() or ""
        if not base_run_uuid:
            msg = f"No completed run found. Run: batho build --root {root}"
            LOGGER.error("patch_failed_no_run", root=str(root))
            return PatchResult(success=False, warnings=[msg])

        base_run_internal_id = db.get_run_internal_id(base_run_uuid)
        cfg = get_config_cached()
        max_file_size_kb = options.max_file_size_kb or cfg.get("indexer", {}).get("max_file_size_kb", 500)

        # --- Detect changes natively (Batho's Local Git Model) ---
        known_tracking = db.get_all_file_tracking()
        changes = _hash_scan_changes(root, known_tracking, max_file_size_kb)

        if not changes:
            LOGGER.info("patch_no_changes", root=str(root))
            return PatchResult(
                success=True,
                base_snapshot_id=base_run_uuid,
                warnings=["No changes detected since last build/patch"],
            )

        # --- Create new run ---
        run_uuid = _generate_run_id()
        from batho.modules.graph.incremental import get_head_commit, is_git_repo
        git_commit = get_head_commit(root) if is_git_repo(root) else None
        git_branch: str | None = None
        try:
            from batho.modules.graph.incremental import get_current_branch
            git_branch = get_current_branch(root) if is_git_repo(root) else None
        except (ImportError, Exception):
            pass

        run_internal_id = db.create_run(
            run_uuid,
            root_path=str(root),
            git_commit=git_commit,
            git_branch=git_branch,
        )
        LOGGER.info("patch_started", root=str(root), run_id=run_uuid, base_run=base_run_uuid)

        # --- Blob-level copy-on-write for unchanged files ---
        # INVARIANT: c.path must be a relative path (relative to root) because:
        #   - file_artifacts uses integer file_id (looked up from string_dict by relative path)
        #   - query_entities.file_path stores the same relative path string
        # `_hash_scan_changes` produces relative paths.
        # If this invariant breaks, query_entities for changed files won't be excluded and
        # stale entities from the base run will bleed into the new run.
        changed_file_paths = {c.path for c in changes}
        # Enforce relative path invariant — absolute paths would silently break
        # the query_entities copy-on-write filter.
        for _p in changed_file_paths:
            if Path(_p).is_absolute():
                raise ValueError(
                    f"FileChange.path must be relative to root, got absolute: {_p!r}"
                )
        if base_run_internal_id is not None:
            with db.transaction() as conn:
                # Use temporary tables to prevent exceeding SQLITE_MAX_VARIABLE_NUMBER (default 999)
                conn.execute("CREATE TEMP TABLE IF NOT EXISTS temp_changed_file_paths (file_path TEXT PRIMARY KEY)")
                conn.execute("DELETE FROM temp_changed_file_paths")
                conn.executemany("INSERT OR IGNORE INTO temp_changed_file_paths (file_path) VALUES (?)", [(p,) for p in changed_file_paths])

                changed_ids_rows = conn.execute(
                    """SELECT id FROM string_dict
                       WHERE val IN (SELECT file_path FROM temp_changed_file_paths)"""
                ).fetchall()
                changed_file_ids = {row["id"] for row in changed_ids_rows}

                conn.execute("CREATE TEMP TABLE IF NOT EXISTS temp_changed_file_ids (file_id INTEGER PRIMARY KEY)")
                conn.execute("DELETE FROM temp_changed_file_ids")
                if changed_file_ids:
                    conn.executemany("INSERT OR IGNORE INTO temp_changed_file_ids (file_id) VALUES (?)", [(fid,) for fid in changed_file_ids])

                # 1. Copy file_artifacts for unchanged files
                conn.execute(
                    f"""INSERT INTO file_artifacts(run_id, file_id, bsg_agent_view, bsg_storage_view, bsg_rel_view, content_hash)
                        SELECT ?, file_id, bsg_agent_view, bsg_storage_view, bsg_rel_view, content_hash
                        FROM file_artifacts
                        WHERE run_id = ? AND file_id NOT IN (SELECT file_id FROM temp_changed_file_ids)""",
                    [run_internal_id, base_run_internal_id],
                )
                # 2. Copy query_entities for unchanged files
                conn.execute(
                    f"""INSERT INTO query_entities (entity_id, run_id, entity_name, entity_type, fqn, file_path, line_number, signature, is_exported)
                        SELECT entity_id, ?, entity_name, entity_type, fqn, file_path, line_number, signature, is_exported
                        FROM query_entities
                        WHERE run_id = ? AND file_path NOT IN (SELECT file_path FROM temp_changed_file_paths)""",
                    [run_internal_id, base_run_internal_id],
                )
                # 3. Copy query_relationships for unchanged files
                # - Direct copy for relationships where both source and target are in unchanged files
                conn.execute(
                    f"""INSERT INTO query_relationships (source_id, target_id, relation_type, run_id, metadata_json)
                        SELECT r.source_id, r.target_id, r.relation_type, ?, r.metadata_json
                        FROM query_relationships r
                        WHERE r.run_id = ?
                          AND r.source_id IN (
                              SELECT entity_id FROM query_entities
                              WHERE run_id = ? AND file_path NOT IN (SELECT file_path FROM temp_changed_file_paths)
                          )
                          AND r.target_id NOT IN (
                              SELECT entity_id FROM query_entities
                              WHERE run_id = ? AND file_path IN (SELECT file_path FROM temp_changed_file_paths)
                          )""",
                    [run_internal_id, base_run_internal_id, base_run_internal_id, base_run_internal_id],
                )
                # - Convert relationships pointing to changed target files to dangling_references so they can be re-resolved
                conn.execute(
                    f"""INSERT INTO dangling_references (source_id, unresolved_target_name, relation_type, run_id)
                        SELECT r.source_id, COALESCE(e.entity_name, r.target_id), r.relation_type, ?
                        FROM query_relationships r
                        LEFT JOIN query_entities e ON r.target_id = e.entity_id AND r.run_id = e.run_id
                        WHERE r.run_id = ?
                          AND r.source_id IN (
                              SELECT entity_id FROM query_entities
                              WHERE run_id = ? AND file_path NOT IN (SELECT file_path FROM temp_changed_file_paths)
                          )
                          AND e.file_path IN (SELECT file_path FROM temp_changed_file_paths)""",
                    [run_internal_id, base_run_internal_id, base_run_internal_id],
                )
                # 4. Copy dangling_references for unchanged files
                conn.execute(
                    f"""INSERT INTO dangling_references (source_id, unresolved_target_name, relation_type, run_id)
                        SELECT source_id, unresolved_target_name, relation_type, ?
                        FROM dangling_references
                        WHERE run_id = ? AND source_id IN (
                            SELECT entity_id FROM query_entities
                            WHERE run_id = ? AND file_path NOT IN (SELECT file_path FROM temp_changed_file_paths)
                        )""",
                    [run_internal_id, base_run_internal_id, base_run_internal_id],
                )

        # --- Re-parse changed (non-deleted) files ---
        added_or_modified = [c for c in changes if c.change_type != FileChangeType.DELETED]
        deleted = [c for c in changes if c.change_type == FileChangeType.DELETED]

        t_batch_prep_ms = 0.0
        t_batch_write_ms = 0.0
        new_entity_count = 0
        new_rel_count = 0
        nodes_added = 0
        nodes_removed = 0
        nodes_modified = 0
        nodes_renamed = 0

        if added_or_modified:
            bsg_cfg = dict(cfg.get("bsg", {}))
            cache_cfg = dict(bsg_cfg.get("cache", {}))
            cache_cfg["enabled"] = True
            cache_cfg["path"] = str(db_path)
            bsg_cfg["cache"] = cache_cfg

            from batho.modules.graph.builder.codegraph import CodeGraphIndexer
            from batho.modules.storage.sqlite_registry.engine import _minify_graph_payload
            from collections import defaultdict

            with CodeGraphIndexer(cache_path=str(db_path), root=str(root)) as indexer:
                # Invalidate AST cache for changed/deleted files in unified cache
                for change in changes:
                    try:
                        indexer._cache.delete_ast_by_path(change.path)
                    except Exception:
                        pass
                write_batch = []
                for change in added_or_modified:
                    full_path = root / change.path
                    if not full_path.exists():
                        continue
                    try:
                        # max_workers=1 for single-file parsing (no benefit from parallelism)
                        single_graph = indexer.build_graph(
                            root=str(root),
                            file_list=[str(full_path)],
                            max_workers=1,
                            max_file_size_kb=max_file_size_kb,
                            verbose=options.verbose,
                            index_id=run_uuid,
                        )
                    except Exception as exc:
                        LOGGER.warning("patch_file_parse_failed", path=change.path, error=str(exc))
                        continue

                    file_rel = change.path
                    entities_list = [
                        e.to_dict() for e in single_graph.entities.values()
                    ]
                    rels_list = [r.to_dict() for r in single_graph.relationships]

                    bsg_map_single = BSGMap.build(single_graph, str(root))
                    file_entities = bsg_map_single._by_file.get(file_rel)
                    if not file_entities:
                        file_entities = entities_list

                    t_prep_0 = time.monotonic()
                    agent_entities = []
                    for e in file_entities:
                        e_dict = e.to_dict(view="agent") if hasattr(e, "to_dict") else e
                        agent_entities.append({
                            "id": e_dict.get("id"),
                            "name": e_dict.get("name"),
                            "type": e_dict.get("type") or e_dict.get("entity_type"),
                            "start_line": e_dict.get("start_line"),
                            "end_line": e_dict.get("end_line"),
                            "signature": e_dict.get("signature"),
                            "content_hash": e.content_hash if hasattr(e, "content_hash") else e_dict.get("content_hash", ""),
                        })

                    delta_entities = []
                    for e in file_entities:
                        e_dict = e.to_dict(view="storage") if hasattr(e, "to_dict") else e
                        delta_entities.append({
                            "id": e_dict.get("id"),
                            "raw_content": e_dict.get("raw_content"),
                            "syntax_glue": {
                                "leading_whitespace": e_dict.get("leading_whitespace", ""),
                                "trailing_whitespace": e_dict.get("trailing_whitespace", ""),
                            },
                            "raw_bytes": e_dict.get("raw_bytes"),
                            "start_byte": e_dict.get("start_byte"),
                            "end_byte": e_dict.get("end_byte"),
                            "parent_id": e_dict.get("parent_id"),
                            "ast_node_type": e_dict.get("ast_node_type"),
                            "children_order": e_dict.get("children_order"),
                            "metadata": e_dict.get("metadata"),
                            "content_hash": e_dict.get("content_hash"),
                        })

                    agent_view_data = {"entities": agent_entities}
                    storage_delta_data = {
                        "entities": delta_entities,
                    }
                    relationships_data = rels_list

                    content_hash = change.new_hash or compute_file_hash(full_path) or ""
                    write_batch.append({
                        "file_path": file_rel,
                        "content_hash": content_hash,
                        "agent_view_data": agent_view_data,
                        "storage_delta_data": storage_delta_data,
                        "relationships_data": relationships_data,
                    })
                    t_batch_prep_ms += (time.monotonic() - t_prep_0) * 1000
                    new_entity_count += len(entities_list)
                    new_rel_count += len(rels_list)

                    # Flush batch when it reaches 50 files
                    if len(write_batch) >= 50:
                        t_write_0 = time.monotonic()
                        db.insert_file_artifacts_batch(run_internal_id, write_batch)
                        t_batch_write_ms += (time.monotonic() - t_write_0) * 1000
                        write_batch = []

                    # Fetch base-run entities for this file and diff
                    if base_run_internal_id is not None:
                        old_entities = db.get_agent_entities_for_file(base_run_internal_id, file_rel) or []
                        from batho.modules.graph.diff_engine.node_diff import diff_file_nodes
                        node_diffs = diff_file_nodes(old_entities, agent_entities, file_rel)
                        if node_diffs:
                            db.record_file_changelog(run_internal_id, base_run_internal_id, node_diffs)
                            for diff in node_diffs:
                                if diff.change_kind == "added":
                                    nodes_added += 1
                                elif diff.change_kind == "removed":
                                    nodes_removed += 1
                                elif diff.change_kind == "modified":
                                    nodes_modified += 1
                                elif diff.change_kind == "renamed":
                                    nodes_renamed += 1

                # Flush any remaining files in batch
                if write_batch:
                    t_write_0 = time.monotonic()
                    db.insert_file_artifacts_batch(run_internal_id, write_batch)
                    t_batch_write_ms += (time.monotonic() - t_write_0) * 1000

        # --- Update file tracking ---
        for change in deleted:
            db.delete_file_tracking(change.path)
            # Fetch base-run entities for this deleted file and record their removal
            if base_run_internal_id is not None:
                old_entities = db.get_agent_entities_for_file(base_run_internal_id, change.path) or []
                if old_entities:
                    from batho.modules.graph.diff_engine.node_diff import diff_file_nodes
                    node_diffs = diff_file_nodes(old_entities, [], change.path)
                    if node_diffs:
                        db.record_file_changelog(run_internal_id, base_run_internal_id, node_diffs)
                        for diff in node_diffs:
                            if diff.change_kind == "removed":
                                nodes_removed += 1

        for change in added_or_modified:
            full_path = root / change.path
            if full_path.exists():
                try:
                    stat = full_path.stat()
                    content_hash = change.new_hash or compute_file_hash(full_path) or ""
                    db.upsert_file_tracking([{
                        "file_path": change.path,
                        "content_hash": content_hash,
                        "mtime": stat.st_mtime,
                        "mtime_ns": getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1e9)),
                        "inode": getattr(stat, "st_ino", None),
                        "size": stat.st_size,
                        "is_indexed": 1,
                        "last_run_id": run_uuid,
                    }])
                except OSError:
                    pass

        # --- Resolve dangling cross-file references via SQL JOIN ---
        try:
            resolved_joined = db.resolve_dangling_references(run_internal_id)
            LOGGER.info("cross_file_relationships_resolved_via_sql_join", count=resolved_joined)
        except Exception as exc:
            LOGGER.warning("cross_file_relationships_sql_join_failed", error=str(exc))

        # --- Complete run ---
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        with db.connection(read_only=True) as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM file_artifacts WHERE run_id = ?",
                (run_internal_id,),
            ).fetchone()
            file_count = row["cnt"] if row else 0
            entity_row = conn.execute(
                "SELECT COUNT(*) as cnt FROM query_entities WHERE run_id = ?",
                (run_internal_id,),
            ).fetchone()
            rel_row = conn.execute(
                "SELECT COUNT(*) as cnt FROM query_relationships WHERE run_id = ?",
                (run_internal_id,),
            ).fetchone()
            total_entities = entity_row["cnt"] if entity_row else 0
            total_rels = rel_row["cnt"] if rel_row else 0

        db.complete_run(
            run_uuid,
            entity_count=total_entities,
            rel_count=total_rels,
            file_count=file_count,
            duration_ms=elapsed_ms,
        )

        # --- Finalize Run Artifacts ---
        from batho.orchestrator.build import _compute_run_metrics
        metrics = _compute_run_metrics(db, run_internal_id, root)
        
        telemetry = {
            "duration_ms": elapsed_ms,
            "batch_prep_ms": t_batch_prep_ms,
            "batch_write_ms": t_batch_write_ms,
            "files_indexed": file_count,
            "entity_count": metrics["context_overview"]["total_entities"],
            "rel_count": metrics["context_overview"]["total_relationships"],
            "git_commit": git_commit,
            "git_branch": git_branch,
        }
        
        total_base_files = len(known_tracking)
        files_changed = len(changes)
        churn_pct = (files_changed / total_base_files * 100.0) if total_base_files > 0 else 0.0
        churn_pct = float(min(max(churn_pct, 0.0), 100.0))
        
        delta_stats = {
            "nodes_added": nodes_added,
            "nodes_removed": nodes_removed,
            "nodes_modified": nodes_modified,
            "nodes_renamed": nodes_renamed,
            "files_changed": files_changed,
            "files_added": sum(1 for c in changes if c.change_type == FileChangeType.ADDED),
            "files_deleted": sum(1 for c in changes if c.change_type == FileChangeType.DELETED),
            "churn_pct": churn_pct,
            "base_run_uuid": base_run_uuid or None,
        }
        
        artifact_blobs_cfg = cfg.get("artifact_blobs", {})

        db.finalize_run_artifacts(
            run_internal_id,
            artifacts={
                "context_overview": metrics["context_overview"],
                "telemetry_metrics": telemetry,
                "structural_metrics": metrics["structural_metrics"],
                "security_audit": {
                    "schema_version": "interception-stats.v1",
                    "plugins": {},
                },
                "artifact_payload": metrics["artifact_payload"],
                "delta_stats": delta_stats,
            },
            blob_config=artifact_blobs_cfg
        )

        LOGGER.info(
            "patch_complete",
            run_id=run_uuid,
            files=file_count,
            changes=len(changes),
            duration_ms=elapsed_ms,
        )

        # Prune file changelog
        file_changelog_max_runs = cfg.get("indexer", {}).get("file_changelog_max_runs", 100)
        db.prune_file_changelog(max_runs=file_changelog_max_runs)

        return PatchResult(
            success=True,
            run_id=run_uuid,
            base_snapshot_id=base_run_uuid,
            new_snapshot_id="",
            changes_applied=len(changes),
            added=sum(1 for c in changes if c.change_type == FileChangeType.ADDED),
            modified=sum(1 for c in changes if c.change_type == FileChangeType.MODIFIED),
            deleted=sum(1 for c in changes if c.change_type == FileChangeType.DELETED),
            entity_count=new_entity_count,
            relationship_count=new_rel_count,
            duration_ms=elapsed_ms,
            nodes_added=nodes_added,
            nodes_removed=nodes_removed,
            nodes_modified=nodes_modified,
            nodes_renamed=nodes_renamed,
        )

    except Exception as e:
        # Mark run as failed on any unhandled exception
        LOGGER.error("patch_unhandled_exception", error=str(e))
        if run_uuid and db is not None:
            try:
                db.fail_run(run_uuid, error_message=str(e))
            except Exception:
                pass  # Best effort
        return PatchResult(
            success=False,
            run_id=run_uuid,
            base_snapshot_id=base_run_uuid,
            warnings=[f"Unhandled exception: {e}"],
        )
