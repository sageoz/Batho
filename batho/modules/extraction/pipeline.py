"""
backend/context/pipeline.py — Multiprocessing pipeline for parallel file processing.

Replaces ThreadPoolExecutor with multiprocessing.Pool to bypass Python's GIL
for CPU-bound tree-sitter parsing operations.

Features:
- Process file workers that instantiate their own tree-sitter parsers
- Chunk-based file processing for load balancing
- Error handling with retry logic
- Graceful degradation when multiprocessing unavailable
"""

from __future__ import annotations

import gc
import msgpack
import os
import orjson
from pathlib import Path
from typing import Any, Callable

from batho.modules.storage.cache.unified_cache import (
    BathoCache,
)
from batho.modules.extraction.extractor import ASTExtractor
from batho.core.schemas import Entity, EntityType, FileSnapshot, Relationship
from batho.modules.extraction.symbol_table import FileSymbolTable
from batho.utils.file_io import read_file_bytes
from batho.utils.hash import _is_binary
from batho.utils.logging import configure_logging, get_logger

logger = get_logger(__name__, component="pipeline")
_WORKER_LOGGING_INITIALIZED = False
_WORKER_CACHE: BathoCache | None = None
_WORKER_RULES_CACHE: list[Any] | None = None
_WORKER_ROOT_PATH: str | None = None
_WORKER_ZSTD_COMPRESSOR: Any | None = None


def _create_file_snapshot(
    filepath: str,
    content_hash: str,
    size: int,
    entities: list[Entity],
    cache: BathoCache,
) -> None:
    """Create and store a file snapshot for gap-based reconstruction."""
    _snap = FileSnapshot(
        file_path=filepath,
        file_hash=content_hash,
        file_size=size,
        encoding="utf-8",
        entity_ids=[e.id for e in entities],
        gap_sections=[
            {
                "byte_start": e.start_byte,
                "byte_end": e.end_byte,
                "raw_content": e.raw_content,
                "hash": e.content_hash or "",
            }
            for e in entities
            if e.type == EntityType.SYNTAX_GLUE and e.raw_content is not None
        ],
    )
    cache.set_file_snapshot(_snap)


def _update_cached_entity_file(
    entities: list[Entity],
    filepath: str,
) -> list[Entity]:
    """Update Entity.file to current filepath and recompute IDs on cache hit.

    When a file is renamed or copied, the cached entities retain the old file path,
    causing stale Entity.id (derived from file). This function updates the file
    path so IDs are recomputed correctly.

    Args:
        entities: Entities deserialized from cache (may have stale file path).
        filepath: Current file path (from current disk location).

    Returns:
        List of entities with updated file path and recomputed IDs.
    """
    if not entities:
        return entities

    updated_entities = []
    for entity in entities:
        if entity.file != filepath:
            updated_entities.append(entity._evolve(file=filepath))
        else:
            updated_entities.append(entity)

    return updated_entities


