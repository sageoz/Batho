"""Orchestrator for `batho patch` — incremental index update (v3.0).

Uses native hash-based change detection against the file_tracking table.
Git is no longer used for change detection; it is only captured for metadata.
"""

from __future__ import annotations

import gc
import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from batho.core.config import get_config_cached, set_active_root
from batho.utils.logging import get_logger
from batho.utils.memory_monitor import get_rss_mb, should_flush_for_memory

from batho.modules.compression.bsg_map import BSGMap
from batho.modules.graph.builder.codegraph import InMemoryGraph
from batho.utils.hash import compute_file_hash
from batho.orchestrator.build import _decode_precompiled_batch

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
    # Accepted for API symmetry with build. Patch always uses the in-memory
    # graph backend internally; a warning is logged when set to anything else.
    graph_backend: str | None = None


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


_MANIFEST_FILES = [
    "pyproject.toml", "setup.cfg", "package.json", "Cargo.toml",
    "go.mod", "pom.xml",
]

# Gradle manifest patterns (searched via ManifestParser._find_manifests).
_GRADLE_PATTERNS = ["build.gradle", "build.gradle.kts"]


def _compute_manifests_hash(root: Path) -> str:
    """Hash all manifest files that ManifestParser would parse.

    Uses the same discovery logic as ManifestParser._find_manifests so that
    nested manifests (e.g. subdir/Cargo.toml in a Rust workspace) are included
    in the cache key. Without this, modifying a nested manifest without
    changing any root-level manifest would produce a stale cache hit.
    """
    from batho.modules.dependency.manifest_parser import ManifestParser

    h = hashlib.sha256()
    # Pattern-based manifests: root + nested (up to _MAX_SEARCH_DEPTH)
    for pattern in _MANIFEST_FILES + _GRADLE_PATTERNS:
        for path in ManifestParser._find_manifests(root, pattern):
            try:
                rel = str(path.relative_to(root))
            except ValueError:
                rel = str(path)
            h.update(rel.encode())
            h.update(path.read_bytes())
    # Requirements files: root-level glob (matches parse_manifests behavior)
    for req in root.glob("requirements*.txt"):
        h.update(req.name.encode())
        h.update(req.read_bytes())
    return h.hexdigest()


def _serialize_scope_manager_to_ipc(sm: Any, path: Path) -> None:
    """Serialize ScopeManager global symbols to Arrow IPC file."""
    from batho.modules.storage.arrow_bundle.schemas import SCOPE_MANAGER_CACHE_SCHEMA
    from batho.modules.storage.arrow_bundle.writer import write_simple_ipc

    data = sm.get_global_symbols()
    rows = []
    for partition, symbols_map in data.items():
        for name, info in symbols_map.items():
            rows.append({
                "partition": partition,
                "name": name,
                "symbol_id": info["symbol_id"],
                "symbol_type": info["symbol_type"],
                "scope_path": info["scope_path"],
                "is_external": info.get("is_external", False),
                "is_heuristic": info.get("is_heuristic", False),
            })
    write_simple_ipc(rows, SCOPE_MANAGER_CACHE_SCHEMA, path)


def _deserialize_scope_manager_from_table(table: Any) -> dict:
    """Reconstruct nested global symbols dict from Arrow IPC table rows."""
    result: dict[str, dict[str, dict[str, Any]]] = {}
    if table.num_rows == 0:
        return result
    for row in table.to_pylist():
        partition = row["partition"]
        name = row["name"]
        if partition not in result:
            result[partition] = {}
        result[partition][name] = {
            "symbol_id": row["symbol_id"],
            "symbol_type": row["symbol_type"],
            "scope_path": row["scope_path"],
            "is_external": row["is_external"],
            "is_heuristic": row["is_heuristic"],
        }
    return result




