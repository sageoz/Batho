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

from batho.context.cache import ASTCache
from batho.context.extractor import ASTExtractor
from batho.context.schema import Entity, Relationship
from batho.utils.file_io import _read_file_content
from batho.utils.logging import configure_logging, get_logger

logger = get_logger(__name__, component="pipeline")
_WORKER_LOGGING_INITIALIZED = False


def _initialize_worker_logging(log_config: dict[str, Any] | None) -> None:
    """Apply configured logging once per worker process."""

    global _WORKER_LOGGING_INITIALIZED

    if _WORKER_LOGGING_INITIALIZED:
        return

    configure_logging(log_config or {})
    _WORKER_LOGGING_INITIALIZED = True


# ---------------------------------------------------------------------------
# Worker function (must be picklable for multiprocessing)
# ---------------------------------------------------------------------------


def process_file_worker(
    file_path: Path,
    filepath: str,
    content: bytes,
    content_hash: str,
    current_mtime: float,
    size: int,
    cache_enabled: bool,
    cache_path: str,
    ttl_days: int,
    max_file_size_kb: int,
    bsg_cache_cfg: dict[str, Any],
    snapshot_id: str | None = None,
) -> tuple[str, list[Entity], list[Relationship], bool] | None:
    """
    Worker function for parallel file processing.

    Each worker instantiates its own tree-sitter Language and parser objects
    since they are not picklable and cannot be shared across processes.

    Args:
        file_path: Absolute path to the file.
        filepath: Repository-relative path for logging.
        content: File content as bytes.
        content_hash: SHA-256 hash of file content.
        current_mtime: File modification time.
        size: File size in bytes.
        cache_enabled: Whether AST cache is enabled.
        cache_path: Path to AST cache database.
        ttl_days: Cache TTL in days.
        max_file_size_kb: Maximum file size in KB.
        bsg_cache_cfg: BSG cache configuration dict.

    Returns:
        Tuple of (filepath, entities, relationships, cached_hit) or None on error.
    """
    try:
        # Check AST cache for existing entities
        if cache_enabled:
            cache = ASTCache(cache_path=cache_path)
            cached_entities = cache.get_cached_entities(
                filepath, content_hash, current_mtime, size
            )
            if cached_entities is not None:
                # Cache hit - stamp snapshot_id on cached entities if provided
                if snapshot_id:
                    stamped_entities = []
                    for entity in cached_entities:
                        metadata = dict(entity.metadata or {})
                        metadata["bsg.snapshot_id"] = snapshot_id
                        stamped_entity = Entity(
                            type=entity.type,
                            name=entity.name,
                            file=entity.file,
                            start_line=entity.start_line,
                            end_line=entity.end_line,
                            start_byte=entity.start_byte,
                            end_byte=entity.end_byte,
                            signature=entity.signature,
                            metadata=metadata,
                            parent_id=entity.parent_id,
                        )
                        stamped_entities.append(stamped_entity)
                    return (filepath, stamped_entities, [], True)
                return (filepath, cached_entities, [], True)

        # Cache miss or cache disabled - parse the file
        from .languages.detector import default_detector
        from .languages.registry import get_extractor as _registry_get_extractor

        suffix = file_path.suffix.lower()
        file_extractor: ASTExtractor | object | None = default_detector.get_extractor(
            file_path, content
        ) or _registry_get_extractor(suffix)
        if file_extractor is None:
            return None

        if not isinstance(file_extractor, ASTExtractor):
            return None

        if snapshot_id is None:
            entities, relationships = file_extractor.parse_file(filepath, content)
        else:
            try:
                entities, relationships = file_extractor.parse_file(
                    filepath,
                    content,
                    snapshot_id=snapshot_id,
                )
            except TypeError:
                entities, relationships = file_extractor.parse_file(filepath, content)

        # Cache the extracted entities if cache is enabled
        if cache_enabled:
            cache = ASTCache(cache_path=cache_path)
            cache.cache_entities(
                filepath, content_hash, entities, current_mtime, size, ttl_days
            )

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


