"""Orchestrator for `batho build` — full index build for new working directories.

Creates a .batho SQLite database with: code graph, BSG map, context outputs,
baseline snapshot, and file tracking records. If .batho already exists,
exits early directing the user to `batho patch`.
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


def _compute_file_hash(file_path: Path) -> str:
    """Compute SHA-256 hash of file contents."""
    h = hashlib.sha256()
    try:
        h.update(file_path.read_bytes())
    except OSError:
        return ""
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


def run_build(options: BuildOptions) -> BuildResult:
    """Execute a full index build for a working directory.

    If .batho already exists and force_full is False, returns early
    with success=True and a warning indicating patch should be used.
    """
    t0 = time.monotonic()
    root = options.root.resolve()
    db_path = root / ".batho"

    # --- Guard: existing database ---
    if db_path.exists() and not options.force_full:
        msg = (
            f".batho database already exists at {db_path}.\n"
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
    from batho.storage.engine import BathoDatabase

    db = BathoDatabase(db_path, repo_root=root)
    run_id = _generate_run_id()
    db.create_run(run_id, schema_version="batho-db.v1", root_path=str(root))

    LOGGER.info("build_started", root=str(root), run_id=run_id)

    # --- Build code graph ---
    from batho.context.codegraph import CodeGraphIndexer

    indexer = CodeGraphIndexer(cache_path=str(db_path), root=str(root))
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

    # --- Persist entities & relationships to DB ---
    db.insert_entities(run_id, [e.to_dict() for e in graph.entities.values()])
    db.insert_relationships(run_id, [r.to_dict() for r in graph.relationships])

    # --- Apply BSG plugin rules ---
    rules_cfg = cfg.get("rules", {})
    if rules_cfg:
        try:
            from batho.bsg.rules import apply_rule_plugins

            apply_rule_plugins(
                graph=graph,
                root_path=root,
                rules_config=rules_cfg,
                logger=LOGGER,
            )
        except Exception as exc:
            LOGGER.warning("build_rules_failed", error=str(exc))

    # --- Build BSG map & persist ---
    from batho.context.bsg_map import BSGMap

    bsg_map = BSGMap.build(graph, str(root))
    bsg_file_count = len(bsg_map._by_file)

    # Persist BSG entries per file
    bsg_entries: list[dict[str, Any]] = []
    for file_path, entities in bsg_map._by_file.items():
        bsg_json_data = json.dumps(
            [e.to_dict(view="agent") for e in entities],
            ensure_ascii=True,
        )
        checksum = hashlib.sha256(bsg_json_data.encode()).hexdigest()[:16]
        bsg_entries.append({
            "file_path": file_path,
            "view_type": "agent",
            "bsg_json": bsg_json_data,
            "node_count": len(entities),
            "checksum": checksum,
        })

    if bsg_entries:
        db.insert_bsg_entries(run_id, bsg_entries)

    LOGGER.info("build_bsg_complete", files=bsg_file_count)

    # --- Build & persist context outputs ---
    overview_data = _build_context_overview(graph, root)
    files_data = _build_context_files(graph, root)
    db.set_context_output(run_id, "overview", json.dumps(overview_data, ensure_ascii=True))
    db.set_context_output(run_id, "files", json.dumps(files_data, ensure_ascii=True))

    # --- Create baseline snapshot ---
    from batho.time_machine import create_snapshot

    snapshot_id = create_snapshot(
        ctn_dir=root,
        root=root,
        graph=graph,
        bsg_map=bsg_map,
        label="baseline",
    )

    LOGGER.info("build_snapshot_created", snapshot_id=snapshot_id)

    # --- Persist file tracking ---
    file_tracking_records = _build_file_tracking(graph, root)
    if file_tracking_records:
        db.upsert_file_tracking(file_tracking_records)

    # --- Complete run ---
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    db.complete_run(
        run_id,
        entity_count=entity_count,
        rel_count=rel_count,
        file_count=bsg_file_count,
        duration_ms=elapsed_ms,
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
        snapshot_id=snapshot_id,
        duration_ms=elapsed_ms,
    )


# ---------------------------------------------------------------------------
# Context builders
# ---------------------------------------------------------------------------


def _build_context_overview(graph: Any, root: Path) -> dict[str, Any]:
    """Build context overview JSON from graph."""
    from collections import Counter

    file_dist: Counter[str] = Counter()
    type_dist: Counter[str] = Counter()

    for entity in graph.entities.values():
        file_path = entity.file
        if file_path:
            try:
                rel = str(Path(file_path).relative_to(root))
            except ValueError:
                rel = file_path
            file_dist[rel] += 1
        type_dist[entity.type.name] += 1

    return {
        "total_entities": len(graph.entities),
        "total_relationships": len(graph.relationships),
        "total_files": len(file_dist),
        "entity_types": dict(type_dist.most_common()),
        "file_distribution": [
            {"file_path": fp, "entity_count": count}
            for fp, count in file_dist.most_common(100)
        ],
    }


def _build_context_files(graph: Any, root: Path) -> dict[str, Any]:
    """Build context files JSON from graph."""
    from collections import defaultdict

    by_ext: dict[str, list[str]] = defaultdict(list)
    all_files: set[str] = set()

    for entity in graph.entities.values():
        file_path = entity.file
        if not file_path:
            continue
        try:
            rel = str(Path(file_path).relative_to(root))
        except ValueError:
            rel = file_path
        all_files.add(rel)
        ext = Path(rel).suffix.lower() or "(no extension)"
        if rel not in by_ext[ext]:
            by_ext[ext].append(rel)

    categories = [
        {"extension": ext, "files": sorted(files), "count": len(files)}
        for ext, files in sorted(by_ext.items(), key=lambda x: -len(x[1]))
    ]

    return {
        "total_files": len(all_files),
        "categories": categories,
    }


def _build_file_tracking(graph: Any, root: Path) -> list[dict[str, Any]]:
    """Build file tracking records from the indexed graph."""
    import os

    seen: set[str] = set()
    records: list[dict[str, Any]] = []

    for entity in graph.entities.values():
        file_path = entity.file
        if not file_path or file_path in seen:
            continue
        seen.add(file_path)

        try:
            rel = str(Path(file_path).relative_to(root))
        except ValueError:
            rel = file_path

        full_path = root / rel
        if not full_path.exists():
            continue

        try:
            stat = full_path.stat()
            content_hash = _compute_file_hash(full_path)
            records.append({
                "file_path": rel,
                "content_hash": content_hash,
                "mtime": stat.st_mtime,
                "size": stat.st_size,
                "is_indexed": 1,
                "last_run_id": None,
            })
        except OSError:
            continue

    return records