def _load_project_scope_from_store(
    db: Any,
    base_run_internal_id: int | None,
    changed_file_paths: set[str],
) -> Any:
    """Load project symbols from the base run's artifact store into a ScopeManager.

    Excludes UNRESOLVED entities and entities from files being patched
    (those will be re-extracted from the changed files and would otherwise
    shadow the freshly-parsed symbols).

    Args:
        db: Open ArrowBundle instance for the base run.
        base_run_internal_id: Internal numeric run id of the base run
            (reserved for future run-scoped filtering; currently the
            agent_views table is already scoped to the active run).
        changed_file_paths: Set of repo-relative paths being patched in
            this run. Their stale symbols are skipped.

    Returns:
        A populated ScopeManager. Empty if no entities are available.
    """
    from batho.modules.extraction.scope_manager import ScopeManager

    scope = ScopeManager()

    # Build file_id → file_path mapping from the tracking table
    tracking = db.get_all_file_tracking()
    file_id_to_path: dict[Any, str] = {
        v.get("file_id"): k for k, v in tracking.items()
    }

    # Identify file_ids for changed files so we can skip their stale symbols.
    # The changed files will be re-parsed and their new symbols are added to
    # the in-flight ScopeManager by build_graph(); keeping stale entries here
    # would risk resolving stubs against deleted/renamed entities.
    changed_file_ids: set[Any] = {
        v.get("file_id") for fp, v in tracking.items()
        if fp in changed_file_paths
    }

    # Read all entities from agent_views (already scoped to the active run)
    db._reader.invalidate()
    agent_table = db._reader._get_table("agent_views")
    if agent_table.num_rows == 0:
        return scope

    # Filter the table in Arrow before converting to Python rows. This avoids
    # materializing the full agent table when only unchanged project symbols
    # are needed for stub resolution.
    import pyarrow as pa
    import pyarrow.compute as pc

    not_unresolved = pc.invert(pc.equal(agent_table["entity_type"], "UNRESOLVED"))
    if changed_file_ids:
        file_id_type = agent_table.schema.field("file_id").type
        changed_array = pa.array(list(changed_file_ids), type=file_id_type)
        not_changed = pc.invert(pc.is_in(agent_table["file_id"], changed_array))
        mask = pc.and_(not_unresolved, not_changed)
    else:
        mask = not_unresolved

    filtered = agent_table.filter(mask)
    for row in filtered.to_pylist():
        entity_name = row.get("name", "")
        entity_id = row.get("entity_id", "")
        file_path = file_id_to_path.get(row.get("file_id"), "")

        if not entity_name or not entity_id:
            continue

        scope.define_global_symbol_qualified(
            name=entity_name,
            symbol_id=entity_id,
            symbol_type=row.get("entity_type", ""),
            filepath=file_path,
            is_global=True,
        )

    return scope


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


