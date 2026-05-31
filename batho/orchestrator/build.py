"""Orchestrator for `batho build` — full index build for new working directories.

Creates an `artifact_<dirname>.batho` SQLite database with: code graph, BSG map, context outputs,
baseline snapshot, and file tracking records. If the artifact database already exists,
exits early directing the user to `batho patch`.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from batho.core.config import get_config_cached, set_active_root
from batho.utils.hash import _is_binary, compute_file_hash
from batho.utils.logging import get_logger
from batho.modules.graph.incremental import get_head_commit, get_current_branch, is_git_repo

LOGGER = get_logger(__name__, component="orchestrator.build")


# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------


@dataclass
class BuildOptions:
    """Configuration for a build run."""

    root: Path
    force_full: bool = False
    verbose: bool = False
    max_workers: int | None = None
    max_file_size_kb: int | None = None


@dataclass
class BuildResult:
    """Outcome of a build run."""

    success: bool
    run_id: str = ""
    entity_count: int = 0
    relationship_count: int = 0
    file_count: int = 0
    bsg_file_count: int = 0
    snapshot_id: str = ""
    duration_ms: int = 0
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _generate_run_id() -> str:
    """Generate a unique run ID (timestamp + short uuid)."""
    ts = int(time.time())
    short = uuid.uuid4().hex[:8]
    return f"build_{ts}_{short}"


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


def _estimate_batch_size_bytes(batch_item: dict) -> int:
    """Estimate the size of a batch item in bytes for persistence."""
    if batch_item.get("_use_precompiled"):
        return (
            len(batch_item.get("agent_blob", b""))
            + len(batch_item.get("storage_blob", b""))
            + len(batch_item.get("rels_blob", b""))
        )
    else:
        try:
            import orjson
            dumps = orjson.dumps
        except ImportError:
            import json
            dumps = lambda x: json.dumps(x).encode("utf-8")
        
        size = 0
        if "agent_view_data" in batch_item:
            size += len(dumps(batch_item["agent_view_data"]))
        if "storage_delta_data" in batch_item:
            size += len(dumps(batch_item["storage_delta_data"]))
        if "relationships_data" in batch_item:
            size += len(dumps(batch_item["relationships_data"]))
        return size


def run_build(options: BuildOptions) -> BuildResult:
    """Execute a full index build for a working directory.

    If the database already exists and force_full is False, returns early
    with success=True and a warning indicating patch should be used.
    """
    from batho.modules.storage.sqlite_registry.engine import resolve_db_path
    t0 = time.monotonic()
    root = options.root.resolve()
    
    if not root.exists():
        return BuildResult(
            success=False,
            warnings=[f"Repository root does not exist: {root}"],
        )
    if not root.is_dir():
        return BuildResult(
            success=False,
            warnings=[f"Repository root is not a directory: {root}"],
        )

    set_active_root(root)
    db_path = resolve_db_path(root)

    # --- Guard: existing database ---
    if db_path.exists() and not options.force_full:
        msg = (
            f"Database already exists at {db_path}.\n"
            f"To update incrementally, run: batho patch --root {root}\n"
            f"To force a full rebuild, run: batho build --root {root} --full"
        )
        LOGGER.info("build_skipped_existing", root=str(root))
        return BuildResult(
            success=True,
            warnings=["already_built", msg],
        )

    if options.force_full and db_path.exists():
        LOGGER.info("build_force_full_clearing", path=str(db_path))
        db_path.unlink()

    # --- Load config ---
    cfg = get_config_cached()
    indexer_cfg = cfg.get("indexer", {})
    bsg_cfg = cfg.get("bsg", {})

    max_file_size_kb = options.max_file_size_kb or indexer_cfg.get("max_file_size_kb", 500)

    # Inherit bidirectional settings directly from config without hardcoding
    bsg_cfg = dict(bsg_cfg)
    bidi_cfg = dict(bsg_cfg.get("bidirectional", {}))
    include_gaps_flag = bidi_cfg.get("include_gaps", False)
    bidi_cfg["include_gaps"] = include_gaps_flag
    bsg_cfg["bidirectional"] = bidi_cfg

    cache_cfg = dict(bsg_cfg.get("cache", {}))
    cache_cfg["enabled"] = True
    cache_cfg["path"] = str(db_path)
    bsg_cfg["cache"] = cache_cfg

    if options.max_workers:
        parallel_cfg = dict(bsg_cfg.get("parallel", {}))
        parallel_cfg["max_workers"] = options.max_workers
        bsg_cfg["parallel"] = parallel_cfg

    # --- Initialize database ---
    from batho.modules.storage.sqlite_registry.engine import BathoDatabase

    db = BathoDatabase(db_path, repo_root=root)
    run_uuid = _generate_run_id()
    git_commit: str | None = None
    git_branch: str | None = None
    if is_git_repo(root):
        git_commit = get_head_commit(root)
        git_branch = get_current_branch(root)
    run_internal_id = db.create_run(
        run_uuid,
        root_path=str(root),
        git_commit=git_commit,
        git_branch=git_branch,
    )
    run_id = run_uuid
    LOGGER.info("build_started", root=str(root), run_id=run_id)
    from batho.modules.graph.builder.codegraph import CodeGraphIndexer

    # Drop query table indexes for bulk write performance
    try:
        db.drop_query_indexes()
    except Exception as exc:
        LOGGER.warning("failed_to_drop_query_indexes", error=str(exc))

    t_batch_prep_ms = 0.0
    t_batch_write_ms = 0.0
    precompiled_write_batch = []
    precompiled_current_batch_bytes = 0

    # --- Dependency Indexing (CDEU) ---
    from batho.modules.dependency import build_dependency_index
    from batho.modules.extraction.scope_manager import ScopeManager

    dep_scope_manager = ScopeManager()
    dep_cfg = cfg.get("dependency", {})
    if isinstance(dep_cfg, BaseModel):
        dep_cfg = dep_cfg.model_dump()

    if dep_cfg.get("enabled", True):
        t_dep_0 = time.monotonic()
        dep_stats = build_dependency_index(
            root=root,
            scope_manager=dep_scope_manager,
            cfg=dep_cfg,
            cache_dir=cfg.get("paths", {}).get("cache_dir"),
        )
        dep_duration_ms = (time.monotonic() - t_dep_0) * 1000
        LOGGER.info(
            "dependency_index_complete",
            manifests=dep_stats.manifests_found,
            deps=dep_stats.deps_declared,
            symbols=dep_stats.symbols_indexed,
            duration_ms=round(dep_duration_ms, 2),
        )

    def write_precompiled_callback(file_rel: str, blob_data: dict) -> None:
        nonlocal precompiled_write_batch, precompiled_current_batch_bytes
        nonlocal t_batch_prep_ms, t_batch_write_ms
        t_prep_0 = time.monotonic()
        
        item = {
            "file_path": file_rel,
            "content_hash": blob_data.get("content_hash", ""),
            "agent_blob": blob_data.get("agent_blob", b""),
            "storage_blob": blob_data.get("storage_blob", b""),
            "rels_blob": blob_data.get("rels_blob", b""),
            "_use_precompiled": True,
        }
        precompiled_write_batch.append(item)
        precompiled_current_batch_bytes += (
            len(item["agent_blob"]) + len(item["storage_blob"]) + len(item["rels_blob"])
        )
        t_batch_prep_ms += (time.monotonic() - t_prep_0) * 1000

        batch_size = cfg.get("persistence", {}).get("batch_size", 500)
        batch_bytes_threshold = cfg.get("persistence", {}).get("batch_bytes_threshold", 15_728_640)
        if len(precompiled_write_batch) >= batch_size or precompiled_current_batch_bytes >= batch_bytes_threshold:
            t_write_0 = time.monotonic()
            precompiled_file_paths = [b["file_path"] for b in precompiled_write_batch]
            resolved_ids = db.bulk_get_or_create_string_ids(precompiled_file_paths)
            precompiled_batch = []
            for b in precompiled_write_batch:
                file_id = resolved_ids[b["file_path"]]
                precompiled_batch.append({
                    "file_id": file_id,
                    "content_hash": b["content_hash"],
                    "agent_blob": b["agent_blob"],
                    "storage_blob": b["storage_blob"],
                    "rels_blob": b.get("rels_blob", b""),
                })
            db._insert_precompiled_batch(run_internal_id, precompiled_batch)
            t_batch_write_ms += (time.monotonic() - t_write_0) * 1000
            precompiled_write_batch.clear()
            precompiled_current_batch_bytes = 0

    with CodeGraphIndexer(cache_path=str(db_path), root=str(root)) as indexer:
        graph = indexer.build_graph(
            root=str(root),
            max_workers=options.max_workers or 0,
            max_file_size_kb=max_file_size_kb,
            verbose=options.verbose,
            index_id=run_id,
            ast_cache_enabled=True,
            include_gaps=include_gaps_flag,
            write_callback=write_precompiled_callback,
            external_scope_manager=dep_scope_manager,
        )

        entity_count = len(graph.entities)
        rel_count = len(graph.relationships)

        if indexer.build_stats["files_parsed"] + indexer.build_stats["files_cached"] == 0:
            LOGGER.warning("build_no_entities", root=str(root))
            db.fail_run(run_id, error_message="No indexable files found")
            return BuildResult(
                success=False,
                run_id=run_id,
                warnings=["No indexable files found in " + str(root)],
                duration_ms=int((time.monotonic() - t0) * 1000),
            )

        LOGGER.info(
            "build_graph_complete",
            entities=entity_count,
            relationships=rel_count,
        )

        # Bidirectional rules pass removed to avoid main-thread loading latency
        bidi_stats = None


        # --- Load opaque snapshots for files the extractor engine could not parse ---
        from batho.core.schemas import FileSnapshot

        opaque_snapshots: list[FileSnapshot] = []
        try:
            for _abs_path, rel in indexer.get_unindexed_files():
                # Safe access to file snapshots using the public method or fallback
                if hasattr(indexer, "get_file_snapshot"):
                    snap = indexer.get_file_snapshot(_abs_path) or indexer.get_file_snapshot(rel)
                elif hasattr(indexer, "_cache") and indexer._cache is not None:
                    snap = indexer._cache.get_file_snapshot(_abs_path) or indexer._cache.get_file_snapshot(rel)
                else:
                    snap = None
                if snap is not None:
                    opaque_snapshots.append(snap)
        except Exception as exc:
            LOGGER.warning("build_opaque_snapshots_failed", error=str(exc))

        # --- Build BSG map ---
        from batho.modules.compression.bsg_map import BSGMap
        from batho.modules.storage.sqlite_registry.engine import _minify_graph_payload

        bsg_map = BSGMap.build(graph, str(root), opaque_snapshots=opaque_snapshots)
        bsg_file_count = len(bsg_map._by_file)
        LOGGER.info("build_bsg_complete", files=bsg_file_count)

        # Flush any remaining precompiled files from the callback buffer
        if precompiled_write_batch:
            t_write_0 = time.monotonic()
            precompiled_file_paths = [b["file_path"] for b in precompiled_write_batch]
            resolved_ids = db.bulk_get_or_create_string_ids(precompiled_file_paths)
            precompiled_batch = []
            for b in precompiled_write_batch:
                file_id = resolved_ids[b["file_path"]]
                precompiled_batch.append({
                    "file_id": file_id,
                    "content_hash": b["content_hash"],
                    "agent_blob": b["agent_blob"],
                    "storage_blob": b["storage_blob"],
                    "rels_blob": b.get("rels_blob", b""),
                })
            db._insert_precompiled_batch(run_internal_id, precompiled_batch)
            t_batch_write_ms += (time.monotonic() - t_write_0) * 1000
            precompiled_write_batch.clear()
            precompiled_current_batch_bytes = 0

        # Check if indexer has precompiled blobs (from optimized worker)
        precompiled_blobs_abs = getattr(indexer, "_precompiled_blobs", {})
        precompiled_blobs = {}
        root_str = str(root)
        
        for abs_path, blob_data in precompiled_blobs_abs.items():
            rel = abs_path[len(root_str)+1:] if abs_path.startswith(root_str) else abs_path
            precompiled_blobs[rel] = blob_data

        # Identify all indexed and graph files
        indexed_rels = []
        if indexer is not None and getattr(indexer, "_indexed_files", None) is not None:
            for file_path in indexer._indexed_files:
                rel = file_path[len(root_str)+1:] if file_path.startswith(root_str) else file_path
                indexed_rels.append(rel)

        all_file_paths = set(bsg_map._by_file.keys()) | set(indexed_rels) | set(precompiled_blobs.keys())
        legacy_files = all_file_paths - set(precompiled_blobs.keys())

        if legacy_files:
            from collections import defaultdict
            entities_by_file = defaultdict(list)
            for entity in graph.entities.values():
                filepath = entity.file
                rel = filepath[len(root_str)+1:] if filepath.startswith(root_str) else filepath
                if rel in legacy_files:
                    entities_by_file[rel].append(entity.to_dict())

            rels_by_source_file = defaultdict(list)
            for rel in graph.relationships:
                source_ent = graph.get_entity(rel.source_id)
                rel_file = source_ent.file if source_ent else rel.source_id
                rel_file_rel = rel_file[len(root_str)+1:] if rel_file.startswith(root_str) else rel_file
                if rel_file_rel in legacy_files:
                    rels_by_source_file[rel_file_rel].append(rel.to_dict())

            legacy_write_batch = []
            legacy_current_batch_bytes = 0
            for file_rel in legacy_files:
                t_prep_0 = time.monotonic()
                # Fallback: build from graph entities (legacy path)
                file_entities = bsg_map._by_file.get(file_rel)
                if not file_entities:
                    file_entities = entities_by_file.get(file_rel, [])

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
                relationships_data = rels_by_source_file.get(file_rel, [])

                content_hash = compute_file_hash(root / file_rel) or ""
                item = {
                    "file_path": file_rel,
                    "content_hash": content_hash,
                    "agent_view_data": agent_view_data,
                    "storage_delta_data": storage_delta_data,
                    "relationships_data": relationships_data,
                }
                legacy_write_batch.append(item)
                t_batch_prep_ms += (time.monotonic() - t_prep_0) * 1000
                legacy_current_batch_bytes += _estimate_batch_size_bytes(item)

                batch_size = cfg.get("persistence", {}).get("batch_size", 500)
                batch_bytes_threshold = cfg.get("persistence", {}).get("batch_bytes_threshold", 15_728_640)
                if len(legacy_write_batch) >= batch_size or legacy_current_batch_bytes >= batch_bytes_threshold:
                    t_write_0 = time.monotonic()
                    db.insert_file_artifacts_batch(run_internal_id, legacy_write_batch)
                    t_batch_write_ms += (time.monotonic() - t_write_0) * 1000
                    legacy_write_batch.clear()
                    legacy_current_batch_bytes = 0

            if legacy_write_batch:
                t_write_0 = time.monotonic()
                db.insert_file_artifacts_batch(run_internal_id, legacy_write_batch)
                t_batch_write_ms += (time.monotonic() - t_write_0) * 1000

        # Recreate search indexes for queries
        try:
            db.recreate_query_indexes()
        except Exception as exc:
            LOGGER.warning("failed_to_recreate_query_indexes", error=str(exc))

        LOGGER.info("batch_performance_breakdown", prep_ms=round(t_batch_prep_ms, 2), write_ms=round(t_batch_write_ms, 2))

        # --- Resolve dangling cross-file references via SQL JOIN ---
        try:
            t_join_0 = time.monotonic()
            resolved_joined = db.resolve_dangling_references(run_internal_id)
            LOGGER.info("cross_file_relationships_resolved_via_sql_join", count=resolved_joined, time_ms=round((time.monotonic() - t_join_0) * 1000, 2))
        except Exception as exc:
            LOGGER.warning("cross_file_relationships_sql_join_failed", error=str(exc))

        # --- Persist file tracking ---
        file_tracking_records = _build_file_tracking(graph, root, indexer, run_id=run_id)
        if file_tracking_records:
            db.upsert_file_tracking(file_tracking_records)

        if indexer is not None:
            indexer.clear_unindexed_files()

        # --- Complete run ---
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        db.complete_run(
            run_uuid,
            entity_count=entity_count,
            rel_count=rel_count,
            file_count=bsg_file_count,
            duration_ms=elapsed_ms,
        )

        # --- Finalize Run Artifacts ---
        metrics = _compute_run_metrics(db, run_internal_id, root)
        telemetry = {
            "duration_ms": elapsed_ms,
            "batch_prep_ms": t_batch_prep_ms,
            "batch_write_ms": t_batch_write_ms,
            "files_indexed": bsg_file_count,
            "entity_count": entity_count,
            "rel_count": rel_count,
            "git_commit": git_commit,
            "git_branch": git_branch,
        }
        security_audit_val = None
        bsg_build_stats = getattr(indexer, "build_stats", {})
        if bsg_build_stats:
            security_audit_val = bsg_build_stats.get("security_audit")

        # Bidirectional rule merging removed (all rules evaluated on parallel workers)

        if security_audit_val is None:
            security_audit_val = {
                "schema_version": "interception-stats.v1",
                "plugins": {},
            }

        artifact_blobs_cfg = cfg.get("artifact_blobs", {})

        db.finalize_run_artifacts(
            run_internal_id,
            artifacts={
                "context_overview": metrics["context_overview"],
                "telemetry_metrics": telemetry,
                "structural_metrics": metrics["structural_metrics"],
                "security_audit": security_audit_val,
                "artifact_payload": metrics["artifact_payload"],
                "delta_stats": None,
            },
            blob_config=artifact_blobs_cfg
        )

        try:
            db.cleanup_query_tables()
        except Exception as exc:
            LOGGER.warning("failed_to_cleanup_query_tables", error=str(exc))

        LOGGER.info(
            "build_complete",
            run_id=run_id,
            entities=entity_count,
            relationships=rel_count,
            files=bsg_file_count,
            duration_ms=elapsed_ms,
        )

        return BuildResult(
            success=True,
            run_id=run_id,
            entity_count=entity_count,
            relationship_count=rel_count,
            file_count=bsg_file_count,
            bsg_file_count=bsg_file_count,
            snapshot_id="",
            duration_ms=elapsed_ms,
        )


# ---------------------------------------------------------------------------
# Context builders
# ---------------------------------------------------------------------------


def _compute_run_metrics(db, run_internal_id: int, root: Path) -> dict:
    # Compute metrics via efficient SQL queries directly in SQLite
    with db.connection(read_only=True) as conn:
        # 1. Total entities & relationships
        total_entities = conn.execute(
            "SELECT COUNT(*) FROM query_entities WHERE run_id = ?", (run_internal_id,)
        ).fetchone()[0]
        
        total_relationships = conn.execute(
            "SELECT COUNT(*) FROM query_relationships WHERE run_id = ?", (run_internal_id,)
        ).fetchone()[0]
        
        # 2. Files
        files_rows = conn.execute(
            "SELECT val FROM string_dict WHERE id IN (SELECT file_id FROM file_artifacts WHERE run_id = ?)",
            (run_internal_id,)
        ).fetchall()
        file_paths = [r["val"] for r in files_rows]
        total_files = len(file_paths)
        
        # 3. Entity types distribution
        entity_types_rows = conn.execute(
            "SELECT entity_type, COUNT(*) as c FROM query_entities WHERE run_id = ? GROUP BY entity_type ORDER BY c DESC",
            (run_internal_id,)
        ).fetchall()
        entity_types = {r["entity_type"]: r["c"] for r in entity_types_rows}
        
        # 4. File distribution (top 100)
        file_dist_rows = conn.execute(
            "SELECT file_path, COUNT(*) as c FROM query_entities WHERE run_id = ? GROUP BY file_path ORDER BY c DESC LIMIT 100",
            (run_internal_id,)
        ).fetchall()
        file_distribution = [{"file_path": r["file_path"], "entity_count": r["c"]} for r in file_dist_rows]
        
        # 5. File categories (computed in Python, fast for < 1000 files)
        from collections import defaultdict
        by_ext = defaultdict(list)
        for fp in file_paths:
            ext = Path(fp).suffix.lower() or "(no extension)"
            by_ext[ext].append(fp)
            
        categories = [
            {"extension": ext, "files": sorted(files), "count": len(files)}
            for ext, files in sorted(by_ext.items(), key=lambda x: -len(x[1]))
        ]
        
        # 6. Top coupled files (SQL CTE)
        top_coupled_rows = conn.execute(
            """
            WITH rel_files AS (
                SELECT 
                    e_src.file_path AS src_file,
                    e_tgt.file_path AS tgt_file
                FROM query_relationships r
                LEFT JOIN query_entities e_src ON r.source_key = e_src.entity_key AND r.run_id = e_src.run_id
                LEFT JOIN query_entities e_tgt ON r.target_key = e_tgt.entity_key AND r.run_id = e_tgt.run_id
                WHERE r.run_id = ?
            ),
            coupled_files AS (
                SELECT src_file AS file_path FROM rel_files WHERE src_file IS NOT NULL AND tgt_file IS NOT NULL AND src_file != tgt_file
                UNION ALL
                SELECT tgt_file AS file_path FROM rel_files WHERE src_file IS NOT NULL AND tgt_file IS NOT NULL AND src_file != tgt_file
            )
            SELECT file_path, COUNT(*) AS coupling 
            FROM coupled_files 
            GROUP BY file_path 
            ORDER BY coupling DESC 
            LIMIT 50
            """,
            (run_internal_id,)
        ).fetchall()
        top_coupled = [{"file_path": r["file_path"], "coupling": r["coupling"]} for r in top_coupled_rows]
        
        # 7. Top 200 entities
        top_entities_rows = conn.execute(
            "SELECT entity_name, entity_type, fqn, file_path, line_number FROM query_entities WHERE run_id = ? ORDER BY COALESCE(fqn, entity_name) LIMIT 200",
            (run_internal_id,)
        ).fetchall()
        top_entities = [
            {
                "name": r["entity_name"],
                "type": r["entity_type"],
                "fqn": r["fqn"],
                "file": r["file_path"],
                "start_line": r["line_number"],
            }
            for r in top_entities_rows
        ]
        
        # 8. Relationship count per file (originating)
        rel_counts_rows = conn.execute(
            """
            SELECT e.file_path, COUNT(*) as c
            FROM query_relationships r
            JOIN query_entities e ON r.source_key = e.entity_key AND r.run_id = e.run_id
            WHERE r.run_id = ?
            GROUP BY e.file_path
            """,
            (run_internal_id,)
        ).fetchall()
        rel_count_per_file = {r["file_path"]: r["c"] for r in rel_counts_rows}
        
    context_overview = {
        "total_entities": total_entities,
        "total_relationships": total_relationships,
        "total_files": total_files,
        "entity_types": entity_types,
        "file_distribution": file_distribution,
        "categories": categories,
    }
    
    structural_metrics = {
        "entity_type_distribution": entity_types,
        "top_coupled_files": top_coupled,
    }
    
    artifact_payload = {
        "entities": top_entities,
        "rel_count_per_file": rel_count_per_file,
    }
    
    return {
        "context_overview": context_overview,
        "structural_metrics": structural_metrics,
        "artifact_payload": artifact_payload,
    }



def _build_file_tracking(graph: Any, root: Path, indexer: Any = None, *, run_id: str = "") -> list[dict[str, Any]]:
    """Build file tracking records from the indexed graph."""
    import os

    seen: set[str] = set()
    records: list[dict[str, Any]] = []

    # Map absolute paths in indexer._precompiled_blobs to relative keys
    precompiled_blobs = {}
    if indexer is not None:
        precompiled_blobs_abs = getattr(indexer, "_precompiled_blobs", {})
        for abs_path, blob_data in precompiled_blobs_abs.items():
            try:
                rel = str(Path(abs_path).relative_to(root))
            except ValueError:
                rel = abs_path
            precompiled_blobs[rel] = blob_data

    if indexer is not None and getattr(indexer, "_indexed_files", None) is not None:
        for file_path in indexer._indexed_files:
            if not file_path:
                continue
            try:
                rel = str(Path(file_path).relative_to(root))
            except ValueError:
                rel = str(file_path)

            if rel in seen:
                continue
            seen.add(rel)

            full_path = root / rel
            if not full_path.exists():
                continue

            try:
                stat = full_path.stat()
                content_hash = ""
                if rel in precompiled_blobs:
                    content_hash = precompiled_blobs[rel].get("content_hash", "")
                if not content_hash:
                    content_hash = compute_file_hash(full_path) or ""
                records.append({
                    "file_path": rel,
                    "content_hash": content_hash,
                    "mtime": stat.st_mtime,
                    "mtime_ns": getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1e9)),
                    "inode": getattr(stat, "st_ino", None),
                    "size": stat.st_size,
                    "is_indexed": 1,
                    "last_run_id": run_id or None,
                    "encoding": "utf-8",
                })
            except OSError:
                continue

    for entity in graph.entities.values():
        file_path = entity.file
        if not file_path:
            continue
        try:
            rel = str(Path(file_path).relative_to(root))
        except ValueError:
            rel = file_path

        if rel in seen:
            continue
        seen.add(rel)

        full_path = root / rel
        if not full_path.exists():
            continue

        try:
            stat = full_path.stat()
            content_hash = ""
            if rel in precompiled_blobs:
                content_hash = precompiled_blobs[rel].get("content_hash", "")
            if not content_hash:
                content_hash = compute_file_hash(full_path) or ""
            records.append({
                "file_path": rel,
                "content_hash": content_hash,
                "mtime": stat.st_mtime,
                "mtime_ns": getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1e9)),
                "inode": getattr(stat, "st_ino", None),
                "size": stat.st_size,
                "is_indexed": 1,
                "last_run_id": run_id or None,
                "encoding": "utf-8",  # All indexed files are text
            })
        except OSError:
            continue

    if indexer is not None:
        for _abs_path, rel in indexer.get_unindexed_files():
            if rel in seen:
                continue
            seen.add(rel)
            full_path = root / rel
            if not full_path.exists():
                continue
            try:
                stat = full_path.stat()
                content_hash = compute_file_hash(full_path) or ""
                # Determine encoding for opaque files
                encoding = "utf-8"
                try:
                    content = full_path.read_bytes()
                    if _is_binary(content):
                        encoding = "binary"
                except Exception:
                    pass  # Default to utf-8 if read fails
                records.append({
                    "file_path": rel,
                    "content_hash": content_hash,
                    "mtime": stat.st_mtime,
                    "mtime_ns": getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1e9)),
                    "inode": getattr(stat, "st_ino", None),
                    "size": stat.st_size,
                    "is_indexed": 0,
                    "last_run_id": run_id or None,
                    "encoding": encoding,
                })
            except OSError:
                continue

    return records