def _serialize_extraction_result(
    entities: list[Entity],
    relationships: list[Relationship],
    filepath: str,
    content_hash: str,
    zstd_compressor: Any,
    file_security_audit: dict[str, Any] | None = None,
) -> tuple[bytes, bytes, bytes, bytes, list[dict], dict[str, Any]]:
    """Serialize extraction results into compressed blobs for storage and graph materialization.

    Returns:
        Tuple of (hollow_bytes, rel_bytes, agent_blob, storage_blob, global_manifest, local_hits)
    """
    from batho.modules.storage.arrow_bundle.helpers import _minify_graph_payload

    # Build hollow topology for graph (excludes heavy raw_content/raw_bytes)
    hollow_topology: list[dict] = []
    for e in entities:
        if e.type != EntityType.SYNTAX_GLUE:
            node: dict = {
                "id": e.id,
                "name": e.name,
                "type": e.type.value,
                "file": filepath,
                "parent_id": e.parent_id,
            }
            # Preserve stub resolution metadata if present
            if e.is_contextual_stub:
                node["caller_scope"] = e.metadata.get("caller_scope")
                node["target_name"] = e.metadata.get("target_name")
            hollow_topology.append(node)
    hollow_bytes = msgpack.packb(hollow_topology)

    # Precompile agent and storage views for persistence
    agent_entities = [e.to_dict(view="agent") for e in entities]
    storage_entities = [e.to_dict(view="storage") for e in entities]
    agent_blob = zstd_compressor.compress(msgpack.packb(_minify_graph_payload({"entities": agent_entities})))
    storage_blob = zstd_compressor.compress(msgpack.packb(_minify_graph_payload({"entities": storage_entities})))

    rel_bytes = zstd_compressor.compress(msgpack.packb([r.to_dict() for r in relationships]))

    # Build global manifest of exported symbols
    global_manifest = [
        {"name": ent.name, "id": ent.id, "type": ent.type.value}
        for ent in entities if ent.metadata.get("is_exported")
    ]

    # Calculate local hits from entity metadata
    local_hits: dict[str, Any] = {"rules_applied": 0, "entities_tagged": 0}
    rules_applied_set: set[str] = set()
    for ent in entities:
        if ent.metadata and ent.metadata.get("bsg.rules"):
            local_hits["entities_tagged"] += 1
            for rule_name in ent.metadata["bsg.rules"]:
                rules_applied_set.add(rule_name)
    local_hits["rules_applied"] = len(rules_applied_set)

    return hollow_bytes, rel_bytes, agent_blob, storage_blob, global_manifest, local_hits