def run_patch(options: PatchOptions) -> PatchResult:
    """Incremental patch of an existing .batho artifact bundle."""
    from batho.modules.storage.arrow_bundle import resolve_bundle_dir, get_bundle
    from batho.modules.storage.arrow_bundle.incremental import IncrementalEngine, FileChangeType, FileChange

    t0 = time.monotonic()
    root = options.root.resolve()

    if options.graph_backend and options.graph_backend != "in-memory":
        LOGGER.warning(
            "patch_ignoring_graph_backend",
            requested=options.graph_backend,
            reason="patch always uses in-memory; Arrow is build-only",
        )

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
    bundle_dir = resolve_bundle_dir(root)
    meta_path = bundle_dir / "meta.json"

    if not meta_path.exists():
        msg = f"No artifact bundle found at {root}. Run: batho build --root {root}"
        LOGGER.error("patch_failed_no_bundle", root=str(root))
        return PatchResult(success=False, warnings=[msg])

    db = None
    run_uuid = ""
    base_run_uuid = ""
    lock = None
    try:
        from batho.utils.file_io import InterProcessLock
        batho_dir = root / ".batho"
        batho_dir.mkdir(parents=True, exist_ok=True)
        lock = InterProcessLock(batho_dir / "batho.lock")
        lock.__enter__()

        db = get_bundle(root)
        base_run_uuid = db.get_latest_run_id() or ""
        if not base_run_uuid:
            msg = f"No completed run found. Run: batho build --root {root}"
            LOGGER.error("patch_failed_no_run", root=str(root))
            return PatchResult(success=False, warnings=[msg])

        base_run_internal_id = db.get_run_internal_id(base_run_uuid)
        cfg = get_config_cached()
        memory_cfg = cfg.get("memory", {})
        community_cfg = cfg.get("community_detection", {})
        rss_flush_threshold_mb = float(memory_cfg.get("rss_flush_threshold_mb", 1000.0))

        LOGGER.info(
            "effective_memory_config",
            warning_threshold_mb=memory_cfg.get("warning_threshold_mb", 800.0),
            critical_threshold_mb=memory_cfg.get("critical_threshold_mb", 1500.0),
            rss_flush_threshold_mb=rss_flush_threshold_mb,
            max_per_worker_mb=memory_cfg.get("max_per_worker_mb", 150.0),
        )
        LOGGER.info(
            "effective_community_detection_config",
            enabled=community_cfg.get("enabled", True),
            skip_threshold=community_cfg.get("skip_threshold", 200_000),
            sample_threshold=community_cfg.get("sample_threshold", 100_000),
        )

        max_file_size_kb = options.max_file_size_kb or cfg.get("indexer", {}).get("max_file_size_kb", 500)

        # --- Detect changes natively (Batho's Local Git Model) ---
        strict_hashing = bool(cfg.get("indexer", {}).get("strict_hashing", True))

        incremental_engine = IncrementalEngine(db, base_run_uuid)
        changes = incremental_engine.scan_changes(
            root=root,
            max_file_size_kb=max_file_size_kb,
            strict_hashing=strict_hashing,
        )

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

        from batho.modules.storage.arrow_store import BsgScratchStore
        batho_dir = root / ".batho"

        # --- Blob-level copy-on-write for unchanged files ---
        # INVARIANT: c.path must be a relative path (relative to root)
        changed_file_paths = {c.path for c in changes}
        for _p in changed_file_paths:
            if Path(_p).is_absolute():
                raise ValueError(
                    f"FileChange.path must be relative to root, got absolute: {_p!r}"
                )

        # Open BSG scratch store for patch (Arrow store, unchanged from before)
        store, delta_store = BsgScratchStore.open_for_patch(
            batho_dir=batho_dir,
            new_run_uuid=run_uuid,
            new_run_internal_id=run_internal_id,
            changed_paths=changed_file_paths,
            db=None,
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
        indexer = None

        if added_or_modified:
            bsg_cfg = dict(cfg.get("bsg", {}))
            cache_cfg = dict(bsg_cfg.get("cache", {}))
            cache_cfg["enabled"] = True
            cache_cfg["path"] = str(bundle_dir)
            bsg_cfg["cache"] = cache_cfg

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

            # --- Dependency Indexing (CDEU) for Patch ---
            # Cache ScopeManager across patches when manifests haven't changed.
            from batho.modules.dependency import build_dependency_index
            from batho.modules.extraction.scope_manager import ScopeManager

            dep_scope_manager = ScopeManager()
            dep_cfg = cfg.get("dependency", {})
            if isinstance(dep_cfg, BaseModel):
                dep_cfg = dep_cfg.model_dump()

            if dep_cfg.get("enabled", True):
                manifest_hash = _compute_manifests_hash(root)
                cache_ipc = batho_dir / "scope_manager_cache.ipc"
                cache_meta = batho_dir / "scope_manager_cache.meta.json"

                cache_hit = False
                if cache_ipc.exists() and cache_meta.exists():
                    try:
                        cached_meta = json.loads(cache_meta.read_text())
                        if cached_meta.get("manifest_hash") == manifest_hash:
                            from batho.modules.storage.arrow_bundle.writer import read_ipc_table
                            table = read_ipc_table(cache_ipc)
                            data = _deserialize_scope_manager_from_table(table)
                            dep_scope_manager.load_global_symbols(data)
                            cache_hit = True
                            LOGGER.info(
                                "scope_manager_loaded_from_cache",
                                symbols=dep_scope_manager.global_symbol_count,
                            )
                    except Exception as exc:
                        LOGGER.warning("scope_manager_cache_load_failed", error=str(exc))

                if not cache_hit:
                    build_dependency_index(
                        root=root,
                        scope_manager=dep_scope_manager,
                        cfg=dep_cfg,
                        cache_dir=cfg.get("paths", {}).get("cache_dir"),
                    )
                    try:
                        # Atomic tmp + rename so readers never see a partial IPC file.
                        cache_ipc_tmp = batho_dir / "scope_manager_cache.tmp.ipc"
                        cache_meta_tmp = batho_dir / "scope_manager_cache.meta.json.tmp"
                        _serialize_scope_manager_to_ipc(dep_scope_manager, cache_ipc_tmp)
                        cache_meta_tmp.write_text(json.dumps({
                            "manifest_hash": manifest_hash,
                        }))
                        cache_ipc_tmp.replace(cache_ipc)
                        cache_meta_tmp.replace(cache_meta)
                        LOGGER.info(
                            "scope_manager_cached",
                            symbols=dep_scope_manager.global_symbol_count,
                        )
                    except Exception as exc:
                        LOGGER.warning("scope_manager_cache_write_failed", error=str(exc))

            # Load project symbols from the base run so that
            # resolve_contextual_stubs() can resolve cross-file references to
            # entities in unchanged files. Without this, refs to other project
            # files remain UNRESOLVED and the patched graph diverges from a
            # full rebuild (C13 patch-correctness gap).
            from batho.modules.graph.builder.codegraph import _merge_external_scope

            try:
                project_scope = _load_project_scope_from_store(
                    db, base_run_internal_id, changed_file_paths
                )
                _merge_external_scope(dep_scope_manager, project_scope)
                LOGGER.info(
                    "project_scope_loaded",
                    symbols=project_scope.global_symbol_count,
                    changed_files_excluded=len(changed_file_paths),
                )
            except Exception as exc:
                LOGGER.warning("project_scope_load_failed", error=str(exc))

            from batho.modules.graph.builder.codegraph import CodeGraphIndexer
            from batho.modules.storage.arrow_bundle.helpers import _minify_graph_payload
            from collections import defaultdict

            with CodeGraphIndexer(
                cache_path=str(root), root=str(root), ast_cache_dir=ast_cache_dir
            ) as indexer:
                # Invalidate AST cache for changed/deleted files in unified cache
                for change in changes:
                    try:
                        indexer._cache.delete_ast_by_path(change.path)
                    except Exception:
                        pass
                write_batch = []
                current_batch_bytes = 0
                unindexed_paths = set()

                # Collect valid changed file paths
                valid_changes = []
                for change in added_or_modified:
                    full_path = root / change.path
                    if full_path.exists():
                        valid_changes.append(change)

                if not valid_changes:
                    # Skip parsing if no valid files
                    pass
                else:
                    all_paths = [str(root / c.path) for c in valid_changes]
                    max_workers = min(4, len(all_paths)) if len(all_paths) > 1 else 1

                    # Precompiled blob collection — preserves all entities (including
                    # duplicate-named ones that would collide in InMemoryGraph's dict).
                    # This mirrors the build flow's write_precompiled_callback.
                    precompiled_write_batch: list[dict] = []

                    def write_precompiled_callback(file_rel: str, blob_data: dict) -> None:
                        item = {
                            "file_path": file_rel,
                            "content_hash": blob_data.get("content_hash", ""),
                            "agent_blob": blob_data.get("agent_blob", b""),
                            "storage_blob": blob_data.get("storage_blob", b""),
                            "rels_blob": blob_data.get("rels_blob", b""),
                            "_use_precompiled": True,
                        }
                        precompiled_write_batch.append(item)

                    try:
                        batch_graph = indexer.build_graph(
                            root=str(root),
                            file_list=all_paths,
                            max_workers=max_workers,
                            max_file_size_kb=max_file_size_kb,
                            verbose=options.verbose,
                            index_id=run_uuid,
                            external_scope_manager=dep_scope_manager,
                            graph_backend="in-memory",
                            skip_orphan_pruning=True,
                            write_callback=write_precompiled_callback,
                        )
                        for _, rel in indexer.get_unindexed_files():
                            unindexed_paths.add(rel)
                        indexer.clear_unindexed_files()
                    except Exception as exc:
                        LOGGER.warning("patch_batch_parse_failed", error=str(exc))
                        batch_graph = None

                    if batch_graph is not None:
                        # Decode precompiled blobs (preserves all entities including
                        # duplicate-named ones that collide in InMemoryGraph.entities dict)
                        if precompiled_write_batch:
                            decoded_items = _decode_precompiled_batch(precompiled_write_batch)
                        else:
                            decoded_items = []
                        decoded_by_file = {item["file_path"]: item for item in decoded_items}
                        precompiled_write_batch.clear()

                        # Group ALL relationships by source entity's file (for fallback
                        # and for extracting synthesized/derived rels added post-extraction)
                        root_str = str(root)
                        all_rels_by_file: dict[str, list] = defaultdict(list)
                        synthesized_rels_by_file: dict[str, list[dict]] = defaultdict(list)
                        for rel in batch_graph.relationships:
                            src_ent = batch_graph.get_entity(rel.source_id)
                            if src_ent and src_ent.file:
                                rel_file = src_ent.file
                                if rel_file.startswith(root_str):
                                    rel_file = rel_file[len(root_str)+1:]
                                rel_dict = rel.to_dict()
                                all_rels_by_file[rel_file].append(rel_dict)
                                meta = rel_dict.get("metadata") or {}
                                if meta.get("synthesized") or meta.get("derived"):
                                    synthesized_rels_by_file[rel_file].append(rel_dict)

                        # Build BSGMap as fallback for files not in precompiled blobs
                        bsg_map_batch = BSGMap.build(batch_graph, str(root))

                        for change in valid_changes:
                            file_rel = change.path
                            decoded = decoded_by_file.get(file_rel)

                            t_prep_0 = time.monotonic()

                            if decoded:
                                # Primary path: use precompiled blobs (preserves duplicates)
                                agent_view_data = decoded["agent_view_data"]
                                storage_delta_data = decoded["storage_delta_data"]
                                relationships_data = decoded["relationships_data"]
                                content_hash = decoded.get("content_hash", "") or change.new_hash or compute_file_hash(root / file_rel) or ""
                                agent_entities = agent_view_data.get("entities", [])
                                entities_list = agent_entities
                            else:
                                # Fallback: file wasn't precompiled (e.g. extraction error)
                                # Use graph entities — may lose duplicates but better than nothing
                                file_entities = bsg_map_batch._by_file.get(file_rel)
                                if not file_entities:
                                    file_entities = [
                                        e for e in batch_graph.entities.values()
                                        if getattr(e, 'file', '') and e.file.endswith(file_rel)
                                    ]
                                entities_list = [e.to_dict() if hasattr(e, 'to_dict') else e for e in file_entities]

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
                                storage_delta_data = {"entities": delta_entities}
                                relationships_data = all_rels_by_file.get(file_rel, [])
                                content_hash = change.new_hash or compute_file_hash(root / file_rel) or ""

                            rels_list = relationships_data

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

                            new_item = write_batch[-1]
                            current_batch_bytes += _estimate_batch_size_bytes(new_item)

                            # Flush batch using configurable dynamic size or byte threshold (default 15MB)
                            batch_size = cfg.get("persistence", {}).get("batch_size", 500)
                            batch_bytes_threshold = cfg.get("persistence", {}).get("batch_bytes_threshold", 15_728_640)
                            should_rss_flush = should_flush_for_memory(rss_flush_threshold_mb)
                            if (
                                len(write_batch) >= batch_size
                                or current_batch_bytes >= batch_bytes_threshold
                                or should_rss_flush
                            ):
                                if should_rss_flush:
                                    rss_before = get_rss_mb()
                                t_write_0 = time.monotonic()
                                db.insert_file_artifacts_batch(run_internal_id, write_batch, store=store, delta_store=delta_store)
                                t_batch_write_ms += (time.monotonic() - t_write_0) * 1000
                                write_batch = []
                                current_batch_bytes = 0
                                if should_rss_flush:
                                    gc.collect()
                                    rss_after = get_rss_mb()
                                    recovered = round(rss_before - rss_after, 1)
                                    if recovered < 0:
                                        LOGGER.warning(
                                            "rss_flush_released_memory",
                                            rss_before_mb=round(rss_before, 1),
                                            rss_after_mb=round(rss_after, 1),
                                            recovered_mb=recovered,
                                            warning="gc.collect increased RSS; memory pressure may persist",
                                        )
                                    elif recovered > 0:
                                        LOGGER.info(
                                            "rss_flush_released_memory",
                                            rss_before_mb=round(rss_before, 1),
                                            rss_after_mb=round(rss_after, 1),
                                            recovered_mb=recovered,
                                        )

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
                    db.insert_file_artifacts_batch(run_internal_id, write_batch, store=store, delta_store=delta_store)
                    t_batch_write_ms += (time.monotonic() - t_write_0) * 1000

                # Append synthesized/derived relationships that were added AFTER
                # precompilation (stub resolution, hierarchy, overrides, semantic overlay).
                # These are not in the precompiled rels_blob, so we append them separately.
                if batch_graph is not None and synthesized_rels_by_file:
                    for file_rel, syn_rels in synthesized_rels_by_file.items():
                        if syn_rels:
                            db.append_relationships_for_file(
                                run_internal_id,
                                file_rel,
                                syn_rels,
                            )

        # --- Update file tracking ---
        deleted_paths = {change.path for change in deleted}
        incremental_engine.handle_deleted_files(deleted_paths)
        
        for change in deleted:
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

        fingerprints = []
        for change in added_or_modified:
            full_path = root / change.path
            if full_path.exists():
                try:
                    stat = full_path.stat()
                    content_hash = change.new_hash or compute_file_hash(full_path) or ""
                    is_indexed = 0 if change.path in unindexed_paths else 1
                    fingerprints.append({
                        "file_path": change.path,
                        "content_hash": content_hash,
                        "mtime": stat.st_mtime,
                        "mtime_ns": getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1e9)),
                        "inode": getattr(stat, "st_ino", None),
                        "size": stat.st_size,
                        "is_indexed": is_indexed,
                        "last_run_id": run_uuid,
                        "encoding": "utf-8",
                    })
                except OSError:
                    pass
        incremental_engine.update_state(fingerprints)

        # --- Compact Arrow store, then resolve dangling cross-file references ---
        try:
            store.compact()
        except Exception as exc:
            LOGGER.warning("failed_to_compact_bsg_store_patch", error=str(exc))

        try:
            resolved_joined = store.resolve_dangling(None)
            LOGGER.info("cross_file_relationships_resolved", count=resolved_joined)
        except Exception as exc:
            LOGGER.warning("cross_file_relationships_failed", error=str(exc))

        # Compact delta sidecar (writes bsg/<patch_uuid>/)
        try:
            delta_store.compact()
        except Exception as exc:
            LOGGER.warning("failed_to_compact_delta_store", error=str(exc))

        store.finalize()

        # --- Complete run ---
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        file_count = len(db.get_all_file_hashes())
        total_entities = store.entity_count
        total_rels = store.rel_count

        db.complete_run(
            run_uuid,
            entity_count=total_entities,
            rel_count=total_rels,
            file_count=file_count,
            duration_ms=elapsed_ms,
        )

        # --- Finalize Run Artifacts ---
        from batho.orchestrator.build import _compute_run_metrics
        metrics = _compute_run_metrics(store, db, root)
        
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
        
        total_base_files = len(db.get_all_file_tracking())
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

        store.cleanup_streams()
        delta_store.cleanup_streams()

        # --- Rebuild communities from updated graph ---
        community_cfg = cfg.get("community_detection", {})
        if community_cfg.get("enabled", True):
            try:
                from batho.modules.graph.community import detect_communities, communities_to_rows
                from batho.modules.storage.arrow_bundle.schemas import COMMUNITIES_SCHEMA
                from batho.modules.storage.arrow_bundle.writer import write_simple_ipc
                from batho.modules.storage.arrow_bundle import resolve_bundle_dir
                from batho.modules.graph.builder.codegraph import InMemoryGraph
                from batho.core.schemas import EntityType, RelationshipType
                from types import SimpleNamespace
                bundle_dir = resolve_bundle_dir(root)
                t_comm_0 = time.monotonic()

                # Reconstruct graph from stored artifact tables
                db._reader.invalidate()
                agent_table = db._reader._get_table("agent_views")
                rels_table = db._reader._get_table("rels_views")
                tracking = db._reader.get_all_file_tracking()
                file_id_to_path = {v.get("file_id"): k for k, v in tracking.items()}

                entities: dict[str, Any] = {}
                if agent_table.num_rows > 0:
                    for row in agent_table.to_pylist():
                        eid = row.get("entity_id", "")
                        try:
                            etype = EntityType[row.get("entity_type", "UNRESOLVED")]
                        except KeyError:
                            etype = EntityType.UNRESOLVED
                        entities[eid] = SimpleNamespace(
                            id=eid,
                            name=row.get("name", ""),
                            file=file_id_to_path.get(row.get("file_id", -1), ""),
                            type=etype,
                        )

                relationships: list[Any] = []
                if rels_table.num_rows > 0:
                    for row in rels_table.to_pylist():
                        try:
                            rtype = RelationshipType[row.get("relation_type", "")]
                        except KeyError:
                            continue
                        relationships.append(SimpleNamespace(
                            source_id=row.get("source_id", ""),
                            target_id=row.get("target_id", ""),
                            type=rtype,
                        ))

                graph = InMemoryGraph(entities=entities, relationships=relationships)
                communities = detect_communities(graph, community_cfg)
                comm_rows = communities_to_rows(communities)
                comm_path = bundle_dir / "communities.tmp.ipc"
                write_simple_ipc(comm_rows, COMMUNITIES_SCHEMA, comm_path)
                final_comm_path = bundle_dir / "communities.ipc"
                comm_path.replace(final_comm_path)
                comm_duration_ms = (time.monotonic() - t_comm_0) * 1000
                LOGGER.info(
                    "community_detection_rebuilt",
                    communities=len(communities),
                    duration_ms=round(comm_duration_ms, 2),
                )
            except Exception as exc:
                LOGGER.warning("community_detection_rebuild_failed", error=str(exc))

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

        warnings_list = list(getattr(indexer, "warnings", [])) if indexer else []
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
            warnings=warnings_list,
        )

    except Exception as e:
        # Mark run as failed on any unhandled exception
        LOGGER.error("patch_unhandled_exception", error=str(e))
        # Ensure scratch stores are cleaned up on exception (leak prevention)
        try:
            if 'store' in locals() and store is not None:
                store.cleanup_streams()
        except Exception:
            pass
        try:
            if 'delta_store' in locals() and delta_store is not None:
                delta_store.cleanup_streams()
        except Exception:
            pass
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
    finally:
        if lock is not None:
            try:
                lock.__exit__(None, None, None)
            except Exception:
                pass
