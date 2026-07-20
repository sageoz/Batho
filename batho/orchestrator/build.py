"""Orchestrator for `batho build` — full index build for new working directories.

Creates an Arrow Bundle artifact in .batho/artifact/ with: code graph, BSG map, context outputs,
baseline snapshot, and file tracking records. If the artifact already exists,
exits early directing the user to `batho patch`.
"""

from __future__ import annotations

import gc
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
from batho.utils.memory_monitor import get_rss_mb, should_flush_for_memory
from batho.modules.graph.incremental import get_head_commit, get_current_branch, is_git_repo

LOGGER = get_logger(__name__, component="orchestrator.build")


def _decode_precompiled_batch(batch: list[dict]) -> list[dict]:
    """Decode msgpack+zstd blobs into agent/storage/rels dicts for BathoBundleWriter."""
    import msgpack
    import zstandard as zstd
    from batho.modules.storage.arrow_bundle.helpers import _expand_graph_payload

    dctx = zstd.ZstdDecompressor()
    result = []
    for b in batch:
        try:
            agent_view = _expand_graph_payload(msgpack.unpackb(dctx.decompress(b["agent_blob"])))
        except Exception as exc:
            LOGGER.error("decode_precompiled_agent_blob_failed", file_path=b["file_path"], error=str(exc))
            raise
        try:
            storage_view = _expand_graph_payload(msgpack.unpackb(dctx.decompress(b["storage_blob"])))
            for ent in storage_view.get("entities", []):
                ent.setdefault("leading_whitespace", "")
                ent.setdefault("trailing_whitespace", "")
        except Exception as exc:
            LOGGER.error("decode_precompiled_storage_blob_failed", file_path=b["file_path"], error=str(exc))
            raise
        try:
            rels_raw = msgpack.unpackb(dctx.decompress(b["rels_blob"]))
            rels = rels_raw if isinstance(rels_raw, list) else []
        except Exception as exc:
            LOGGER.error("decode_precompiled_rels_blob_failed", file_path=b["file_path"], error=str(exc))
            raise
        result.append({
            "file_path": b["file_path"],
            "content_hash": b["content_hash"],
            "agent_view_data": agent_view,
            "storage_delta_data": storage_view,
            "relationships_data": rels,
        })
    return result


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
    from batho.modules.storage.arrow_bundle import resolve_bundle_dir, BathoBundle
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
    from batho.utils.file_io import InterProcessLock
    batho_dir = root / ".batho"
    batho_dir.mkdir(parents=True, exist_ok=True)
    lock = InterProcessLock(batho_dir / "batho.lock")

    db = None
    store = None
    run_uuid = ""
    try:
        with lock:
            try:

                set_active_root(root)
                bundle_dir = resolve_bundle_dir(root)
                meta_path = bundle_dir / "meta.json"

                # --- Guard: existing bundle ---
                if meta_path.exists() and not options.force_full:
                    msg = (
                        f"Artifact bundle already exists at {bundle_dir}.\n"
                        f"To update incrementally, run: batho patch --root {root}\n"
                        f"To force a full rebuild, run: batho build --root {root} --full"
                    )
                    LOGGER.info("build_skipped_existing", root=str(root))
                    return BuildResult(
                        success=True,
                        warnings=["already_built", msg],
                    )

                if options.force_full and bundle_dir.exists():
                    import shutil as _shutil
                    LOGGER.info("build_force_full_clearing", path=str(bundle_dir))
                    _shutil.rmtree(bundle_dir, ignore_errors=True)
                    bundle_dir.mkdir(parents=True, exist_ok=True)

                # --- Load config ---
                cfg = get_config_cached(auto_create=True)
                indexer_cfg = cfg.get("indexer", {})
                bsg_cfg = cfg.get("bsg", {})
                memory_cfg = cfg.get("memory", {})
                community_cfg = cfg.get("community_detection", {})
                rss_flush_threshold_mb = float(memory_cfg.get("rss_flush_threshold_mb", 650.0))

                LOGGER.info(
                    "effective_memory_config",
                    warning_threshold_mb=memory_cfg.get("warning_threshold_mb", 500.0),
                    critical_threshold_mb=memory_cfg.get("critical_threshold_mb", 800.0),
                    rss_flush_threshold_mb=rss_flush_threshold_mb,
                    max_per_worker_mb=memory_cfg.get("max_per_worker_mb", 150.0),
                )
                LOGGER.info(
                    "effective_community_detection_config",
                    enabled=community_cfg.get("enabled", True),
                    skip_threshold=community_cfg.get("skip_threshold", 200_000),
                    sample_threshold=community_cfg.get("sample_threshold", 100_000),
                )

                max_file_size_kb = options.max_file_size_kb or indexer_cfg.get("max_file_size_kb", 500)

                # Inherit bidirectional settings directly from config without hardcoding
                bsg_cfg = dict(bsg_cfg)
                bidi_cfg = dict(bsg_cfg.get("bidirectional", {}))
                include_gaps_flag = bidi_cfg.get("include_gaps", False)
                bidi_cfg["include_gaps"] = include_gaps_flag
                bsg_cfg["bidirectional"] = bidi_cfg

                cache_cfg = dict(bsg_cfg.get("cache", {}))
                cache_cfg["enabled"] = True
                cache_cfg["path"] = str(bundle_dir)
                bsg_cfg["cache"] = cache_cfg

                if options.max_workers:
                    parallel_cfg = dict(bsg_cfg.get("parallel", {}))
                    parallel_cfg["max_workers"] = options.max_workers
                    bsg_cfg["parallel"] = parallel_cfg

                # --- Extraction AST cache configuration ---
                extraction_cfg = cfg.get("extraction", {})
                if isinstance(extraction_cfg, BaseModel):
                    extraction_cfg = extraction_cfg.model_dump()
                extraction_cache_cfg = extraction_cfg.get("cache", {})
                ast_cache_dir = None
                if extraction_cache_cfg.get("enabled", True):
                    cache_dir = cfg.get("paths", {}).get("cache_dir")
                    if cache_dir:
                        ast_cache_dir = str(Path(cache_dir))
                    else:
                        ast_cache_dir = str(root / ".batho" / "cache")

                # --- Initialize Arrow Bundle ---
                db = BathoBundle(root)
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
                from batho.modules.storage.arrow_store import BsgScratchStore

                batho_dir = root / ".batho"
                store = BsgScratchStore(run_uuid=run_uuid, batho_dir=batho_dir, run_internal_id=run_internal_id)

                t_batch_prep_ms = 0.0
                t_batch_write_ms = 0.0
                precompiled_write_batch = []
                precompiled_current_batch_bytes = 0

                def _flush_precompiled_batch() -> None:
                    nonlocal precompiled_write_batch, precompiled_current_batch_bytes, t_batch_write_ms
                    if not precompiled_write_batch:
                        return
                    t_write_0 = time.monotonic()
                    arrow_batch = _decode_precompiled_batch(precompiled_write_batch)
                    db.insert_file_artifacts_batch(run_internal_id, arrow_batch, store=store)
                    t_batch_write_ms += (time.monotonic() - t_write_0) * 1000
                    precompiled_write_batch.clear()
                    precompiled_current_batch_bytes = 0

                def _flush_legacy_batch(batch: list[dict]) -> None:
                    nonlocal t_batch_write_ms
                    if not batch:
                        return
                    t_write_0 = time.monotonic()
                    db.insert_file_artifacts_batch(run_internal_id, batch, store=store, entity_ids_global=all_entity_ids)
                    t_batch_write_ms += (time.monotonic() - t_write_0) * 1000
                    batch.clear()

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
                    should_rss_flush = should_flush_for_memory(rss_flush_threshold_mb)
                    if (
                        len(precompiled_write_batch) >= batch_size
                        or precompiled_current_batch_bytes >= batch_bytes_threshold
                        or should_rss_flush
                    ):
                        if should_rss_flush:
                            rss_before = get_rss_mb()
                        _flush_precompiled_batch()
                        if should_rss_flush:
                            gc.collect()
                            rss_after = get_rss_mb()
                            LOGGER.info(
                                "rss_flush_released_memory",
                                rss_before_mb=round(rss_before, 1),
                                rss_after_mb=round(rss_after, 1),
                                recovered_mb=round(rss_before - rss_after, 1),
                            )

                with CodeGraphIndexer(
                    cache_path=str(root), root=str(root), ast_cache_dir=ast_cache_dir
                ) as indexer:
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
                        db.fail_run(run_uuid, error_message="No indexable files found")
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

                    # --- Community Detection ---
                    community_cfg = cfg.get("community_detection", {})
                    if community_cfg.get("enabled", True):
                        try:
                            from batho.modules.graph.community import detect_communities, communities_to_rows
                            from batho.modules.storage.arrow_bundle.schemas import COMMUNITIES_SCHEMA
                            from batho.modules.storage.arrow_bundle.writer import write_simple_ipc
                            t_comm_0 = time.monotonic()
                            communities = detect_communities(graph, community_cfg)
                            comm_rows = communities_to_rows(communities)
                            comm_path = bundle_dir / "communities.tmp.ipc"
                            write_simple_ipc(comm_rows, COMMUNITIES_SCHEMA, comm_path)
                            final_comm_path = bundle_dir / "communities.ipc"
                            comm_path.replace(final_comm_path)
                            comm_duration_ms = (time.monotonic() - t_comm_0) * 1000
                            LOGGER.info(
                                "community_detection_complete",
                                communities=len(communities),
                                duration_ms=round(comm_duration_ms, 2),
                            )
                        except Exception as exc:
                            LOGGER.warning("community_detection_failed", error=str(exc))

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
                    from batho.modules.storage.arrow_bundle.helpers import _minify_graph_payload

                    bsg_map = BSGMap.build(graph, str(root), opaque_snapshots=opaque_snapshots)
                    bsg_file_count = len(bsg_map._by_file)
                    LOGGER.info("build_bsg_complete", files=bsg_file_count)

                    # Global entity ID set: lets cross-file rels resolve immediately instead of going to dangling
                    all_entity_ids: set[str] = set(graph.entities.keys())

                    # Flush any remaining precompiled files from the callback buffer
                    if precompiled_write_batch:
                        t_write_0 = time.monotonic()
                        legacy_precompiled = _decode_precompiled_batch(precompiled_write_batch)
                        db.insert_file_artifacts_batch(run_internal_id, legacy_precompiled, store=store, entity_ids_global=all_entity_ids)
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
                    # store_files: all files that need Arrow scratch accumulation (includes precompiled)
                    store_files = all_file_paths

                    if legacy_files or store_files:
                        from collections import defaultdict
                        entities_by_file = defaultdict(list)
                        for entity in graph.entities.values():
                            filepath = entity.file
                            rel = filepath[len(root_str)+1:] if filepath.startswith(root_str) else filepath
                            if rel in store_files:
                                entities_by_file[rel].append(entity.to_dict())

                        rels_by_source_file = defaultdict(list)
                        for rel in graph.relationships:
                            source_ent = graph.get_entity(rel.source_id)
                            rel_file = source_ent.file if source_ent else rel.source_id
                            rel_file_rel = rel_file[len(root_str)+1:] if rel_file.startswith(root_str) else rel_file
                            if rel_file_rel in store_files:
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
                            should_rss_flush = should_flush_for_memory(rss_flush_threshold_mb)
                            if (
                                len(legacy_write_batch) >= batch_size
                                or legacy_current_batch_bytes >= batch_bytes_threshold
                                or should_rss_flush
                            ):
                                if should_rss_flush:
                                    rss_before = get_rss_mb()
                                _flush_legacy_batch(legacy_write_batch)
                                legacy_current_batch_bytes = 0
                                if should_rss_flush:
                                    gc.collect()
                                    rss_after = get_rss_mb()
                                    LOGGER.info(
                                        "rss_flush_released_memory",
                                        rss_before_mb=round(rss_before, 1),
                                        rss_after_mb=round(rss_after, 1),
                                        recovered_mb=round(rss_before - rss_after, 1),
                                    )

                        if legacy_write_batch:
                            _flush_legacy_batch(legacy_write_batch)

                    # --- Accumulate precompiled-path files into BSG Arrow store ---
                    if precompiled_blobs and store_files:
                        from batho.modules.storage.arrow_bundle.helpers import _accumulate_scratch_rows
                        for file_rel in precompiled_blobs:
                            avd = {"entities": [
                                {
                                    "id": e.get("id"),
                                    "name": e.get("name"),
                                    "type": e.get("type") or e.get("entity_type"),
                                    "start_line": e.get("start_line"),
                                    "fqn": e.get("fqn"),
                                    "signature": e.get("signature"),
                                    "is_exported": e.get("is_exported", False),
                                }
                                for e in entities_by_file.get(file_rel, [])
                            ]}
                            rds = rels_by_source_file.get(file_rel, [])
                            _accumulate_scratch_rows(
                                store=store,
                                run_internal_id=run_internal_id,
                                file_path=file_rel,
                                agent_view_data=avd,
                                relationships_data=rds,
                                entity_ids_in_batch=all_entity_ids,
                            )

                    # Compact Arrow scratch store
                    try:
                        store.compact()
                    except Exception as exc:
                        LOGGER.warning("failed_to_compact_bsg_store", error=str(exc))

                    LOGGER.info("batch_performance_breakdown", prep_ms=round(t_batch_prep_ms, 2), write_ms=round(t_batch_write_ms, 2))

                    # --- Resolve dangling cross-file references via Arrow store ---
                    try:
                        t_join_0 = time.monotonic()
                        resolved_joined = store.resolve_dangling(None)
                        LOGGER.info("cross_file_relationships_resolved", count=resolved_joined, time_ms=round((time.monotonic() - t_join_0) * 1000, 2))
                    except Exception as exc:
                        LOGGER.warning("cross_file_relationships_failed", error=str(exc))

                    # --- Persist file tracking ---
                    file_tracking_records = _build_file_tracking(graph, root, indexer, run_id=run_id)
                    if file_tracking_records:
                        db.upsert_file_tracking(file_tracking_records)

                    if indexer is not None:
                        indexer.clear_unindexed_files()

                    stored_entity_count = store.entity_count
                    stored_rel_count = store.rel_count

                    # --- Complete run ---
                    elapsed_ms = int((time.monotonic() - t0) * 1000)
                    db.complete_run(
                        run_uuid,
                        entity_count=stored_entity_count,
                        rel_count=stored_rel_count,
                        file_count=bsg_file_count,
                        duration_ms=elapsed_ms,
                    )

                    # --- Finalize Run Artifacts ---
                    store.finalize()
                    metrics = _compute_run_metrics(store, db, root)
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
                        blob_config=artifact_blobs_cfg,
                    )

                    store.cleanup_streams()

                    LOGGER.info(
                        "build_complete",
                        run_id=run_id,
                        entities=stored_entity_count,
                        relationships=stored_rel_count,
                        files=bsg_file_count,
                        duration_ms=elapsed_ms,
                    )

                    warnings_list = list(getattr(indexer, "warnings", []))
                    return BuildResult(
                        success=True,
                        run_id=run_id,
                        entity_count=stored_entity_count,
                        relationship_count=stored_rel_count,
                        file_count=bsg_file_count,
                        bsg_file_count=bsg_file_count,
                        snapshot_id="",
                        duration_ms=elapsed_ms,
                        warnings=warnings_list,
                    )


            # ---------------------------------------------------------------------------
            # Context builders
            # ---------------------------------------------------------------------------


            except Exception as exc:
                LOGGER.error("build_failed", error=str(exc))
                if db is not None and run_uuid:
                    try:
                        db.fail_run(run_uuid, error_message=str(exc))
                    except Exception:
                        pass
                raise
            finally:
                if store is not None:
                    try:
                        store.cleanup_streams()
                    except Exception:
                        pass
    except Exception as exc:
        LOGGER.error("build_unhandled_exception", error=str(exc))
        return BuildResult(
            success=False,
            warnings=[f"Build failed: {exc}"],
        )

def _compute_run_metrics(store: Any, db: Any, root: Path) -> dict:
    """Compute run metrics from the Arrow scratch store (replaces 8 SQL queries)."""
    from batho.modules.storage.arrow_store.metrics import compute_run_metrics
    return compute_run_metrics(store, db, root)



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
                rel = Path(abs_path).relative_to(root).as_posix()
            except ValueError:
                rel = abs_path
            precompiled_blobs[rel] = blob_data

    if indexer is not None and getattr(indexer, "_indexed_files", None) is not None:
        for file_path in indexer._indexed_files:
            if not file_path:
                continue
            try:
                rel = Path(file_path).relative_to(root).as_posix()
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
            rel = Path(file_path).relative_to(root).as_posix()
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