def _enrich_cached_entities(
    entities: list[Entity],
    content: bytes,
    filepath: str,
) -> list[Entity]:
    """Reconstruct raw content, content hash, raw bytes, whitespace and hierarchy
    for cached entities in a single pass using ``Entity._evolve()``.

    Because the SQLite cache stores entities in the *agent* view (no raw bytes),
    we re-derive all byte-level attributes from the current file content on every
    cache hit.  This keeps the cache compact while still providing full fidelity
    on cache hits.

    Args:
        entities: Entities deserialized from the SQLite cache (no raw_content).
        content: Current file content bytes (freshly read from disk).
        filepath: Repo-relative file path for warning messages.

    Returns:
        List of enriched Entity objects in the same order as ``entities``.
    """
    from batho.utils.hash import compute_bytes_hash

    if not content:
        return entities

    content_len = len(content)
    ws_set = b" \t\n\r"

    # ------------------------------------------------------------------
    # Step 1: Byte-level enrichment (raw_content / raw_bytes / content_hash)
    # ------------------------------------------------------------------
    raw_data: list[tuple[str, str | None, bytes | None]] = []  # (decoded, c_hash, raw_bytes)
    for entity in entities:
        start_byte = min(max(0, entity.start_byte), content_len)
        end_byte = min(max(start_byte, entity.end_byte), content_len)
        raw_bytes_slice = content[start_byte:end_byte]

        try:
            decoded_content = raw_bytes_slice.decode("utf-8", errors="strict")
            stored_raw_bytes: bytes | None = None
        except UnicodeDecodeError as exc:
            logger.warning(
                "utf8_decode_fallback_in_cache",
                filepath=filepath,
                context=f"cached entity {entity.name}",
                error=str(exc),
                bytes_length=len(raw_bytes_slice),
            )
            decoded_content = raw_bytes_slice.decode("utf-8", errors="replace")
            stored_raw_bytes = raw_bytes_slice

        c_hash = compute_bytes_hash(raw_bytes_slice)
        raw_data.append((decoded_content, c_hash, stored_raw_bytes))

    # ------------------------------------------------------------------
    # Step 2: Whitespace resolution and containment hierarchy (O(N log N))
    # ------------------------------------------------------------------
    leading_list: list[str] = [""] * len(entities)
    trailing_list: list[str] = [""] * len(entities)
    semantic_indices: list[int] = []

    for idx, entity in enumerate(entities):
        if entity.type != EntityType.SYNTAX_GLUE:
            semantic_indices.append(idx)

    # Initialize maps for all cases
    parent_map: dict[str, str] = {}
    children_map: dict[str, list[str]] = {}
    sorted_sem: list[int] = []

    if semantic_indices:
        # Sort by start_byte for linear whitespace limit computation
        sorted_sem = sorted(
            semantic_indices,
            key=lambda i: (entities[i].start_byte, -entities[i].end_byte),
        )

        # Build position arrays for O(1) neighbor lookup
        sorted_starts: list[int] = []
        sorted_ends: list[int] = []
        sorted_to_orig: list[int] = []
        for sorted_idx, orig_idx in enumerate(sorted_sem):
            e = entities[orig_idx]
            start = min(max(0, e.start_byte), content_len)
            end = min(max(start, e.end_byte), content_len)
            sorted_starts.append(start)
            sorted_ends.append(end)
            sorted_to_orig.append(orig_idx)

        # Compute leading whitespace in single left-to-right pass
        # For each entity, left limit is the previous entity's end (if before this start)
        leading_ws_bytes: list[bytes] = [b""] * len(entities)
        for sorted_idx, orig_idx in enumerate(sorted_sem):
            start_byte = sorted_starts[sorted_idx]

            # Find left limit: previous entity that ends before this starts
            limit_left = 0
            if sorted_idx > 0:
                prev_end = sorted_ends[sorted_idx - 1]
                if prev_end <= start_byte:
                    limit_left = prev_end

            i = start_byte - 1
            while i >= limit_left and content[i] in ws_set:
                i -= 1
            leading_bytes = content[i + 1:start_byte]
            leading_ws_bytes[orig_idx] = leading_bytes
            leading_list[orig_idx] = leading_bytes.decode("utf-8", errors="replace")

        # Compute trailing whitespace in single right-to-left pass
        # For each entity, right limit is next entity's start minus its leading ws
        for sorted_idx in range(len(sorted_sem) - 1, -1, -1):
            orig_idx = sorted_to_orig[sorted_idx]
            end_byte = sorted_ends[sorted_idx]

            # Find right limit: next entity's effective start (start - leading_ws)
            limit_right = content_len
            if sorted_idx < len(sorted_sem) - 1:
                next_orig_idx = sorted_to_orig[sorted_idx + 1]
                next_start = sorted_starts[sorted_idx + 1]
                next_leading_len = len(leading_ws_bytes[next_orig_idx])
                next_effective_start = next_start - next_leading_len
                if next_effective_start >= end_byte:
                    limit_right = next_effective_start

            j = end_byte
            while j < limit_right and content[j] in ws_set:
                j += 1
            trailing_list[orig_idx] = content[end_byte:j].decode("utf-8", errors="replace")

    # Containment hierarchy via monotonic stack (reuse sorted_sem from above)
    # sorted_sem is already sorted by (start_byte, -end_byte), or empty if no semantic entities
    stack: list[int] = []

    for idx in sorted_sem:
        e = entities[idx]
        while stack:
            anc = entities[stack[-1]]
            if anc.start_byte <= e.start_byte and e.end_byte <= anc.end_byte:
                break
            stack.pop()
        if stack:
            parent_e = entities[stack[-1]]
            parent_map[e.id] = parent_e.id
            children_map.setdefault(parent_e.id, []).append(e.id)
        stack.append(idx)

    # ------------------------------------------------------------------
    # Step 3: Single _evolve() call per entity — one reconstruction pass
    # ------------------------------------------------------------------
    result: list[Entity] = []
    for idx, entity in enumerate(entities):
        decoded_content, c_hash, stored_raw_bytes = raw_data[idx]

        if entity.type == EntityType.SYNTAX_GLUE:
            result.append(entity._evolve(
                raw_content=decoded_content,
                content_hash=c_hash,
                raw_bytes=stored_raw_bytes,
                leading_whitespace="",
                trailing_whitespace="",
                children_order=[],
            ))
            continue

        p_id = entity.parent_id or parent_map.get(entity.id)
        c_order = children_map.get(entity.id, [])
        leading = leading_list[idx]
        trailing = trailing_list[idx]

        result.append(entity._evolve(
            raw_content=decoded_content,
            content_hash=c_hash,
            raw_bytes=stored_raw_bytes,
            leading_whitespace=leading,
            trailing_whitespace=trailing,
            parent_id=p_id,
            children_order=c_order,
        ))

    return result