def build_graph_parallel(
    candidates: list[tuple[Path, str]],
    configured_max_file_size_kb: int,
    bsg_cfg: dict[str, Any],
    extractor: ASTExtractor | None = None,
    snapshot_id: str | None = None,
) -> tuple[list[tuple[str, list[Entity], list[Relationship], bool]], int]:
    """
    Process files in parallel using multiprocessing.Pool.

    Args:
        candidates: List of (file_path, filepath) tuples to process.
        configured_max_file_size_kb: Maximum file size in KB.
        bsg_cfg: BSG configuration dict.
        extractor: Optional ASTExtractor instance (for single-extractor mode).

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
    cache_path = bsg_cache_cfg.get("path", "~/.batho/ast_cache.db")
    ttl_days = bsg_cache_cfg.get("ttl_days", 30)

    if not parallel_enabled:
        # Fallback to sequential processing
        logger.info("parallel_disabled", reason="config")
        return build_graph_sequential(
            candidates,
            configured_max_file_size_kb,
            bsg_cfg,
            extractor,
            snapshot_id=snapshot_id,
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

    logger.info(
        "parallel_start",
        workers=actual_workers,
        files=len(candidates),
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

        content = _read_file_content(filepath, configured_max_file_size_kb)
        if content is None:
            continue

        from batho.utils.hash import compute_bytes_hash

        content_hash = compute_bytes_hash(content)

        work_items.append(
            (
                file_path,
                filepath,
                content,
                content_hash,
                current_mtime,
                size,
                cache_enabled,
                cache_path,
                ttl_days,
                configured_max_file_size_kb,
                bsg_cache_cfg,
                snapshot_id,
            )
        )

    # Use multiprocessing for parallel processing.
    #
    # We explicitly use the "spawn" start method instead of the platform
    # default (fork on Linux). Forking from a multi-threaded Python process
    # (e.g. when the indexer is invoked concurrently from multiple threads,
    # as in the parallel-processing performance test) can deadlock the
    # worker children because they inherit locked mutexes from threads that
    # no longer exist in the child. "spawn" starts a fresh interpreter and
    # is immune to this hazard at the cost of slightly slower pool startup.
    try:
        import multiprocessing as _mp

        from batho.config import get_config_cached

        worker_log_config = dict(get_config_cached().get("logging", {}))
        ctx = _mp.get_context("spawn")
        with ctx.Pool(
            processes=actual_workers,
            initializer=_initialize_worker_logging,
            initargs=(worker_log_config,),
        ) as pool:
            results = pool.starmap(
                process_file_worker, work_items, chunksize=chunk_size
            )
    except ImportError:
        logger.warning("multiprocessing_unavailable", fallback="sequential")
        return build_graph_sequential(
            candidates,
            configured_max_file_size_kb,
            bsg_cfg,
            extractor,
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
    snapshot_id: str | None = None,
) -> tuple[list[tuple[str, list[Entity], list[Relationship], bool]], int]:
    """
    Process files sequentially (fallback when multiprocessing unavailable).

    Args:
        candidates: List of (file_path, filepath) tuples to process.
        configured_max_file_size_kb: Maximum file size in KB.
        bsg_cfg: BSG configuration dict.
        extractor: Optional ASTExtractor instance.

    Returns:
        Tuple of (results list, error count).
    """
    from batho.utils.hash import compute_bytes_hash

    bsg_cache_cfg = bsg_cfg.get("cache", {})
    cache_enabled = bsg_cache_cfg.get("enabled", True)
    cache_path = bsg_cache_cfg.get("path", "~/.batho/ast_cache.db")
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

        content = _read_file_content(filepath, configured_max_file_size_kb)
        if content is None:
            errors += 1
            continue

        content_hash = compute_bytes_hash(content)

        # Process the file using the worker function logic
        result = process_file_worker(
            file_path,
            filepath,
            content,
            content_hash,
            current_mtime,
            size,
            cache_enabled,
            cache_path,
            ttl_days,
            configured_max_file_size_kb,
            bsg_cache_cfg,
            snapshot_id=snapshot_id,
        )

        if result is None:
            errors += 1
        else:
            results.append(result)

    return results, errors
