"""
backend/context/codegraph.py — Production Code Graph Indexer.

Improvements over prototype:
- SQLite-based AST entity cache (stores extracted entities, not just file state)
- AST entity caching: skips unchanged files entirely (no re-parsing)
- Parallel file extraction using multiprocessing (CPU-bound, bypasses GIL)
- Per-file exception isolation: one bad file never aborts the whole scan
- Binary file detection and size guard
- pathspec-based .gitignore / .bathoignore support
- Synchronous (no async): cleaner for CLI and daemon usage

The InMemoryGraph is returned inline — no external persistence needed for
Batho's Markdown-based memory model.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional

import batho.utils.memory_monitor
from batho.config import get_config_cached
from batho.utils.file_io import read_file_bytes
from batho.utils.hash import compute_bytes_hash
from batho.utils.ignore import is_ignored, load_ignore_spec
from batho.utils.logging import get_logger
from batho.utils.memory_monitor import force_garbage_collection, memory_monitor

from .cache import ASTCache
from .extractor import ASTExtractor
from .pipeline import build_graph_parallel
from .schema import Entity, EntityType, Relationship, RelationshipType
from .symbol_index import SymbolIndex

# Binary detection is now handled in batho.utils.file_io


# ---------------------------------------------------------------------------
# Ignore pattern support — re-export from centralized utility
# ---------------------------------------------------------------------------

# Re-export for backward compatibility within this module
_load_ignore_spec = load_ignore_spec
_is_ignored = is_ignored


# ---------------------------------------------------------------------------
# InMemoryGraph
# ---------------------------------------------------------------------------


class InMemoryGraph:
    """
    In-memory graph of code entities and their relationships.

    Stores all entities and relationships extracted from the codebase AST.
    Uses lazy adjacency index building: the index is built on the first
    call to neighbors() and invalidated whenever a relationship is added.
    """

    def __init__(
        self,
        entities: dict[str, Entity] | None = None,
        relationships: list[Relationship] | None = None,
    ) -> None:
        self.entities: dict[str, Entity] = entities if entities is not None else {}
        self.relationships: list[Relationship] = (
            relationships if relationships is not None else []
        )
        self._adj_out: dict[str, list[str]] | None = None
        self._adj_in: dict[str, list[str]] | None = None

    def add_entity(self, entity: Entity) -> None:
        self.entities[entity.id] = entity

    def add_relationship(self, relationship: Relationship) -> None:
        self.relationships.append(relationship)
        self._adj_out = None
        self._adj_in = None

    def get_entity(self, entity_id: str) -> Entity | None:
        return self.entities.get(entity_id)

    def _build_index(self) -> None:
        out: dict[str, list[str]] = {}
        in_: dict[str, list[str]] = {}
        for rel in self.relationships:
            out.setdefault(rel.source_id, []).append(rel.target_id)
            in_.setdefault(rel.target_id, []).append(rel.source_id)
        self._adj_out = out
        self._adj_in = in_

    def neighbors(self, entity_id: str, direction: str = "out") -> list[str]:
        if self._adj_out is None:
            self._build_index()
        if direction == "out":
            return list(self._adj_out.get(entity_id, []))  # type: ignore[union-attr]
        if direction == "in":
            return list(self._adj_in.get(entity_id, []))  # type: ignore[union-attr]
        out = self._adj_out.get(entity_id, [])  # type: ignore[union-attr]
        in_ = self._adj_in.get(entity_id, [])  # type: ignore[union-attr]
        return list(dict.fromkeys(out + in_))

    def entities_by_file(self, file_path: str) -> list[Entity]:
        return [e for e in self.entities.values() if e.file == file_path]

    def entities_by_type(self, entity_type: EntityType) -> list[Entity]:
        return [e for e in self.entities.values() if e.type == entity_type]

    def root_entities(self) -> list[Entity]:
        return [e for e in self.entities.values() if e.parent_id is None]

    def stats(self) -> dict[str, Any]:
        files: set[str] = set()
        entity_types: Counter[str] = Counter()
        for entity in self.entities.values():
            files.add(entity.file)
            entity_types[str(entity.type)] += 1
        return {
            "entity_count": len(self.entities),
            "relationship_count": len(self.relationships),
            "file_count": len(files),
            "entity_types": dict(entity_types),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "entities": [e.to_dict() for e in self.entities.values()],
            "entities_by_id": {eid: e.to_dict() for eid, e in self.entities.items()},
            "relationships": [r.to_dict() for r in self.relationships],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InMemoryGraph":
        graph = cls()
        for e_data in data.get("entities_by_id", {}).values():
            graph.add_entity(Entity.from_dict(e_data))
        for r_data in data.get("relationships", []):
            graph.add_relationship(Relationship.from_dict(r_data))
        return graph

    def __len__(self) -> int:
        return len(self.entities)

    def __contains__(self, entity_id: str) -> bool:
        return entity_id in self.entities

    def __repr__(self) -> str:
        return f"InMemoryGraph(entities={len(self.entities)}, relationships={len(self.relationships)})"


# ---------------------------------------------------------------------------
# IncrementalGraphUpdater
# ---------------------------------------------------------------------------


class IncrementalGraphUpdater:
    """
    Handles incremental updates to the InMemoryGraph for modified files.

    Provides methods to update entities for changed files without full rebuild.
    Maintains graph consistency and handles edge cases like missing files and parse errors.
    """

    def __init__(self) -> None:
        self.logger = get_logger(__name__, operation="incremental_updater")

    def update_entities_for_file(
        self,
        graph: InMemoryGraph,
        file_path: str,
        extractor: ASTExtractor,
    ) -> None:
        """
        Update entities for a modified file.

        Removes existing entities for the file and re-parses to add new ones.
        Handles parse errors gracefully by logging and leaving graph unchanged.

        Args:
            graph: The InMemoryGraph to update
            file_path: Absolute path to the modified file
            extractor: ASTExtractor instance for parsing the file
        """
        # Remove existing entities for this file
        self.remove_entities_for_file(graph, file_path)

        # Add new entities by parsing the file
        self.add_entities_for_file(graph, file_path, extractor)

    def remove_entities_for_file(self, graph: InMemoryGraph, file_path: str) -> None:
        """
        Remove all entities from a deleted file using transactional approach.

        Also removes any relationships involving entities from this file.
        Uses transactional approach to prevent partial state on errors.

        Args:
            graph: The InMemoryGraph to update
            file_path: Absolute path to the deleted file
        """
        # Collect all changes first (transactional approach)
        entities_to_remove = [
            eid for eid, entity in graph.entities.items() if entity.file == file_path
        ]

        relationships_to_keep = []
        relationships_to_remove = []

        # Identify relationships to remove
        for rel in graph.relationships:
            if (
                rel.source_id in entities_to_remove
                or rel.target_id in entities_to_remove
            ):
                relationships_to_remove.append(rel)
            else:
                relationships_to_keep.append(rel)

        # Apply all changes atomically
        try:
            # Remove entities
            for eid in entities_to_remove:
                if eid in graph.entities:  # Double-check existence
                    del graph.entities[eid]

            # Update relationships
            graph.relationships = relationships_to_keep

            # Invalidate adjacency cache
            graph._adj_out = None
            graph._adj_in = None

            self.logger.debug(
                "removed_entities_for_file",
                file_path=file_path,
                entity_count=len(entities_to_remove),
                relationship_count=len(relationships_to_remove),
            )

        except Exception as e:
            # Log the error but don't leave graph in partial state
            # The graph should remain consistent since we collected changes first
            self.logger.error(
                "remove_entities_failed",
                file_path=file_path,
                error=str(e),
                entities_targeted=len(entities_to_remove),
                relationships_targeted=len(relationships_to_remove),
            )
            raise

    def add_entities_for_file(
        self,
        graph: InMemoryGraph,
        file_path: str,
        extractor: ASTExtractor,
    ) -> None:
        """
        Add entities for a new file.

        Parses the file and adds all entities and relationships to the graph.
        Handles parse errors gracefully by logging and skipping the file.

        Args:
            graph: The InMemoryGraph to update
            file_path: Absolute path to the new file
            extractor: ASTExtractor instance for parsing the file
        """
        from .languages.detector import default_detector
        from .languages.registry import get_extractor as _registry_get_extractor

        try:
            # Check if file exists and read content
            if not Path(file_path).exists():
                self.logger.warning("file_not_found", file_path=file_path)
                return

            content = read_file_bytes(
                file_path, max_size_kb=get_config_cached()["indexer"]["max_file_size_kb"], detect_binary=True
            )
            if content is None:
                self.logger.warning("file_read_failed", file_path=file_path)
                return

            # Determine extractor
            file_extractor: ASTExtractor | None = extractor
            if extractor is None:
                suffix = Path(file_path).suffix.lower()
                file_extractor = default_detector.get_extractor(
                    Path(file_path), content
                )
                if file_extractor is None:
                    file_extractor = _registry_get_extractor(suffix)

            if file_extractor is None:
                self.logger.warning("no_extractor_found", file_path=file_path)
                return

            # Parse file
            entities, relationships = file_extractor.parse_file(file_path, content)

            # Add to graph
            for entity in entities:
                graph.add_entity(entity)
            for rel in relationships:
                graph.add_relationship(rel)

            self.logger.debug(
                "added_entities_for_file",
                file_path=file_path,
                entity_count=len(entities),
            )

        except Exception as exc:
            self.logger.warning(
                "file_parse_failed", file_path=file_path, error=str(exc)
            )

    def validate_graph_consistency(self, graph: InMemoryGraph) -> bool:
        """
        Check for broken relationships after updates.

        Verifies that all relationship source and target IDs exist in the entities.
        Also checks for orphaned relationships and invalid entity references.

        Args:
            graph: The InMemoryGraph to validate

        Returns:
            True if graph is consistent, False otherwise
        """
        entity_ids = set(graph.entities.keys())
        broken_relationships = []

        for rel in graph.relationships:
            if rel.source_id not in entity_ids or rel.target_id not in entity_ids:
                broken_relationships.append(rel)

        if broken_relationships:
            self.logger.warning(
                "graph_inconsistency_detected",
                broken_relationship_count=len(broken_relationships),
                total_relationships=len(graph.relationships),
            )
            return False

        # Check for relationships with unresolved targets that are now resolvable
        # This is a basic consistency check - full resolution would require more context
        unresolved_count = sum(
            1 for rel in graph.relationships if rel.target_id.startswith("unresolved:")
        )
        if unresolved_count > 0:
            self.logger.debug("unresolved_relationships_found", count=unresolved_count)

        return True


# ---------------------------------------------------------------------------
# CodeGraphIndexer
# ---------------------------------------------------------------------------


class CodeGraphIndexer:
    """
    Production code graph indexer for batho-v1.

    Features:
    - AST entity caching with SQLite: skips unchanged files entirely
    - Parallel extraction with multiprocessing (bypasses GIL for CPU-bound parsing)
    - Per-file exception isolation
    - .gitignore + .bathoignore support via pathspec
    - Binary file detection and size guard
    - Cross-file import resolution pass

    Usage::

        indexer = CodeGraphIndexer(cache_path=".ctn/local/cache/ast_cache.db")
        graph = indexer.build_graph(
            root="/path/to/repo",
            max_workers=8,
            max_file_size_kb=500,
        )
    """

    def __init__(
        self, cache_path: str = ".ctn/local/cache/ast_cache.db", root: str | None = None
    ) -> None:
        self.logger = get_logger(__name__, operation="index")
        root_path = Path(root).resolve() if root else None
        self._cache = ASTCache(cache_path=cache_path)
        self._root: Path | None = root_path
        self.stats: Dict[str, Any] = {}

    def close(self) -> None:
        """Close the cache database connection to release file locks."""
        self._cache.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensures cache is closed."""
        self.close()
        return False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_graph(
        self,
        root: str,
        extractor: ASTExtractor | None = None,
        extensions: list[str] | None = None,
        max_workers: int = 0,
        max_file_size_kb: int | None = None,
        verbose: bool = False,
        metrics_callback: Callable[[str, Dict[str, Any]], None] | None = None,
        snapshot_id: str | None = None,
        ast_cache_enabled: bool | None = None,
    ) -> InMemoryGraph:
        """
        Walk *root* recursively, index every matching source file, and return
        a populated InMemoryGraph.

        When *extractor* is None (default), the language is inferred from the
        file extension via the registry — a mixed-language repo is fully indexed
        in a single pass.

        Args:
            root: Root directory to walk.
            extractor: Optional explicit extractor (overrides registry).
            extensions: File extensions to include, e.g. [".py", ".ts"].
                        None includes every supported extension.
            max_workers: Number of parallel threads. 0 = auto (cpu_count * 2).
            max_file_size_kb: Skip files larger than this (KB). Default 500KB.
            verbose: Print progress to stdout.
            metrics_callback: Optional callback for metrics collection.
            ast_cache_enabled: Optional override for AST cache usage in this run.

        Returns:
            Populated InMemoryGraph.

        Raises:
            ValueError: If input parameters are invalid.
            OSError: If root directory doesn't exist or isn't accessible.
        """
        # Input validation
        if not root or not isinstance(root, str):
            raise ValueError("root must be a non-empty string")

        root_path = Path(root).resolve()
        if not root_path.exists():
            raise OSError(f"Root directory does not exist: {root_path}")
        if not root_path.is_dir():
            raise OSError(f"Root path is not a directory: {root_path}")

        if max_file_size_kb is not None and (
            not isinstance(max_file_size_kb, (int, float)) or max_file_size_kb <= 0
        ):
            raise ValueError("max_file_size_kb must be a positive number or None")

        if max_workers < 0:
            raise ValueError("max_workers must be non-negative")

        if extensions is not None:
            if not isinstance(extensions, list) or not all(
                isinstance(ext, str) for ext in extensions
            ):
                raise ValueError("extensions must be a list of strings or None")
        # Use memory monitoring for large operations
        with memory_monitor(
            "build_graph", warning_threshold_mb=300.0, critical_threshold_mb=800.0
        ) as monitor:
            from .languages.detector import default_detector
            from .languages.registry import get_extractor as _registry_get_extractor

            cfg = get_config_cached()
            configured_max_file_size_kb = (
                max_file_size_kb
                if max_file_size_kb is not None
                else cfg["indexer"]["max_file_size_kb"]
            )
            configured_max_workers = (
                max_workers if max_workers > 0 else cfg["indexer"].get("max_workers", 0)
            )
            max_files_cap: Optional[int] = cfg["indexer"].get("max_files")
            fail_on_warning = cfg["indexer"].get("fail_on_warning", False)
            strict_mode = cfg["indexer"].get("strict", False)
            ext_set: set[str] | None = (
                {e if e.startswith(".") else f".{e}" for e in extensions}
                if extensions is not None
                else None
            )

            # Load BSG configuration for ignore settings
            bsg_cfg = cfg.get("bsg", {})
            if ast_cache_enabled is not None:
                bsg_cfg = dict(bsg_cfg)
                cache_cfg = dict(bsg_cfg.get("cache", {}))
                cache_cfg["enabled"] = bool(ast_cache_enabled)
                bsg_cfg["cache"] = cache_cfg
            bsg_ignore_cfg = bsg_cfg.get("ignore", {})
            bathoignore_path = (
                bsg_ignore_cfg.get("file") if bsg_ignore_cfg.get("enabled") else None
            )

            # Set parsing config for all extractors
            from .languages.registry import set_parsing_config

            bsg_parsing_cfg = bsg_cfg.get("parsing", {})
            set_parsing_config(bsg_parsing_cfg)

            ignore_spec = _load_ignore_spec(
                root_path,
                extra_patterns=cfg["indexer"].get("ignore_patterns"),
                ignore_files=cfg["indexer"].get("ignore_files"),
                bathoignore_path=bathoignore_path,
            )

            # --- Collect files to process ---
            candidates: list[tuple[Path, str]] = []  # (path, rel_str)
            for file_path in sorted(root_path.rglob("*")):
                if not file_path.is_file():
                    continue
                if _is_ignored(file_path, root_path, ignore_spec):
                    continue

                suffix = file_path.suffix.lower()

                if extractor is not None:
                    if ext_set is not None and suffix not in ext_set:
                        continue
                    candidates.append((file_path, str(file_path)))
                else:
                    file_extractor = _registry_get_extractor(suffix)
                    if file_extractor is None:
                        continue
                    if ext_set is not None and suffix not in ext_set:
                        continue
                    candidates.append((file_path, str(file_path)))

                if max_files_cap and len(candidates) >= max_files_cap:
                    break

            if verbose:
                self.logger.info(
                    "index_candidates_discovered",
                    candidates=len(candidates),
                )

            # --- Parallel extraction (single pass: cache skips parse) ---
            if configured_max_workers > 0:
                actual_workers = configured_max_workers
            else:
                cpu_count = os.cpu_count() or 4
                worker_cap = min(32, cpu_count * 2)
                file_count = len(candidates)
                if file_count <= 50:
                    actual_workers = min(4, worker_cap)
                elif file_count <= 200:
                    actual_workers = min(8, worker_cap)
                elif file_count <= 1000:
                    actual_workers = min(16, worker_cap)
                else:
                    actual_workers = worker_cap
                actual_workers = min(actual_workers, max(1, file_count))

            errors = 0

        # Check memory usage after operation and cleanup if needed
        if monitor and hasattr(monitor, "get_memory_stats"):
            final_stats = monitor.get_memory_stats()
            if final_stats.rss_mb > 500:  # If memory usage is high
                gc_result = batho.utils.memory_monitor.force_garbage_collection()
                self.logger.info(
                    "memory_cleanup_performed",
                    memory_before_mb=f"{final_stats.rss_mb:.1f}",
                    objects_freed=gc_result.get("objects_freed", 0),
                )

        def _handle_file_error(
            filepath: str, error: Exception, error_type: str = "parse"
        ) -> None:
            """Centralized error handling for file processing failures."""
            error_context = {
                "filepath": filepath,
                "error": str(error),
                "error_type": error_type,
            }

            if error_type == "parse":
                self.logger.warning("file_parse_failed", **error_context)
            elif error_type == "graph_update":
                self.logger.error("graph_update_failed", **error_context)
            elif error_type == "future_processing":
                self.logger.error("future_processing_failed", **error_context)
            else:
                self.logger.error("file_processing_failed", **error_context)

        graph = InMemoryGraph()
        files_parsed = 0
        files_skipped = 0
        files_cached = 0
        start_ts = os.times().elapsed if hasattr(os, "times") else 0.0

        # Process files using multiprocessing pipeline
        try:
            results, parallel_errors = build_graph_parallel(
                candidates,
                configured_max_file_size_kb,
                bsg_cfg,
                extractor,
                snapshot_id=snapshot_id,
            )
            errors += parallel_errors

            # Add results to graph
            for filepath, entities, relationships, cached_hit in results:
                try:
                    for entity in entities:
                        graph.add_entity(entity)
                    for rel in relationships:
                        graph.add_relationship(rel)
                    files_parsed += 1
                    if cached_hit:
                        files_cached += 1
                except Exception as graph_error:
                    _handle_file_error(filepath, graph_error, "graph_update")
                    errors += 1
                    files_skipped += 1
        except Exception as pool_error:
            self.logger.error("parallel_processing_failed", error=str(pool_error))
            raise

        # Cache cleanup: remove expired entries if cache is enabled
        bsg_cache_cfg = bsg_cfg.get("cache", {})
        if bsg_cache_cfg.get("enabled"):
            try:
                self._cache.cleanup_expired_cache()
                max_size_mb = bsg_cache_cfg.get("max_size_mb", 1024)
                self._cache.enforce_max_size(max_size_mb)
            except Exception as exc:
                self.logger.warning("cache_cleanup_failed", error=str(exc))

        bsg_symbol_cfg = bsg_cfg.get("symbol_resolution", {})
        symbol_resolution_enabled = bsg_symbol_cfg.get("enabled", True)
        symbol_resolution_fuzzy = bool(bsg_symbol_cfg.get("fuzzy_matching", False))
        symbol_index = SymbolIndex.build(graph) if symbol_resolution_enabled else None

        graph = self._resolve_imports(
            graph,
            symbol_index=symbol_index,
            fuzzy_matching=symbol_resolution_fuzzy,
        )
        derived_hierarchy_edges = self._derive_hierarchy_relations(graph)
        derived_overrides_edges = self._derive_override_edges(graph)

        semantic_stats: dict[str, int] = {
            "semantic_tags_added": 0,
            "semantic_edges_added": 0,
        }
        try:
            from batho.bsg import apply_semantic_overlay

            semantic_stats = apply_semantic_overlay(
                graph=graph,
                root_path=root_path,
                logger=self.logger,
            )
        except Exception as exc:
            self.logger.warning("bsg_semantic_stage_failed", error=str(exc))

        rule_stats: dict[str, Any] = {
            "enabled": False,
            "rules_loaded": 0,
            "rules_applied": 0,
            "entities_updated": 0,
            "errors": [],
        }
        rules_cfg = cfg.get("rules", {}) if isinstance(cfg, dict) else {}
        plugins_cfg = cfg.get("plugins", {}) if isinstance(cfg, dict) else {}
        if isinstance(rules_cfg, dict) and isinstance(plugins_cfg, dict):
            overrides = plugins_cfg.get("overrides")
            if overrides:
                rules_cfg = {**rules_cfg, "plugins_overrides": overrides}
        try:
            from batho.bsg import apply_rule_plugins

            rule_stats = apply_rule_plugins(
                graph=graph,
                root_path=root_path,
                rules_config=rules_cfg,
                logger=self.logger,
            )
        except Exception as exc:
            if rules_cfg.get("fail_on_rule_error", False):
                raise
            self.logger.warning("bsg_rules_stage_failed", error=str(exc))
            rule_stats["errors"] = [str(exc)]

        elapsed = (
            (os.times().elapsed if hasattr(os, "times") else 0.0) - start_ts
            if start_ts
            else None
        )

        self.stats = {
            "files_candidates": len(candidates),
            "files_parsed": files_parsed,
            "files_skipped": files_skipped,
            "files_cached": files_cached,
            "errors": errors,
            "entity_count": len(graph.entities),
            "relationship_count": len(graph.relationships),
            "elapsed_seconds": elapsed,
            "workers_used": actual_workers,
            "symbol_resolution_enabled": bool(symbol_resolution_enabled),
            "symbol_resolution_fuzzy": bool(symbol_resolution_fuzzy),
            "symbol_index_size": int(symbol_index.size) if symbol_index else 0,
            "derived_hierarchy_edges": derived_hierarchy_edges,
            "derived_overrides_edges": derived_overrides_edges,
            "semantic_tags_added": int(semantic_stats.get("semantic_tags_added", 0)),
            "semantic_edges_added": int(semantic_stats.get("semantic_edges_added", 0)),
            "rules_enabled": bool(rule_stats.get("enabled", False)),
            "rules_loaded": int(rule_stats.get("rules_loaded", 0)),
            "rules_applied": int(rule_stats.get("rules_applied", 0)),
            "entities_rule_tagged": int(rule_stats.get("entities_updated", 0)),
            "rules": rule_stats,
        }

        self.logger.info(
            "build_graph_complete",
            root=root,
            **self.stats,
        )

        if metrics_callback:
            try:
                metrics_callback("batho.index", self.stats)
            except Exception:
                pass

        if verbose:
            self.logger.info(
                "index_verbose_summary",
                files_parsed=files_parsed,
                entity_count=len(graph.entities),
                files_skipped=files_skipped,
                files_cached=files_cached,
            )

        # Force garbage collection for large operations
        if len(candidates) > 1000:
            gc_stats = batho.utils.memory_monitor.force_garbage_collection()
            self.logger.info("gc_completed", **gc_stats)

        return graph

    def index_file(
        self,
        filepath: str,
        extractor: ASTExtractor,
        max_file_size_kb: int | None = None,
    ) -> tuple[list[Entity], list[Relationship]]:
        """
        Index a single file on-demand (used by the MCP `index_file` tool).

        Always re-parses; updates the cache entry.

        Args:
            filepath: Absolute path to the file.
            extractor: Language-specific ASTExtractor instance.
            max_file_size_kb: Skip if file exceeds this size.

        Returns:
            (entities, relationships)
        """
        configured_max_file_size_kb = (
            max_file_size_kb
            if max_file_size_kb is not None
            else get_config_cached()["indexer"]["max_file_size_kb"]
        )

        content = read_file_bytes(filepath, max_size_kb=configured_max_file_size_kb, detect_binary=True)
        if content is None:
            return [], []

        try:
            entities, rels = extractor.parse_file(filepath, content)
        except Exception as exc:
            self.logger.warning("index_file_failed", filepath=filepath, error=str(exc))
            return [], []

        # Cache the extracted entities if cache is enabled
        bsg_cache_cfg = get_config_cached().get("bsg", {}).get("cache", {})
        if bsg_cache_cfg.get("enabled"):
            try:
                stat_info = Path(filepath).stat()
                mtime = stat_info.st_mtime
                size = stat_info.st_size
                content_hash = self._cache.file_hash(filepath, content)
                ttl_days = bsg_cache_cfg.get("ttl_days", 30)
                self._cache.cache_entities(
                    filepath, content_hash, entities, mtime, size, ttl_days
                )
            except OSError:
                pass

        return entities, rels

    def invalidate(self, filepath: str) -> None:
        """Force re-parse of filepath on the next build_graph call."""
        self._cache.invalidate_cache(pattern=filepath)

    def stats(self) -> dict[str, int]:
        """Return cache statistics."""
        cache_stats = self._cache.get_cache_stats()
        return {"cached_files": cache_stats["entry_count"]}

    def get_cache_stats(self) -> dict[str, Any]:
        """Get detailed cache statistics for monitoring."""
        return self._cache.get_cache_stats()

    # ------------------------------------------------------------------
    # Internal — cross-file import resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_ref_token(text: str) -> str:
        normalized = text.strip().strip(",;")
        normalized = re.sub(r"\s+as\s+\w+$", "", normalized).strip()
        if (
            len(normalized) >= 2
            and normalized[0] == normalized[-1]
            and normalized[0] in {'"', "'", "`"}
        ):
            normalized = normalized[1:-1].strip()
        elif normalized.startswith("<") and normalized.endswith(">"):
            normalized = normalized[1:-1].strip()
        return normalized.replace("::", ".").strip()

    @classmethod
    def _lookup_candidates(cls, ref_text: str) -> list[str]:
        base = cls._normalize_ref_token(ref_text)
        if not base:
            return []

        ordered: list[str] = []
        seen: set[str] = set()

        def _add(value: str) -> None:
            token = cls._normalize_ref_token(value)
            if not token or token in seen:
                return
            seen.add(token)
            ordered.append(token)

        _add(base)

        if "/" in base:
            tail = base.rsplit("/", 1)[-1]
            _add(tail)
            if "." in tail:
                _add(tail.rsplit(".", 1)[0])

        if "." in base:
            _add(base.rsplit(".", 1)[-1])

        if ":" in base and not base.startswith(("http://", "https://")):
            _add(base.rsplit(":", 1)[-1])

        return ordered

    @staticmethod
    def _extract_type_references(raw: Any) -> list[str]:
        reserved = {
            "class",
            "extends",
            "implements",
            "interface",
            "public",
            "private",
            "protected",
            "internal",
            "abstract",
            "final",
            "static",
            "trait",
            "struct",
        }

        values: list[str] = []
        if isinstance(raw, list):
            values = [str(item) for item in raw if str(item).strip()]
        elif isinstance(raw, str):
            values = [raw]
        elif raw is not None:
            values = [str(raw)]

        refs: list[str] = []
        seen: set[str] = set()
        for value in values:
            for token in re.findall(r"[A-Za-z_][A-Za-z0-9_\.]*", value):
                lowered = token.lower()
                if lowered in reserved:
                    continue
                if token in seen:
                    continue
                seen.add(token)
                refs.append(token)
        return refs

    def _derive_hierarchy_relations(self, graph: InMemoryGraph) -> int:
        """Derive INHERITS/IMPLEMENTS edges from entity metadata."""
        if not graph.entities:
            return 0

        name_to_id: dict[str, str] = {}
        for ent in sorted(graph.entities.values(), key=lambda e: e.id):
            name_to_id[ent.name] = ent.id
            if "." in ent.name:
                name_to_id[ent.name.split(".")[-1]] = ent.id
            if ent.type == EntityType.MODULE:
                name_to_id[Path(ent.file).stem] = ent.id

        existing = {
            (
                str(rel.source_id),
                str(rel.target_id),
                rel.type if isinstance(rel.type, RelationshipType) else rel.type,
            )
            for rel in graph.relationships
        }

        def _resolve_target(ref: str) -> str | None:
            for candidate in self._lookup_candidates(ref):
                target_id = name_to_id.get(candidate)
                if target_id:
                    return target_id
            return None

        added = 0
        class_like = {
            EntityType.CLASS,
            EntityType.INTERFACE,
            EntityType.TRAIT,
            EntityType.STRUCT,
        }
        for entity in graph.entities.values():
            if entity.type not in class_like:
                continue

            metadata = dict(entity.metadata or {})
            relation_specs = [
                (RelationshipType.INHERITS, metadata.get("bases")),
                (RelationshipType.INHERITS, metadata.get("extends")),
                (RelationshipType.IMPLEMENTS, metadata.get("implements")),
            ]
            for relation_type, raw_refs in relation_specs:
                for ref in self._extract_type_references(raw_refs):
                    target_id = _resolve_target(ref)
                    if not target_id or target_id == entity.id:
                        continue

                    key = (entity.id, target_id, relation_type)
                    if key in existing:
                        continue

                    existing.add(key)
                    graph.add_relationship(
                        Relationship(
                            source_id=entity.id,
                            target_id=target_id,
                            type=relation_type,
                            metadata={"derived": True, "reason": "metadata_hierarchy"},
                        )
                    )
                    added += 1

        return added

    def _derive_override_edges(self, graph: InMemoryGraph) -> int:
        """Derive OVERRIDES edges from CONTAINS + INHERITS relationships."""
        if not graph.entities:
            return 0

        class_methods: dict[str, dict[str, list[str]]] = defaultdict(
            lambda: defaultdict(list)
        )
        parent_map: dict[str, set[str]] = defaultdict(set)
        existing = {
            (
                str(rel.source_id),
                str(rel.target_id),
                rel.type if isinstance(rel.type, RelationshipType) else rel.type,
            )
            for rel in graph.relationships
        }

        for rel in graph.relationships:
            if rel.type == RelationshipType.CONTAINS:
                parent = graph.get_entity(rel.source_id)
                child = graph.get_entity(rel.target_id)
                if parent is None or child is None:
                    continue
                if parent.type != EntityType.CLASS or child.type != EntityType.METHOD:
                    continue
                class_methods[parent.id][child.name].append(child.id)
            elif rel.type == RelationshipType.INHERITS:
                source = graph.get_entity(rel.source_id)
                target = graph.get_entity(rel.target_id)
                if source is None or target is None:
                    continue
                if source.type != EntityType.CLASS or target.type != EntityType.CLASS:
                    continue
                parent_map[source.id].add(target.id)

        added = 0
        for class_id, methods_by_name in class_methods.items():
            if not methods_by_name:
                continue

            stack = list(parent_map.get(class_id, set()))
            visited: set[str] = set()
            ancestors: list[str] = []
            while stack:
                ancestor_id = stack.pop()
                if ancestor_id in visited:
                    continue
                visited.add(ancestor_id)
                ancestors.append(ancestor_id)
                stack.extend(parent_map.get(ancestor_id, set()))

            for ancestor_id in ancestors:
                ancestor_methods = class_methods.get(ancestor_id, {})
                if not ancestor_methods:
                    continue

                for method_name, child_method_ids in methods_by_name.items():
                    parent_method_ids = ancestor_methods.get(method_name, [])
                    if not parent_method_ids:
                        continue

                    for child_method_id in child_method_ids:
                        for parent_method_id in parent_method_ids:
                            if child_method_id == parent_method_id:
                                continue
                            key = (
                                child_method_id,
                                parent_method_id,
                                RelationshipType.OVERRIDES,
                            )
                            if key in existing:
                                continue

                            existing.add(key)
                            graph.add_relationship(
                                Relationship(
                                    source_id=child_method_id,
                                    target_id=parent_method_id,
                                    type=RelationshipType.OVERRIDES,
                                    metadata={
                                        "derived": True,
                                        "reason": "method_name_and_inheritance",
                                    },
                                )
                            )
                            added += 1

        return added

    def _resolve_imports(
        self,
        graph: InMemoryGraph,
        symbol_index: SymbolIndex | None = None,
        fuzzy_matching: bool = False,
    ) -> InMemoryGraph:
        """
        Resolve "unresolved:X" relationship targets across the full graph.

        Builds a name → entity_id index and replaces unresolved targets with
        real entity IDs where possible. Stores unresolvable imports as plain
        module name strings for visualization purposes.
        """
        lookup = symbol_index or SymbolIndex.build(graph)

        unresolved = [
            r for r in graph.relationships if r.target_id.startswith("unresolved:")
        ]
        resolved = []

        for rel in unresolved:
            ref_text = rel.target_id[11:]  # strip "unresolved:"
            source_entity = graph.get_entity(rel.source_id)
            source_file = source_entity.file if source_entity is not None else None
            target_id = lookup.resolve_candidates(
                self._lookup_candidates(ref_text),
                source_file=source_file,
                fuzzy_matching=fuzzy_matching,
            )

            resolved.append(
                Relationship(
                    source_id=rel.source_id,
                    target_id=(
                        target_id if target_id else self._normalize_ref_token(ref_text)
                    ),
                    type=rel.type,
                    metadata=rel.metadata,
                )
            )

        # Rebuild relationships: drop unresolved stubs, add resolved ones
        clean_rels = [
            r for r in graph.relationships if not r.target_id.startswith("unresolved:")
        ]
        clean_rels.extend(resolved)
        graph.relationships = clean_rels

        self.logger.info(
            "import_resolution_complete",
            unresolved_count=len(unresolved),
            resolved_count=sum(1 for r in resolved if r.target_id in graph.entities),
            symbol_index_size=lookup.size,
        )
        return graph