def _process_file_worker_wrapper(args: tuple) -> Any:
    """Wrapper function to unpack arguments for pool map worker."""
    return process_file_single_pass_worker(*args)


def _initialize_worker(
    log_config: dict[str, Any] | None,
    cache_path: str | None,
    root_path: str | None = None,
    rules_config: dict[str, Any] | None = None,
    ast_cache_dir: str | None = None,
) -> None:
    """Apply configured logging, initialize cache, and pre-load BSG rules once per worker process."""
    global _WORKER_LOGGING_INITIALIZED, _WORKER_CACHE, _WORKER_RULES_CACHE, _WORKER_ROOT_PATH, _WORKER_ZSTD_COMPRESSOR

    import gc
    gc.set_threshold(50000, 50, 50)

    if not _WORKER_LOGGING_INITIALIZED:
        configure_logging(log_config or {})
        _WORKER_LOGGING_INITIALIZED = True

    if cache_path and _WORKER_CACHE is None:
        try:
            ast_dir = Path(ast_cache_dir) if ast_cache_dir else None
            _WORKER_CACHE = BathoCache(
                cache_path=cache_path,
                ast_cache_dir=ast_dir,
            )
        except Exception as exc:
            logger.warning("worker_cache_init_failed", cache_path=cache_path, error=str(exc))

    if root_path and rules_config and _WORKER_RULES_CACHE is None:
        try:
            from batho.modules.compression.rules import load_effective_rules
            _WORKER_RULES_CACHE, _ = load_effective_rules(rules_config, Path(root_path))
            _WORKER_ROOT_PATH = root_path
        except Exception as exc:
            logger.warning("worker_bsg_rules_init_failed", error=str(exc))

    # Initialize zstd compressor once per worker for reuse across files
    if _WORKER_ZSTD_COMPRESSOR is None:
        try:
            import zstandard as zstd
            _WORKER_ZSTD_COMPRESSOR = zstd.ZstdCompressor(level=3)
        except Exception as exc:
            logger.warning("worker_zstd_init_failed", error=str(exc))


# ---------------------------------------------------------------------------
# Worker function (must be picklable for multiprocessing)
# ---------------------------------------------------------------------------


