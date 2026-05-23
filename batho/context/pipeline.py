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

import os
from pathlib import Path
from typing import Any

from batho.context.unified_cache import BathoCache
from batho.context.extractor import ASTExtractor
from batho.context.schema import Entity, EntityType, FileSnapshot, Relationship
from batho.utils.file_io import read_file_bytes
from batho.utils.hash import _is_binary
from batho.utils.logging import configure_logging, get_logger

logger = get_logger(__name__, component="pipeline")
_WORKER_LOGGING_INITIALIZED = False
_WORKER_CACHE: BathoCache | None = None


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


def _initialize_worker(log_config: dict[str, Any] | None, cache_path: str | None = None) -> None:
    """Apply configured logging and initialize cache once per worker process."""
    global _WORKER_LOGGING_INITIALIZED, _WORKER_CACHE

    if not _WORKER_LOGGING_INITIALIZED:
        configure_logging(log_config or {})
        _WORKER_LOGGING_INITIALIZED = True

    if cache_path and _WORKER_CACHE is None:
        try:
            _WORKER_CACHE = BathoCache(cache_path=cache_path)
        except Exception as exc:
            logger.warning("worker_cache_init_failed", cache_path=cache_path, error=str(exc))


def _warmup_worker_cache(cache_path: str, file_hashes: list[tuple[str, str]]) -> int:
    """
    Pre-warm the worker cache with frequently accessed files.
    
    Args:
        cache_path: Path to the cache database
        file_hashes: List of (file_path, content_hash) tuples to pre-load
        
    Returns:
        Number of entries successfully warmed up
    """
    global _WORKER_CACHE
    
    if _WORKER_CACHE is None:
        try:
            _WORKER_CACHE = BathoCache(cache_path=cache_path)
        except Exception:
            return 0
    
    warmed = 0
    for file_path, content_hash in file_hashes:
        try:
            result = _WORKER_CACHE.get_ast(content_hash)
            if result is not None:
                warmed += 1
        except Exception:
            pass
    return warmed


def _get_worker_cache_stats() -> dict[str, Any]:
    """Get statistics about the worker cache for monitoring."""
    global _WORKER_CACHE
    
    if _WORKER_CACHE is None:
        return {"initialized": False}
    
    try:
        from batho.context.unified_cache import BathoCache
        # Access internal stats if available
        return {
            "initialized": True,
            "cache_path": str(_WORKER_CACHE._path),
        }
    except Exception:
        return {"initialized": True, "error": "stats_unavailable"}


# ---------------------------------------------------------------------------
# Worker function (must be picklable for multiprocessing)
# ---------------------------------------------------------------------------


def process_file_worker(
    file_path: Path,
    filepath: str,
    current_mtime: float,
    size: int,
    cache_enabled: bool,
    cache_path: str,
    ttl_days: int,
    max_file_size_kb: int,
    bsg_cache_cfg: dict[str, Any],
    index_id: str | None = None,
    include_gaps: bool = False,
) -> tuple[str, list[Entity], list[Relationship], bool] | None:
    """
    Worker function for parallel file processing.

    Reads file bytes and computes hash inside the worker to reduce pickle traffic.
    Uses a persisted per-worker BathoCache if available.
    """
    global _WORKER_CACHE

    try:
        # Step 1: Read content and compute hash inside the worker (reduces pickle traffic)
        from batho.utils.hash import compute_bytes_hash
        
        content = read_file_bytes(filepath, max_size_kb=max_file_size_kb, detect_binary=True)
        if content is None:
            return None
            
        content_hash = compute_bytes_hash(content)

        cache = None
        if cache_enabled:
            if _WORKER_CACHE is not None:
                cache = _WORKER_CACHE
            elif cache_path is not None:
                cache = BathoCache(cache_path=cache_path)

        # Check AST cache for existing entities and relationships
        if cache_enabled and cache is not None:
            cached_result = cache.get_ast(content_hash)
            if cached_result is not None:
                cached_entities, cached_relationships = cached_result

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
                # Only create if snapshot doesn't already exist to avoid staleness.
                if include_gaps and cached_entities:
                    existing_snapshot = cache.get_file_snapshot(filepath)
                    if existing_snapshot is None:
                        _create_file_snapshot(filepath, content_hash, len(content), cached_entities, cache)

                return (filepath, cached_entities, cached_relationships, True)

        # Cache miss or cache disabled - parse the file
        from .languages.detector import default_detector
        from .languages.registry import get_extractor as _registry_get_extractor

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

        if index_id is None:
            try:
                entities, relationships = file_extractor.parse_file(
                    filepath, content, include_gaps=include_gaps
                )
            except TypeError:
                entities, relationships = file_extractor.parse_file(
                    filepath, content
                )
        else:
            try:
                entities, relationships = file_extractor.parse_file(
                    filepath,
                    content,
                    index_id=index_id,
                    include_gaps=include_gaps,
                )
            except TypeError:
                try:
                    entities, relationships = file_extractor.parse_file(
                        filepath, content, index_id=index_id
                    )
                except TypeError:
                    entities, relationships = file_extractor.parse_file(
                        filepath, content
                    )

        # Cache the extracted entities and relationships if cache is enabled
        # Skip caching empty results to avoid re-parsing files that legitimately have no entities
        if cache_enabled and entities and cache is not None:
            cache.set_ast(
                content_hash,
                filepath,
                entities,
                relationships or [],
                current_mtime,
                size,
                ttl_days,
            )

            # Create file snapshot when include_gaps is enabled
            if include_gaps:
                _create_file_snapshot(filepath, content_hash, size, entities, cache)

        return (filepath, entities, relationships, False)
    except Exception as exc:
        logger.warning(
            "worker_parse_failed",
            filepath=filepath,
            error=str(exc),
        )
        return None


