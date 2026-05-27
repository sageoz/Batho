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

    # Override BSG config for optimized build defaults
    bsg_cfg = dict(bsg_cfg)
    bidi_cfg = dict(bsg_cfg.get("bidirectional", {}))
    bidi_cfg["include_gaps"] = True  # always include gaps
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

    with CodeGraphIndexer(cache_path=str(db_path), root=str(root)) as indexer:
        graph = indexer.build_graph(
            root=str(root),
            max_workers=options.max_workers or 0,
            max_file_size_kb=max_file_size_kb,
            verbose=options.verbose,
            index_id=run_id,
            ast_cache_enabled=True,
        )

        entity_count = len(graph.entities)
        rel_count = len(graph.relationships)

        if entity_count == 0:
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

        # --- Apply BSG plugin rules ---
        rules_cfg = cfg.get("rules", {})
        bsg_summary = None
        if rules_cfg:
            try:
                from batho.modules.compression.rules import apply_rule_plugins

                bsg_summary = apply_rule_plugins(
                    graph=graph,
                    root_path=root,
                    rules_config=rules_cfg,
                    logger=LOGGER,
                )
            except Exception as exc:
                LOGGER.warning("build_rules_failed", error=str(exc))

        # --- Load opaque snapshots for files the extractor engine could not parse ---
        from batho.core.schemas import FileSnapshot

        opaque_snapshots: list[FileSnapshot] = []
        try:
            for _abs_path, rel in indexer.get_unindexed_files():
                # NOTE: Accessing private _cache attribute breaks encapsulation.
                # Consider adding get_file_snapshot() public method to CodeGraphIndexer
                # or exposing via CodeGraphIndexer.get_unindexed_files_with_snapshots().
                snap = indexer._cache.get_file_snapshot(_abs_path) or indexer._cache.get_file_snapshot(rel)
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

        # --- Group entities/relationships by file and persist as compressed blobs ---
        from collections import defaultdict
        t_group_start = time.monotonic()
        entities_by_file: dict[str, list[Any]] = defaultdict(list)
        for entity in graph.entities.values():
            try:
                rel = str(Path(entity.file).relative_to(root))
            except ValueError:
                rel = entity.file
            entities_by_file[rel].append(entity.to_dict())

        rels_by_source_file: dict[str, list[Any]] = defaultdict(list)
        for rel in graph.relationships:
            source_ent = graph.get_entity(rel.source_id)
            if source_ent:
                # Relationship source is an entity - use entity's file
                try:
                    rel_file = str(Path(source_ent.file).relative_to(root))
                except ValueError:
                    rel_file = source_ent.file
            else:
                # Relationship source is not an entity (e.g., file-level import)
                # Treat source_id as a file path directly
                try:
                    rel_file = str(Path(rel.source_id).relative_to(root))
                except ValueError:
                    rel_file = rel.source_id
            rels_by_source_file[rel_file].append(rel.to_dict())

        all_file_paths = set(entities_by_file.keys()) | set(rels_by_source_file.keys())
        write_batch = []
        t_batch_prep_ms = 0.0
        t_batch_write_ms = 0.0

        for file_rel in all_file_paths:
            t_prep_0 = time.monotonic()
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
            write_batch.append({
                "file_path": file_rel,
                "content_hash": content_hash,
                "agent_view_data": agent_view_data,
                "storage_delta_data": storage_delta_data,
                "relationships_data": relationships_data,
            })
            t_batch_prep_ms += (time.monotonic() - t_prep_0) * 1000

            # Flush batch when it reaches 50 files
            if len(write_batch) >= 50:
                t_write_0 = time.monotonic()
                db.insert_file_artifacts_batch(run_internal_id, write_batch)
                t_batch_write_ms += (time.monotonic() - t_write_0) * 1000
                write_batch = []

        # Flush any remaining files
        if write_batch:
            t_write_0 = time.monotonic()
            db.insert_file_artifacts_batch(run_internal_id, write_batch)
            t_batch_write_ms += (time.monotonic() - t_write_0) * 1000

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
        if bsg_summary:
            security_audit_val = bsg_summary.get("security_audit")
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
    # Fetch entities and relationships from the database
    with db.connection(read_only=True) as conn:
        entities_rows = conn.execute(
            "SELECT entity_id, file_path, entity_name, entity_type, fqn, line_number FROM query_entities WHERE run_id = ?",
            (run_internal_id,)
        ).fetchall()
        
        relationships_rows = conn.execute(
            "SELECT source_id, target_id FROM query_relationships WHERE run_id = ?",
            (run_internal_id,)
        ).fetchall()
        
        files_rows = conn.execute(
            "SELECT val FROM string_dict WHERE id IN (SELECT file_id FROM file_artifacts WHERE run_id = ?)",
            (run_internal_id,)
        ).fetchall()
        file_paths = [r["val"] for r in files_rows]
    
    total_entities = len(entities_rows)
    total_relationships = len(relationships_rows)
    total_files = len(file_paths)
    
    # Entity types distribution
    from collections import Counter, defaultdict
    entity_types = Counter()
    file_ent_counts = Counter()
    entity_to_file = {}
    
    for ent in entities_rows:
        entity_types[ent["entity_type"]] += 1
        file_ent_counts[ent["file_path"]] += 1
        entity_to_file[ent["entity_id"]] = ent["file_path"]
        
    # File categories
    by_ext = defaultdict(list)
    for fp in file_paths:
        ext = Path(fp).suffix.lower() or "(no extension)"
        by_ext[ext].append(fp)
        
    categories = [
        {"extension": ext, "files": sorted(files), "count": len(files)}
        for ext, files in sorted(by_ext.items(), key=lambda x: -len(x[1]))
    ]
    
    context_overview = {
        "total_entities": total_entities,
        "total_relationships": total_relationships,
        "total_files": total_files,
        "entity_types": dict(entity_types.most_common()),
        "file_distribution": [
            {"file_path": fp, "entity_count": count}
            for fp, count in file_ent_counts.most_common(100)
        ],
        "categories": categories,
    }
    
    # top-coupled files
    coupling = defaultdict(int)
    for rel in relationships_rows:
        src_file = entity_to_file.get(rel["source_id"])
        tgt_file = entity_to_file.get(rel["target_id"])
        if src_file and tgt_file and src_file != tgt_file:
            coupling[src_file] += 1
            coupling[tgt_file] += 1
            
    top_coupled = [
        {"file_path": fp, "coupling": c}
        for fp, c in sorted(coupling.items(), key=lambda x: x[1], reverse=True)[:50]
    ]
    
    structural_metrics = {
        "entity_type_distribution": dict(entity_types),
        "top_coupled_files": top_coupled,
    }
    
    # artifact_payload: top 200 entities (name, type, fqn, file, start_line) + rel count per file
    # Sort alphabetically by fqn or name
    sorted_ents = sorted(entities_rows, key=lambda e: e["fqn"] or e["entity_name"])
    top_entities = []
    for e in sorted_ents[:200]:
        top_entities.append({
            "name": e["entity_name"],
            "type": e["entity_type"],
            "fqn": e["fqn"],
            "file": e["file_path"],
            "start_line": e["line_number"],
        })
        
    # rel count per file (originating from each file)
    rel_counts = Counter()
    for rel in relationships_rows:
        src_file = entity_to_file.get(rel["source_id"])
        if src_file:
            rel_counts[src_file] += 1
            
    artifact_payload = {
        "entities": top_entities,
        "rel_count_per_file": dict(rel_counts),
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