def process_file_single_pass_worker(
    file_path: Path,
    filepath: str,
    current_mtime: float,
    size: int,
    cache_enabled: bool,
    cache_path: str,
    ttl_days: int,
    max_file_size_kb: int,
    bsg_cache_cfg: dict[str, Any],
    cache_variant: str | None = None,
    index_id: str | None = None,
    include_gaps: bool = False,
    package: dict | None = None,
    rules_config: dict[str, Any] | None = None,
    root_path: str | None = None,
    ast_cache_dir: str | None = None,
) -> tuple[str, str, bytes, bytes, bytes, bytes, list[dict], dict, dict] | None:
    """
    Worker function for parallel single-pass extraction.
    Returns: (filepath, content_hash, hollow_bytes, rel_bytes, agent_blob, storage_blob, global_manifest, file_security_audit, local_hits)
    - hollow_bytes: lightweight topology for graph (no raw_content/raw_bytes)
    - agent_blob: precompiled agent view for persistence
    - storage_blob: precompiled storage view for persistence
    - file_security_audit: per-file BSG audit fragment (empty dict if no rules applied)
    - local_hits: dict with keys "rules_applied" and "entities_tagged"
    """
    global _WORKER_CACHE, _WORKER_ZSTD_COMPRESSOR

    try:
        from batho.utils.hash import compute_bytes_hash
        import msgpack
        import zstandard as zstd
        from batho.core.schemas import PackageMetadata

        # Use worker-initialized compressor or create one if not available
        if _WORKER_ZSTD_COMPRESSOR is not None:
            zstd_compressor = _WORKER_ZSTD_COMPRESSOR
        else:
            zstd_compressor = zstd.ZstdCompressor(level=3)

        content = read_file_bytes(filepath, max_size_kb=max_file_size_kb, detect_binary=True)
        if content is None:
            return None
            
        content_hash = compute_bytes_hash(content)

        cache = None
        if cache_enabled:
            if _WORKER_CACHE is not None:
                cache = _WORKER_CACHE
            elif cache_path is not None:
                ast_dir = Path(ast_cache_dir) if ast_cache_dir else None
                cache = BathoCache(
                    cache_path=cache_path,
                    ast_cache_dir=ast_dir,
                )

        # Check AST cache for existing entities and relationships
        if cache_enabled and cache is not None:
            cached_result = cache.get_ast(filepath, content_hash, cache_variant)
            if cached_result is not None:
                cached_entities, cached_relationships = cached_result

                # Update entity file path to current location (handles renames/copies)
                cached_entities = _update_cached_entity_file(cached_entities, filepath)

                # Enrich cached entities with raw contents sliced from file bytes
                cached_entities = _enrich_cached_entities(
                    cached_entities, content, filepath
                )

                # Stamp index_id on cached entities if provided
                if index_id:
                    cached_entities = [
                        e._evolve(metadata={**dict(e.metadata or {}), "bsg.index_id": index_id})
                        for e in cached_entities
                    ]

                # Create file snapshot on cache hit when include_gaps is enabled.
                if include_gaps and cached_entities:
                    existing_snapshot = cache.get_file_snapshot(filepath)
                    if existing_snapshot is None:
                        _create_file_snapshot(filepath, content_hash, len(content), cached_entities, cache)

                # Serialize extraction results using shared helper
                hollow_bytes, rel_bytes, agent_blob, storage_blob, global_manifest, local_hits = _serialize_extraction_result(
                    cached_entities,
                    cached_relationships,
                    filepath,
                    content_hash,
                    zstd_compressor,
                    file_security_audit={},
                )

                local_hits["rules_loaded"] = len(_WORKER_RULES_CACHE) if _WORKER_RULES_CACHE else 0
                return (filepath, content_hash, hollow_bytes, rel_bytes, agent_blob, storage_blob, global_manifest, {}, local_hits)

        # Cache miss or cache disabled - parse the file
        from batho.modules.extraction.submodules.parser_factory.detector import default_detector
        from batho.modules.extraction.submodules.parser_factory.registry import get_extractor as _registry_get_extractor

        suffix = file_path.suffix.lower()
        file_extractor: ASTExtractor | object | None = default_detector.get_extractor(
            file_path, content
        ) or _registry_get_extractor(suffix)
        if file_extractor is None:
            if cache_enabled and cache is not None:
                _snap = FileSnapshot.create_opaque(
                    file_path=filepath,
                    content=content,
                    file_size=len(content),
                )
                cache.set_file_snapshot(_snap)
            return None  # opaque file — no extractor

        if not isinstance(file_extractor, ASTExtractor):
            return None

        pkg = PackageMetadata.from_dict(package) if package else None
        entities, relationships = file_extractor.parse_file(
            filepath,
            content,
            index_id=index_id,
            include_gaps=include_gaps,
            package=pkg,
        )

        # Apply BSG rules per-file in parallel (before serialization)
        file_security_audit: dict[str, Any] = {}
        local_hits = {"rules_applied": 0, "entities_tagged": 0, "rules_loaded": 0}
        if _WORKER_RULES_CACHE:
            try:
                from batho.modules.compression.rules import apply_bsg_rules_to_entities
                entities, file_security_audit = apply_bsg_rules_to_entities(
                    entities=entities,
                    relationships=relationships,
                    rules=_WORKER_RULES_CACHE,
                    root_path=_WORKER_ROOT_PATH or str(file_path.parent),
                    file_path=filepath,
                )
                rules_applied_set = set()
                for ent in entities:
                    if ent.metadata and ent.metadata.get("bsg.rules"):
                        local_hits["entities_tagged"] += 1
                        for rule_name in ent.metadata["bsg.rules"]:
                            rules_applied_set.add(rule_name)
                local_hits["rules_applied"] = len(rules_applied_set)
            except Exception as exc:
                logger.warning(
                    "worker_bsg_rules_failed",
                    filepath=filepath,
                    error=str(exc),
                )

        # Cache the extracted entities and relationships if cache is enabled
        if cache_enabled and entities and cache is not None:
            cache.set_ast(
                filepath,
                content_hash,
                entities,
                relationships or [],
                current_mtime,
                size,
                ttl_days,
                variant=cache_variant,
            )

            # Create file snapshot when include_gaps is enabled
            if include_gaps:
                _create_file_snapshot(filepath, content_hash, size, entities, cache)

        # Serialize extraction results using shared helper
        hollow_bytes, rel_bytes, agent_blob, storage_blob, global_manifest, local_hits = _serialize_extraction_result(
            entities,
            relationships or [],
            filepath,
            content_hash,
            zstd_compressor,
            file_security_audit=file_security_audit,
        )
        local_hits["rules_loaded"] = len(_WORKER_RULES_CACHE) if _WORKER_RULES_CACHE else 0

        return (filepath, content_hash, hollow_bytes, rel_bytes, agent_blob, storage_blob, global_manifest, file_security_audit, local_hits)
    except Exception as exc:
        logger.warning(
            "worker_single_pass_parse_failed",
            filepath=filepath,
            error=str(exc),
        )
        return None