# ---------------------------------------------------------------------------
# Pipeline orchestration
# ---------------------------------------------------------------------------


def _calculate_optimal_chunk_size(
    candidates: list[tuple[Path, str]],
    num_workers: int,
) -> int:
    """
    Calculate optimal chunk size based on file sizes for better load balancing.
    
    Uses file size distribution to determine chunk size that balances
    work across workers. Smaller chunks for varied sizes, larger for uniform.
    
    Args:
        candidates: List of (file_path, filepath) tuples
        num_workers: Number of worker processes
        
    Returns:
        Optimal chunk size for the workload
    """
    if not candidates or num_workers <= 0:
        return 50
    
    # Collect file sizes
    sizes: list[int] = []
    for file_path, _ in candidates:
        try:
            sizes.append(file_path.stat().st_size)
        except OSError:
            sizes.append(0)
    
    if not sizes:
        return 50
    
    # Calculate coefficient of variation (CV) for size distribution
    # High CV = varied sizes = smaller chunks for better load balance
    # Low CV = uniform sizes = larger chunks for efficiency
    mean_size = sum(sizes) / len(sizes)
    if mean_size > 0:
        variance = sum((s - mean_size) ** 2 for s in sizes) / len(sizes)
        std_dev = variance ** 0.5
        cv = std_dev / mean_size  # Coefficient of variation
    else:
        cv = 0
    
    # Base chunk size on CV and number of workers
    # CV > 0.5: varied sizes -> smaller chunks (10-20)
    # CV 0.2-0.5: moderate variation -> medium chunks (20-50)
    # CV < 0.2: uniform sizes -> larger chunks (50-100)
    if cv > 0.5:
        base_chunk = 15
    elif cv > 0.2:
        base_chunk = 35
    else:
        base_chunk = 70
    
    # Adjust based on worker count and total files
    # More workers need smaller chunks for better load balancing
    worker_factor = max(1, num_workers // 4)
    chunk_size = max(5, base_chunk // worker_factor)
    
    # Ensure we have enough chunks to keep workers busy
    min_chunks = num_workers * 2
    if len(candidates) < min_chunks:
        chunk_size = max(1, len(candidates) // min_chunks)
    
    return min(chunk_size, 200)  # Cap at 200 to avoid memory issues


def build_graph_parallel(
    candidates: list[tuple[Path, str]],
    configured_max_file_size_kb: int,
    bsg_cfg: dict[str, Any],
    extractor: ASTExtractor | None = None,
    index_id: str | None = None,
    include_gaps: bool = False,
) -> tuple[list[tuple[str, list[Entity], list[Relationship], bool]], int]:
    """
    Process files in parallel using multiprocessing.Pool.

    Args:
        candidates: List of (file_path, filepath) tuples to process.
        configured_max_file_size_kb: Maximum file size in KB.
        bsg_cfg: BSG configuration dict.
        extractor: Optional ASTExtractor instance (for single-extractor mode).
        index_id: Optional index ID to stamp on entities.
        include_gaps: When True, emit SYNTAX_GLUE entities for full byte coverage.

    Returns:
        Tuple of (results list, error count).
    """
    # Get parallel configuration
    bsg_parallel_cfg = bsg_cfg.get("parallel", {})
    parallel_enabled = bsg_parallel_cfg.get("enabled", True)
    max_workers = bsg_parallel_cfg.get("max_workers", 16)
    chunk_size = bsg_parallel_cfg.get("chunk_size", 50)

    # Get cache configuration
    bsg_cache_cfg = bsg_cfg.get("cache", {})
    cache_enabled = bsg_cache_cfg.get("enabled", True)
    cache_path = bsg_cache_cfg.get("path", ".batho")
    ttl_days = bsg_cache_cfg.get("ttl_days", 30)

    if not parallel_enabled:
        # Fallback to sequential processing
        logger.info("parallel_disabled", reason="config")
        return build_graph_sequential(
            candidates,
            configured_max_file_size_kb,
            bsg_cfg,
            extractor,
            index_id=index_id,
            include_gaps=include_gaps,
        )

    # Calculate worker count
    cpu_count = os.cpu_count() or 4
    actual_workers = min(cpu_count, max_workers)
    actual_workers = min(actual_workers, len(candidates))

    # Ensure at least 1 worker if there are files to process
    if actual_workers == 0 and len(candidates) > 0:
        actual_workers = 1

    # If no files to process, return early
    if len(candidates) == 0:
        return [], 0

    # Dynamic chunk sizing based on file sizes for better load balancing
    chunk_size = _calculate_optimal_chunk_size(candidates, actual_workers)

    logger.info(
        "parallel_start",
        workers=actual_workers,
        files=len(candidates),
        chunk_size=chunk_size,
    )

    # Prepare work items
    work_items = []
    for file_path, filepath in candidates:
        try:
            stat_info = file_path.stat()
            size = stat_info.st_size
            current_mtime = stat_info.st_mtime
        except OSError:
            continue

        if size > configured_max_file_size_kb * 1024:
            logger.debug("skipping_large_file", filepath=filepath, size_kb=size // 1024)
            continue

        # NOTICE: We no longer read file bytes or compute hashes in the parent process.
        # This significantly reduces pickle overhead and memory pressure on large repos.

        work_items.append(
            (
                file_path,
                filepath,
                current_mtime,
                size,
                cache_enabled,
                cache_path,
                ttl_days,
                configured_max_file_size_kb,
                bsg_cache_cfg,
                index_id,
                include_gaps,
            )
        )

    # Use multiprocessing for parallel processing.
    try:
        import multiprocessing as _mp

        from batho.config import get_config_cached

        worker_log_config = dict(get_config_cached().get("logging", {}))
        ctx = _mp.get_context("spawn")
        with ctx.Pool(
            processes=actual_workers,
            initializer=_initialize_worker,
            initargs=(worker_log_config, cache_path),
        ) as pool:
            results = pool.starmap(
                process_file_worker, work_items, chunksize=chunk_size
            )
    except (ImportError, OSError, RuntimeError) as exc:
        # Fallback to sequential processing:
        # - ImportError: multiprocessing module unavailable
        # - OSError: pool startup failure (e.g., spawn process resource limits)
        # - RuntimeError: pool startup or communication failure
        logger.warning(
            "multiprocessing_unavailable_or_failed",
            fallback="sequential",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return build_graph_sequential(
            candidates,
            configured_max_file_size_kb,
            bsg_cfg,
            extractor,
            index_id=index_id,
            include_gaps=include_gaps,
        )

    # Filter out None results (errors)
    valid_results = [r for r in results if r is not None]
    error_count = len(results) - len(valid_results)

    logger.info(
        "parallel_complete",
        total_files=len(work_items),
        successful=len(valid_results),
        errors=error_count,
    )

    return valid_results, error_count


def build_graph_sequential(
    candidates: list[tuple[Path, str]],
    configured_max_file_size_kb: int,
    bsg_cfg: dict[str, Any],
    extractor: ASTExtractor | None = None,
    index_id: str | None = None,
    include_gaps: bool = False,
) -> tuple[list[tuple[str, list[Entity], list[Relationship], bool]], int]:
    """
    Process files sequentially (fallback when multiprocessing unavailable).
    """
    bsg_cache_cfg = bsg_cfg.get("cache", {})
    cache_enabled = bsg_cache_cfg.get("enabled", True)
    cache_path = bsg_cache_cfg.get("path", ".batho")
    ttl_days = bsg_cache_cfg.get("ttl_days", 30)

    results = []
    errors = 0

    for file_path, filepath in candidates:
        try:
            stat_info = file_path.stat()
            size = stat_info.st_size
            current_mtime = stat_info.st_mtime
        except OSError:
            errors += 1
            continue

        if size > configured_max_file_size_kb * 1024:
            logger.debug("skipping_large_file", filepath=filepath, size_kb=size // 1024)
            continue

        # Process the file using the worker function logic (it now handles its own reading)
        result = process_file_worker(
            file_path,
            filepath,
            current_mtime,
            size,
            cache_enabled,
            cache_path,
            ttl_days,
            configured_max_file_size_kb,
            bsg_cache_cfg,
            index_id=index_id,
            include_gaps=include_gaps,
        )

        if result is None:
            errors += 1
        else:
            results.append(result)

    return results, errors