# ---------------------------------------------------------------------------
# Pipeline orchestration
# ---------------------------------------------------------------------------


def _calculate_optimal_chunk_size(
    sizes: list[int],
    num_workers: int,
) -> int:
    """
    Calculate optimal chunk size based on file sizes for better load balancing.
    
    Args:
        sizes: List of file sizes in bytes (pre-collected to avoid redundant stat calls)
        num_workers: Number of worker processes
    """
    if not sizes or num_workers <= 0:
        return 50
    
    mean_size = sum(sizes) / len(sizes)
    if mean_size > 0:
        variance = sum((s - mean_size) ** 2 for s in sizes) / len(sizes)
        std_dev = variance ** 0.5
        cv = std_dev / mean_size
    else:
        cv = 0
    
    if cv > 0.5:
        base_chunk = 15
    elif cv > 0.2:
        base_chunk = 35
    else:
        base_chunk = 70
    
    worker_factor = max(1, num_workers // 4)
    chunk_size = max(5, base_chunk // worker_factor)
    
    min_chunks = num_workers * 2
    if len(sizes) < min_chunks:
        chunk_size = max(1, len(sizes) // min_chunks)
    
    return min(chunk_size, 200)


def extract_and_emit_parallel(
    candidates: list[tuple[Path, str]],
    configured_max_file_size_kb: int,
    bsg_cfg: dict[str, Any],
    package_dict: dict | None = None,
    index_id: str | None = None,
    include_gaps: bool = False,
    result_callback: Callable[[tuple], None] | None = None,
    ast_cache_dir: str | None = None,
) -> tuple[list[tuple[str, bytes, bytes, list[dict]]], int, dict[str, Any]]:
    """
    Process files in parallel to parse and emit compressed binary representations 
    along with lightweight global manifests of exported definitions.
    """
    bsg_parallel_cfg = bsg_cfg.get("parallel", {})
    parallel_enabled = bsg_parallel_cfg.get("enabled", True)
    max_workers = bsg_parallel_cfg.get("max_workers", 16)

    bsg_cache_cfg = bsg_cfg.get("cache", {})
    cache_enabled = bsg_cache_cfg.get("enabled", True)
    cache_path = bsg_cache_cfg.get("path") or None
    ttl_days = bsg_cache_cfg.get("ttl_days", 30)
    
    from batho.modules.storage.cache.unified_cache import build_ast_cache_variant as _build_ast_cache_variant
    cache_variant = _build_ast_cache_variant(
        include_gaps=include_gaps,
        parsing_config=bsg_cfg.get("parsing", {}),
    )

    rules_config = bsg_cfg.get("rules", {})
    root_path = bsg_cfg.get("root_path")

    raw_results = []
    error_count = 0

    if not parallel_enabled or len(candidates) == 0:
        logger.info("parallel_disabled_or_empty_candidates")
        for file_path, filepath in candidates:
            try:
                stat_info = file_path.stat()
                size = stat_info.st_size
                current_mtime = stat_info.st_mtime
            except OSError:
                error_count += 1
                continue

            if size > configured_max_file_size_kb * 1024:
                continue

            res = process_file_single_pass_worker(
                file_path,
                filepath,
                current_mtime,
                size,
                cache_enabled,
                cache_path,
                ttl_days,
                configured_max_file_size_kb,
                bsg_cache_cfg,
                cache_variant=cache_variant,
                index_id=index_id,
                include_gaps=include_gaps,
                package=package_dict,
                ast_cache_dir=ast_cache_dir,
            )
            if res is None:
                error_count += 1
            else:
                raw_results.append(res)
                if result_callback is not None:
                    result_callback(res)
    else:
        cpu_count = os.cpu_count() or 4
        actual_workers = min(cpu_count, max_workers, len(candidates))
        actual_workers = max(1, actual_workers)
        
        # Collect sizes in a single pass to avoid redundant stat calls
        candidate_sizes: list[int] = []
        work_items = []
        for file_path, filepath in candidates:
            try:
                stat_info = file_path.stat()
                size = stat_info.st_size
                current_mtime = stat_info.st_mtime
            except OSError:
                continue
            if size > configured_max_file_size_kb * 1024:
                continue
            candidate_sizes.append(size)
            work_items.append((
                file_path,
                filepath,
                current_mtime,
                size,
                cache_enabled,
                cache_path,
                ttl_days,
                configured_max_file_size_kb,
                bsg_cache_cfg,
                cache_variant,
                index_id,
                include_gaps,
                package_dict,
                ast_cache_dir,
            ))
        
        chunk_size = _calculate_optimal_chunk_size(candidate_sizes, actual_workers)

        logger.info(
            "parallel_single_pass_start",
            workers=actual_workers,
            files=len(work_items),
            chunk_size=chunk_size,
        )

        try:
            import multiprocessing as _mp
            from batho.core.config import get_config_cached
            worker_log_config = dict(get_config_cached().get("logging", {}))
            ctx = _mp.get_context("spawn")
            with ctx.Pool(
                processes=actual_workers,
                initializer=_initialize_worker,
                initargs=(worker_log_config, cache_path, root_path, rules_config, ast_cache_dir),
            ) as pool:
                for res in pool.imap_unordered(
                    _process_file_worker_wrapper, work_items, chunksize=chunk_size
                ):
                    raw_results.append(res)
                    if result_callback is not None and res is not None:
                        result_callback(res)
        except Exception as exc:
            logger.warning("parallel_extract_and_emit_failed_fallback_sequential", error=str(exc))
            raw_results = []
            error_count = 0
            for item in work_items:
                res = process_file_single_pass_worker(*item)
                if res is None:
                    error_count += 1
                else:
                    raw_results.append(res)
                    if result_callback is not None:
                        result_callback(res)

    valid_results = []
    from collections import defaultdict
    merged_audit = {
        "schema_version": "interception-stats.v1",
        "plugins": defaultdict(lambda: {"plugin_id": "", "name": "", "interceptions": 0})
    }

    for r in raw_results:
        if r is None:
            error_count += 1
        else:
            # Merge file security audit fragment
            if len(r) > 7 and r[7]:
                for plugin_id, data in r[7].get("plugins", {}).items():
                    merged_audit["plugins"][plugin_id]["plugin_id"] = plugin_id
                    merged_audit["plugins"][plugin_id]["name"] = data.get("name", "")
                    merged_audit["plugins"][plugin_id]["interceptions"] += data.get("interceptions", 0)
            local_hits = r[8] if len(r) > 8 else {"rules_applied": 0, "entities_tagged": 0}
            valid_results.append((r[0], r[1], r[2], r[3], r[4], r[5], r[6], local_hits))

    merged_audit["plugins"] = dict(merged_audit["plugins"])
    return valid_results, error_count, merged_audit


