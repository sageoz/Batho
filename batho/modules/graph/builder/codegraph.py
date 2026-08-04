"""
backend/context/codegraph.py — Production Code Graph Indexer.

Improvements over prototype:
- AST entity cache (flat-file msgpack, stores extracted entities, not just file state)
- AST entity caching: skips unchanged files entirely (no re-parsing)
- Parallel file extraction using multiprocessing (CPU-bound, bypasses GIL)
- Per-file exception isolation: one bad file never aborts the whole scan
- Binary file detection and size guard
- pathspec-based .gitignore support
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
import time
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterable, Optional

if TYPE_CHECKING:
    from batho.modules.graph.builder.arrow_graph import ArrowGraph
    from batho.modules.graph.builder.protocol import GraphBackend

from batho.utils.ignore import walk_ignored_filtered

import batho.utils.memory_monitor
from batho.core.config import get_config_cached
from batho.utils.file_io import read_file_bytes
from batho.utils.hash import compute_bytes_hash
from batho.utils.ignore import is_ignored, load_ignore_spec
from batho.utils.logging import get_logger
from batho.utils.memory_monitor import (
    cap_workers_by_ram,
    force_garbage_collection,
    memory_monitor,
)

from batho.modules.storage.cache.unified_cache import (
    BathoCache,
    build_ast_cache_variant,
)
from batho.modules.extraction.extractor import ASTExtractor
from batho.modules.extraction.pipeline import (
    extract_and_emit_parallel,
)
from batho.core.schemas import (
    Entity,
    EntityType,
    GraphConsistencyError,
    Relationship,
    RelationshipType,
    generate_hierarchical_id,
    detect_package_from_config,
)
from batho.modules.extraction.scope_manager import ScopeManager
from batho.modules.extraction.symbol_table import FileSymbolTable

# Binary detection is now handled in batho.utils.file_io


# ---------------------------------------------------------------------------
# Ignore pattern support — re-export from centralized utility
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# InMemoryGraph
# ---------------------------------------------------------------------------


class InMemoryGraph:
    """
    In-memory graph of code entities and their relationships.

    Stores all entities and relationships extracted from the codebase AST.
    Uses lazy adjacency index building: the index is built on the first
    call to neighbors() and invalidated whenever a relationship is added.

    Secondary indexes (_by_file, _by_type, _rels_by_endpoint) provide O(k)
    lookups where k is the result size, instead of O(N) linear scans.
    """

    def __init__(
        self,
        entities: dict[str, Entity] | None = None,
        relationships: list[Relationship] | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self.entities: dict[str, Entity] = entities if entities is not None else {}
        self.relationships: list[Relationship] = (
            relationships if relationships is not None else []
        )
        self._rel_ids: set[str] = {r.id for r in (relationships or [])}
        self._adj_out: dict[str, list[str]] | None = None
        self._adj_in: dict[str, list[str]] | None = None

        # Secondary indexes for O(k) lookups
        self._by_file: dict[str, set[str]] = defaultdict(set)
        self._by_type: dict[EntityType, set[str]] = defaultdict(set)
        self._rels_by_endpoint: dict[str, list[Relationship]] = defaultdict(list)
        self._stale_relations_count: int = 0

        # Build indexes from initial data
        if entities:
            for eid, entity in entities.items():
                self._by_file[entity.file].add(eid)
                self._by_type[entity.type].add(eid)
        if relationships:
            for rel in relationships:
                self._rels_by_endpoint[rel.source_id].append(rel)
                self._rels_by_endpoint[rel.target_id].append(rel)

    def add_entity(self, entity: Entity) -> None:
        with self._lock:
            self.entities[entity.id] = entity
            self._by_file[entity.file].add(entity.id)
            self._by_type[entity.type].add(entity.id)

    def add_relationship(self, relationship: Relationship) -> None:
        with self._lock:
            if relationship.id in self._rel_ids:
                return
            self._rel_ids.add(relationship.id)
            self.relationships.append(relationship)

            # Update secondary index
            self._rels_by_endpoint[relationship.source_id].append(relationship)
            self._rels_by_endpoint[relationship.target_id].append(relationship)

            # Incremental update instead of full invalidation
            if self._adj_out is not None:
                self._adj_out.setdefault(relationship.source_id, []).append(relationship.target_id)
            if self._adj_in is not None:
                self._adj_in.setdefault(relationship.target_id, []).append(relationship.source_id)

    def add_entities_batch(self, entities: list[Entity]) -> None:
        """Add multiple entities efficiently in a single operation."""
        with self._lock:
            for entity in entities:
                self.entities[entity.id] = entity
                self._by_file[entity.file].add(entity.id)
                self._by_type[entity.type].add(entity.id)

    def add_relationships_batch(self, relationships: list[Relationship]) -> None:
        """Add multiple relationships efficiently in a single operation."""
        with self._lock:
            for relationship in relationships:
                if relationship.id in self._rel_ids:
                    continue
                self._rel_ids.add(relationship.id)
                self.relationships.append(relationship)

                # Update secondary index
                self._rels_by_endpoint[relationship.source_id].append(relationship)
                self._rels_by_endpoint[relationship.target_id].append(relationship)

                # Incremental update instead of full invalidation
                if self._adj_out is not None:
                    self._adj_out.setdefault(relationship.source_id, []).append(relationship.target_id)
                if self._adj_in is not None:
                    self._adj_in.setdefault(relationship.target_id, []).append(relationship.source_id)

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

    def _ensure_adjacency(self) -> None:
        if self._adj_out is None or self._adj_in is None:
            self._build_index()

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

    def has_incoming_edges(self, entity_id: str) -> bool:
        self._ensure_adjacency()
        return bool(self._adj_in.get(entity_id, []))  # type: ignore[union-attr]

    def has_outgoing_edges(self, entity_id: str) -> bool:
        self._ensure_adjacency()
        return bool(self._adj_out.get(entity_id, []))  # type: ignore[union-attr]

    def get_all_nodes(self) -> list[str]:
        return list(self.entities.keys())

    def entities_by_file(self, file_path: str) -> list[Entity]:
        """Return entities for a file path using secondary index (O(k))."""
        with self._lock:
            return [self.entities[eid] for eid in self._by_file.get(file_path, []) if eid in self.entities]

    def entities_by_type(self, entity_type: EntityType) -> list[Entity]:
        """Return entities of a specific type using secondary index (O(k))."""
        with self._lock:
            return [self.entities[eid] for eid in self._by_type.get(entity_type, []) if eid in self.entities]

    def get_rels_by_endpoint(self, entity_id: str) -> list[Relationship]:
        """Return all relationships where entity_id is source or target (O(k))."""
        return list(self._rels_by_endpoint.get(entity_id, []))

    def degree_by_endpoint(self, entity_id: str) -> int:
        """Count relationships touching entity_id (O(1), matches len of endpoint list)."""
        return len(self._rels_by_endpoint.get(entity_id, ()))

    def entity_ids_by_type(self, entity_type: EntityType) -> list[str]:
        """Return entity ids of a type without materializing entities (O(k))."""
        with self._lock:
            return [
                eid
                for eid in self._by_type.get(entity_type, ())
                if eid in self.entities
            ]

    def update_entity(self, entity_id: str, entity: Entity) -> None:
        """Insert or replace an entity, keeping secondary indexes consistent.

        Handles file/type changes by discarding stale index entries before
        re-adding under the new file/type.
        """
        with self._lock:
            old = self.entities.get(entity_id)
            if old is not None:
                if old.file != entity.file:
                    self._by_file[old.file].discard(entity_id)
                if old.type != entity.type:
                    self._by_type[old.type].discard(entity_id)
            self.entities[entity_id] = entity
            self._by_file[entity.file].add(entity_id)
            self._by_type[entity.type].add(entity_id)

    def update_relationships(self, relationships: list[Relationship]) -> None:
        """Replace the full relationship list and rebuild dependent indexes."""
        with self._lock:
            self.relationships = list(relationships)
            self._rel_ids = {r.id for r in self.relationships}
            self._adj_out = None
            self._adj_in = None
            self._rels_by_endpoint.clear()
            for rel in self.relationships:
                self._rels_by_endpoint[rel.source_id].append(rel)
                self._rels_by_endpoint[rel.target_id].append(rel)

    def update_relationship(self, relationship: Relationship) -> None:
        """Replace a single relationship (matched by id); add if missing."""
        with self._lock:
            idx = next(
                (i for i, r in enumerate(self.relationships) if r.id == relationship.id),
                None,
            )
            if idx is None:
                if relationship.id in self._rel_ids:
                    return
                self._rel_ids.add(relationship.id)
                self.relationships.append(relationship)
                self._rels_by_endpoint[relationship.source_id].append(relationship)
                self._rels_by_endpoint[relationship.target_id].append(relationship)
                if self._adj_out is not None:
                    self._adj_out.setdefault(relationship.source_id, []).append(relationship.target_id)
                if self._adj_in is not None:
                    self._adj_in.setdefault(relationship.target_id, []).append(relationship.source_id)
                return

            old = self.relationships[idx]
            self.relationships[idx] = relationship
            for endpoint in (old.source_id, old.target_id):
                lst = self._rels_by_endpoint.get(endpoint)
                if lst:
                    try:
                        lst.remove(old)
                    except ValueError:
                        pass
            self._rels_by_endpoint[relationship.source_id].append(relationship)
            self._rels_by_endpoint[relationship.target_id].append(relationship)
            self._adj_out = None
            self._adj_in = None

    def compact(self) -> None:
        """No-op lifecycle hook for GraphBackend parity (ArrowGraph compacts)."""

    def close(self) -> None:
        """No-op lifecycle hook for GraphBackend parity (ArrowGraph frees mmap)."""

    def _remove_entity_indexes(self, entity_id: str) -> None:
        """Remove an entity from secondary indexes."""
        entity = self.entities.get(entity_id)
        if entity:
            self._by_file[entity.file].discard(entity_id)
            self._by_type[entity.type].discard(entity_id)

    def remove_node(self, entity_id: str) -> bool:
        with self._lock:
            entity = self.entities.get(entity_id)
            if entity is None:
                return False

            del self.entities[entity_id]
            self._by_file[entity.file].discard(entity_id)
            self._by_type[entity.type].discard(entity_id)

            rels = list(self._rels_by_endpoint.get(entity_id, []))
            rel_ids = {rel.id for rel in rels}
            if rel_ids:
                self.relationships = [
                    r for r in self.relationships if r.id not in rel_ids
                ]
                self._rel_ids.difference_update(rel_ids)
                self._stale_relations_count += len(rel_ids)

                for rel in rels:
                    if rel.source_id != entity_id:
                        self._rels_by_endpoint[rel.source_id] = [
                            r
                            for r in self._rels_by_endpoint.get(rel.source_id, [])
                            if r.id not in rel_ids
                        ]
                    if rel.target_id != entity_id:
                        self._rels_by_endpoint[rel.target_id] = [
                            r
                            for r in self._rels_by_endpoint.get(rel.target_id, [])
                            if r.id not in rel_ids
                        ]

                threshold = max(1000, len(self.relationships) // 5)
                if self._stale_relations_count > threshold:
                    self._rels_by_endpoint.clear()
                    for rel in self.relationships:
                        self._rels_by_endpoint[rel.source_id].append(rel)
                        self._rels_by_endpoint[rel.target_id].append(rel)
                    self._stale_relations_count = 0

            self._rels_by_endpoint.pop(entity_id, None)

            if self._adj_out is not None:
                self._adj_out.pop(entity_id, None)
                for src, targets in list(self._adj_out.items()):
                    if entity_id in targets:
                        self._adj_out[src] = [
                            target for target in targets if target != entity_id
                        ]
            if self._adj_in is not None:
                self._adj_in.pop(entity_id, None)
                for tgt, sources in list(self._adj_in.items()):
                    if entity_id in sources:
                        self._adj_in[tgt] = [
                            source for source in sources if source != entity_id
                        ]

            return True

    def evict_file_graph(self, file_path: str) -> None:
        """Safely evicts file entities and relationships without corrupting secondary indexes."""
        with self._lock:
            entities_to_remove = list(self._by_file.get(file_path, set()))
            if not entities_to_remove:
                return

            rel_ids_to_remove = set()
            for eid in entities_to_remove:
                ent = self.entities.pop(eid, None)
                if ent:
                    self._by_type[ent.type].discard(eid)
                for rel in self._rels_by_endpoint.get(eid, []):
                    rel_ids_to_remove.add(rel.id)
                self._rels_by_endpoint.pop(eid, None)

            self._by_file.pop(file_path, None)

            if rel_ids_to_remove:
                self.relationships = [r for r in self.relationships if r.id not in rel_ids_to_remove]
                self._rel_ids.difference_update(rel_ids_to_remove)
                self._adj_out = None
                self._adj_in = None

    def root_entities(self) -> list[Entity]:
        return [e for e in self.entities.values() if e.parent_id is None]

    def to_dict(self, *, view: str = "storage") -> dict[str, Any]:
        return {
            "entities": [e.to_dict(view=view) for e in self.entities.values()],
            "entities_by_id": {
                eid: e.to_dict(view=view) for eid, e in self.entities.items()
            },
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

    def stats(self) -> dict[str, Any]:
        """Get statistics about the graph for profiling and monitoring."""
        files: set[str] = set()
        entity_types: dict[str, int] = {}
        for entity in self.entities.values():
            files.add(entity.file)
            entity_types[entity.type.value] = entity_types.get(entity.type.value, 0) + 1

        relationship_types: dict[str, int] = {}
        for rel in self.relationships:
            relationship_types[rel.type.value] = relationship_types.get(rel.type.value, 0) + 1

        return {
            "entity_count": len(self.entities),
            "relationship_count": len(self.relationships),
            "file_count": len(files),
            "entity_types": entity_types,
            "total_entities": len(self.entities),
            "total_relationships": len(self.relationships),
            "relationship_types": relationship_types,
            "files_indexed": len(self._by_file),
            "indexes_valid": self._adj_out is not None,
        }

    def enrich_from_storage_view(self, storage_view_data: dict[str, Any]) -> None:
        """Enrich graph entities with raw_content and raw_bytes from storage view."""
        if not storage_view_data:
            return
        for file_entry in storage_view_data.get("files", []):
            for entity_data in file_entry.get("entities", []):
                entity_id = entity_data.get("id")
                if entity_id and entity_id in self.entities:
                    entity = self.entities[entity_id]
                    updates: dict[str, Any] = {}
                    if "raw_content" in entity_data:
                        updates["raw_content"] = entity_data["raw_content"]
                    if "raw_bytes" in entity_data:
                        raw_bytes_val = entity_data["raw_bytes"]
                        if isinstance(raw_bytes_val, str) and raw_bytes_val:
                            updates["raw_bytes"] = bytes.fromhex(raw_bytes_val)
                        elif raw_bytes_val:
                            updates["raw_bytes"] = raw_bytes_val
                    if updates:
                        self.entities[entity_id] = entity.model_copy(
                            update=updates
                        )


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

        Uses secondary indexes for O(removed × degree) complexity instead of O(F×R).
        Updates adjacency cache incrementally instead of full invalidation.

        NOTE on threading (BUG-02): This method mutates graph structures without
        acquiring graph._lock. This is a design decision; patch operations (including
        this method and add_entities_for_file) are executed sequentially on the main
        thread inside a single-threaded orchestrator. No concurrent mutations occur
        during patch execution.

        Args:
            graph: The InMemoryGraph to update
            file_path: Absolute path to the deleted file
        """
        # Use _by_file index for O(k) lookup instead of O(N) scan
        entities_to_remove = list(graph._by_file.get(file_path, set()))
 
        # Collect all relationships to remove using _rels_by_endpoint index
        rel_ids_to_remove: set[str] = set()
        for eid in entities_to_remove:
            for rel in graph._rels_by_endpoint.get(eid, []):
                if rel.id in graph._rel_ids:
                    rel_ids_to_remove.add(rel.id)
 
        # Build new relationships list (filtering out removed ones)
        relationships_to_keep = [r for r in graph.relationships if r.id not in rel_ids_to_remove]
 
        # Snapshot for rollback in case of partial mutation failure (BUG-03)
        original_entities = {eid: graph.entities[eid] for eid in entities_to_remove if eid in graph.entities}
        original_by_file = set(graph._by_file.get(file_path, set()))
        original_by_type = {
            ent.type: set(graph._by_type.get(ent.type, set()))
            for ent in original_entities.values()
        }
        original_relationships = list(graph.relationships)
        original_rel_ids = set(graph._rel_ids)
        original_rels_by_endpoint = {k: list(v) for k, v in graph._rels_by_endpoint.items()}
        original_stale_relations_count = graph._stale_relations_count
        original_adj_out = {k: list(v) for k, v in graph._adj_out.items()} if graph._adj_out is not None else None
        original_adj_in = {k: list(v) for k, v in graph._adj_in.items()} if graph._adj_in is not None else None

        # Apply all changes atomically
        try:
            # Remove entities and update secondary indexes
            for eid in entities_to_remove:
                if eid in graph.entities:
                    entity = graph.entities[eid]
                    del graph.entities[eid]
                    # Update secondary indexes
                    graph._by_file[entity.file].discard(eid)
                    graph._by_type[entity.type].discard(eid)
 
            # Update relationships
            graph.relationships = relationships_to_keep
            graph._rel_ids = {r.id for r in relationships_to_keep}
 
            # Lazy/batch eviction of relationship endpoints
            for eid in entities_to_remove:
                graph._rels_by_endpoint.pop(eid, None)
 
            graph._stale_relations_count += len(rel_ids_to_remove)
 
            # Rebuild relationship index if threshold exceeded (e.g. 20% of total relationships or 1000)
            threshold = max(1000, len(graph.relationships) // 5)
            if graph._stale_relations_count > threshold:
                graph._rels_by_endpoint.clear()
                for rel in graph.relationships:
                    graph._rels_by_endpoint[rel.source_id].append(rel)
                    graph._rels_by_endpoint[rel.target_id].append(rel)
                graph._stale_relations_count = 0
 
            # Incremental adjacency cache update (if cache exists)
            if graph._adj_out is not None:
                for eid in entities_to_remove:
                    if eid in graph._adj_out:
                        del graph._adj_out[eid]
                    # Remove entries where eid is a target
                    for src, targets in list(graph._adj_out.items()):
                        if eid in targets:
                            targets.remove(eid)
            if graph._adj_in is not None:
                for eid in entities_to_remove:
                    if eid in graph._adj_in:
                        del graph._adj_in[eid]
                    # Remove entries where eid is a source
                    for tgt, sources in list(graph._adj_in.items()):
                        if eid in sources:
                            sources.remove(eid)
 
            self.logger.debug(
                "removed_entities_for_file",
                file_path=file_path,
                entity_count=len(entities_to_remove),
                relationship_count=len(rel_ids_to_remove),
            )
 
        except Exception as e:
            # Rollback mutations to ensure transactional atomicity
            graph.entities.update(original_entities)
            graph._by_file[file_path] = original_by_file
            for etype, original_set in original_by_type.items():
                graph._by_type[etype] = original_set
            graph.relationships = original_relationships
            graph._rel_ids = original_rel_ids
            graph._rels_by_endpoint = original_rels_by_endpoint
            graph._stale_relations_count = original_stale_relations_count
            graph._adj_out = original_adj_out
            graph._adj_in = original_adj_in

            if isinstance(e, (KeyError, ValueError, RuntimeError)):
                self.logger.error(
                    "remove_entities_recoverable_error",
                    file_path=file_path,
                    error=str(e),
                    entities_targeted=len(entities_to_remove),
                    relationships_targeted=len(rel_ids_to_remove),
                )
                raise GraphConsistencyError(f"Failed to remove entities for {file_path}: {e}") from e
            else:
                self.logger.exception("Unexpected error in remove_entities_for_file")
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
        from batho.modules.extraction.submodules.parser_factory.detector import default_detector
        from batho.modules.extraction.submodules.parser_factory.registry import get_extractor as _registry_get_extractor

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

    def validate_graph_consistency(self, graph: "GraphBackend") -> bool:
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

        def is_valid_target(target_id: str) -> bool:
            """Check if target is a valid entity reference or intentional external reference."""
            if target_id in entity_ids:
                return True
            # Allow UNRESOLVED and EXTERNAL_SYMBOL entity IDs
            target_entity = graph.entities.get(target_id)
            if target_entity is not None and target_entity.type in (EntityType.UNRESOLVED, EntityType.EXTERNAL_SYMBOL):
                return True
            # Allow special external references (URLs, files, anchors, imports, resources, variables, images)
            valid_prefixes = ("external:", "file:", "anchor:", "import:", "resource:", "variable:", "image:", "batho ")
            if any(target_id.startswith(prefix) for prefix in valid_prefixes):
                return True
            return False

        def is_valid_source(source_id: str) -> bool:
            """Check if source is a valid entity reference or file path (legacy behavior)."""
            if source_id in entity_ids:
                return True
            # Allow file paths as source (legacy behavior - some relationships use file path as source)
            if "/" in source_id or "\\" in source_id:
                return True
            return False

        for rel in graph.relationships:
            if not is_valid_source(rel.source_id) or not is_valid_target(rel.target_id):
                broken_relationships.append(rel)

        if broken_relationships:
            self.logger.warning(
                "graph_inconsistency_detected",
                broken_relationship_count=len(broken_relationships),
                total_relationships=len(graph.relationships),
            )
            return False

        # Check for unresolved entities in the graph
        unresolved_entity_count = sum(
            1 for e in graph.entities.values() if e.type == EntityType.UNRESOLVED
        )
        if unresolved_entity_count > 0:
            self.logger.debug("unresolved_entities_found", count=unresolved_entity_count)

        return True


# ---------------------------------------------------------------------------
# CodeGraphIndexer
# ---------------------------------------------------------------------------


def _merge_external_scope(target: ScopeManager, source: ScopeManager) -> None:
    """Bulk-merge all global symbols from source into target (write-once, no lock per symbol)."""
    snapshot = source.get_global_symbols()
    target.load_global_symbols(snapshot)


# Common stdlib module names across supported languages (Python, Go, Rust, C++).
# Used by the stdlib-prefix fast-path in resolve_contextual_stubs to quickly
# resolve stubs that reference well-known standard library modules.
_STDLIB_MODULE_PREFIXES = frozenset({
    # Python
    "std", "os", "re", "sys", "json", "math", "time",
    "fmt", "io", "net", "sync", "strings", "context",
    "collections", "pathlib", "datetime", "threading",
    "subprocess", "logging", "typing", "itertools",
    "functools", "abc", "copy", "hashlib", "pickle",
    "sqlite3", "csv", "xml", "html", "urllib",
    # Node.js / JavaScript / TypeScript
    "fs", "path", "http", "https", "crypto", "stream",
    "events", "util", "process", "console", "buffer",
    "url", "querystring", "tls", "dgram", "dns",
    "cluster", "readline", "repl", "vm", "zlib", "assert",
    "timers", "worker_threads", "child_process",
})


# ---------------------------------------------------------------------------
# Phase 4: Confidence scoring — resolution strategy tiers
# ---------------------------------------------------------------------------

# Confidence scores for each resolution strategy (codebase-indexer-py pattern).
# Tagged on every resolved stub so downstream consumers (queries, visualizations,
# exports) can filter by confidence level.
_RESOLUTION_CONFIDENCE: dict[str, float] = {
    "exact_match": 0.95,        # Tier 1: Direct dotpath lookup
    "stdlib_method": 0.90,      # Tier 2: Stdlib method / module prefix match
    "import_map": 0.85,         # Tier 3: Import-map cross-file
    "parent_chain": 0.75,       # Tier 4: Parent stub chain building
    "scope_qualified": 0.70,    # Tier 5: Caller-scope qualified path
    "receiver_type": 0.65,      # Tier 6: Receiver-type inference
    "unresolved": 0.0,          # Tier 7: No match
}


# ---------------------------------------------------------------------------
# Phase 4: Conservative pruning — common stdlib method names
# ---------------------------------------------------------------------------

# Common method names that are safe to prune if receiver type is unknown.
# These are stdlib methods that appear on many types — resolving them to a
# specific type is not meaningful, and leaving them as unresolved stubs
# clutters the graph with false "gaps."
_PRUNABLE_METHOD_NAMES: frozenset[str] = frozenset({
    # Rust — Option/Result/Iterator/Vec/String/convert methods
    "unwrap", "unwrap_or", "unwrap_or_else", "expect", "clone", "into", "as_ref",
    "as_mut", "to_owned", "to_string", "map", "map_err", "and_then", "or", "ok",
    "err", "is_some", "is_none", "is_ok", "is_err", "iter", "into_iter", "next",
    "collect", "filter", "fold", "for_each", "enumerate", "zip", "len", "is_empty",
    "get", "push", "pop", "insert", "remove", "contains", "clear", "extend",
    "copied", "cloned", "take", "skip", "rev", "chain", "flat_map", "filter_map",
    "any", "all", "count", "sum", "min", "max", "peekable", "dedup",
    # JavaScript — Array/String/Promise methods
    "then", "catch", "finally", "reduce", "forEach", "slice", "splice", "concat",
    "join", "split", "replace", "trim", "includes", "indexOf", "find", "findIndex",
    "some", "every", "flat", "flatMap", "sort", "reverse", "fill", "keys", "values",
    "entries", "charAt", "charCodeAt", "substring", "toLowerCase", "toUpperCase",
    "padStart", "padEnd", "repeat", "startsWith", "endsWith", "normalize",
    # Python — list/dict/set/str methods
    "append", "copy", "index", "items", "update",
    "setdefault", "popitem", "fromkeys", "add", "discard", "union", "intersection",
    "difference", "symmetric_difference", "issubset", "issuperset", "format",
    "encode", "decode", "strip", "lstrip", "rstrip", "partition", "rpartition",
    "rsplit", "splitlines", "swapcase", "title", "zfill", "isalpha", "isdigit",
    "isalnum", "isupper", "islower", "isspace",
})


def _materialize_external_symbols(graph: "InMemoryGraph | ArrowGraph", scope_manager: ScopeManager) -> int:
    """Create EXTERNAL_SYMBOL entities in the graph for all external symbols in the scope manager.
    
    Returns the number of external symbol entities created.
    """
    from batho.core.schemas import Entity, EntityType
    
    global_symbols = scope_manager.get_global_symbols()
    created = 0
    
    for _partition, symbols_map in global_symbols.items():
        for name, info in symbols_map.items():
            if not info.get("is_external", False):
                continue
            symbol_id = info["symbol_id"]
            # Skip if entity already exists in graph
            if symbol_id in graph.entities:
                continue
            ent = Entity.model_construct(
                id_override=symbol_id,
                name=name,
                type=EntityType.EXTERNAL_SYMBOL,
                file="",
                start_line=1,
                end_line=1,
                start_byte=0,
                end_byte=0,
                parent_id=None,
                raw_content=None,
                raw_bytes=None,
                metadata={
                    "is_hollow": True,
                    "is_external": True,
                    "symbol_type": info.get("symbol_type", "external"),
                    "scope_path": info.get("scope_path", ""),
                },
            )
            graph.add_entity(ent)
            created += 1
    
    return created

class CodeGraphIndexer:
    """
    Production code graph indexer for batho-v1.

    Features:
    - AST entity caching with flat-file msgpack: skips unchanged files entirely
    - Parallel extraction with multiprocessing (bypasses GIL for CPU-bound parsing)
    - Per-file exception isolation
    - .gitignore support via pathspec
    - Binary file detection and size guard
    - Cross-file import resolution pass

    Usage::

        # cache_path should be derived from config: get_config_cached()["paths"]["db_path"]
        # max_workers should be derived from config: get_config_cached()["indexer"]["max_workers"]
        # max_file_size_kb should be derived from config: get_config_cached()["indexer"]["max_file_size_kb"]
        indexer = CodeGraphIndexer(cache_path="/path/to/cache")
        graph = indexer.build_graph(
            root="/path/to/repo",
            max_workers=0,  # 0 = auto (cpu_count * 2)
            max_file_size_kb=500,
        )
    """

    def __init__(
        self,
        cache_path: str | None = None,
        root: str | None = None,
        ast_cache_dir: str | None = None,
    ) -> None:
        self.logger = get_logger(__name__, operation="index")
        root_path = Path(root).resolve() if root else None
        self._cache = BathoCache(
            cache_path=cache_path,
            repo_root=root_path,
            ast_cache_dir=ast_cache_dir,
        )
        self._root: Path | None = root_path
        self.build_stats: dict[str, Any] = {}  # populated after build_graph(); distinct from stats() method
        self._last_reconstruction: Any = None  # set after reconstruct_file
        self._unindexed_files: list[tuple[str, str]] = []  # (abs_path_str, rel_path_str) populated by build_graph()
        self._indexed_files: list[str] = []
        self._keep_nodes: set[str] = set()

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

    def get_unindexed_files(self) -> list[tuple[str, str]]:
        """Return list of files that could not be indexed (no extractor available).

        Returns:
            List of tuples (absolute_path, relative_path) for unindexed files.
        """
        return list(self._unindexed_files)

    def clear_unindexed_files(self) -> None:
        """Clear the list of unindexed files."""
        self._unindexed_files.clear()

    def get_file_snapshot(self, path_or_rel: str) -> Optional[FileSnapshot]:
        """Expose file snapshot from the unified cache."""
        from batho.core.schemas import FileSnapshot
        if hasattr(self, "_cache") and self._cache is not None:
            return self._cache.get_file_snapshot(path_or_rel)
        return None

    # Entity types that should be registered as global symbols for cross-file
    # resolution. Mirrors rust-analyzer's DefMap and Pyright's binder: every
    # project-defined function/class/method/struct is globally resolvable.
    _GLOBAL_SYMBOL_ENTITY_TYPES = frozenset({
        EntityType.FUNCTION,
        EntityType.METHOD,
        EntityType.CLASS,
        EntityType.STRUCT,
        EntityType.INTERFACE,
        EntityType.ENUM,
        EntityType.TRAIT,
    })

    def _register_project_symbols(self, graph: "GraphBackend", scope_manager: ScopeManager) -> int:
        """Register all project-internal definitions as global symbols.

        After extraction, every project-defined function, class, method,
        struct, enum, interface, and trait is registered in the global symbol
        table by both simple name and qualified name (FQN/signature).

        This enables cross-file resolution where a stub references a project
        symbol that was defined in a different file/scope than where it is
        being resolved. Without this, only symbols defined during extraction
        (with an active scope) make it into the ScopeManager.

        Performance: O(n) where n = number of entities. For tokenizers
        (~12k entities) this is <10ms. The ScopeManager uses partitioned
        locks for thread safety.
        """
        registered = 0
        for entity in graph.entities.values():
            if entity.is_contextual_stub:
                continue
            if entity.type not in self._GLOBAL_SYMBOL_ENTITY_TYPES:
                continue
            # Register by simple name
            scope_manager.define_symbol(
                entity.name, entity.id, entity.type.name, is_global=True
            )
            # Register by qualified name if FQN is available
            fqn = entity.fqn
            if fqn and fqn != entity.name:
                scope_manager.define_symbol(
                    fqn, entity.id, entity.type.name, is_global=True
                )
            registered += 1
        self.logger.info("project_symbols_registered", count=registered)
        return registered

    # Mapping from common type names to stdlib module paths, used by
    # _check_stdlib_method to verify that a method exists on a known type.
    _TYPE_TO_STDLIB_MODULE: Dict[str, str] = {
        # Rust prelude types
        "Option": "std::option::Option",
        "Result": "std::result::Result",
        "Iterator": "std::iter::Iterator",
        "Vec": "std::vec::Vec",
        "String": "std::string::String",
        "HashMap": "std::collections",
        "HashSet": "std::collections",
        "VecDeque": "std::collections",
        "BTreeMap": "std::collections",
        "BTreeSet": "std::collections",
        # JavaScript/TypeScript built-ins
        "Array": "Array.prototype",
        "Promise": "Promise",
    }

    def _resolve_method_call(
        self, stub: Entity, graph: "GraphBackend", scope_manager: ScopeManager
    ) -> Optional[Any]:
        """Resolve a method call by inferring the receiver type.

        Implements rust-analyzer's two-phase method resolution:
        1. Infer the receiver variable's type from scope/declarations
        2. Look up the method on that type (inherent methods, then stdlib)
        """
        target_name = stub.metadata.get("target_name", "")
        receiver_var = stub.metadata.get("receiver_var")
        if not receiver_var or "." not in target_name:
            return None

        method_name = target_name.split(".", 1)[1]

        # 1. Infer the receiver variable's declared type
        var_type = self._infer_variable_type(receiver_var, stub, graph, scope_manager)
        if not var_type:
            return None

        # 2. Look up method on the type: try "Type.method_name"
        qualified = f"{var_type}.{method_name}"
        result = scope_manager.resolve_symbol_dotpath(qualified)
        if result:
            return result

        # 3. Check stdlib method table for the inferred type
        return self._check_stdlib_method(var_type, method_name, scope_manager)

    def _infer_variable_type(
        self, var_name: str, stub: Entity, graph: "GraphBackend", scope_manager: ScopeManager
    ) -> Optional[str]:
        """Infer the type of a variable from multiple sources.

        Type inference sources (from Pyright and rust-analyzer research):
        1. self/this -> enclosing class type (from caller_scope)
        2. receiver_type hint in stub metadata (captured by tree-sitter queries)
        3. Variable declaration with type annotation in the same file
        """
        # Source 1: self/this -> enclosing class type
        if var_name in ("self", "this"):
            caller_scope = stub.metadata.get("caller_scope", "")
            # caller_scope format: "batho <pm> <pkg> <ver> <path/to/Class/method>"
            parts = caller_scope.split()
            if len(parts) >= 5:
                scope_path = parts[4]
            else:
                scope_path = caller_scope
            # Walk the scope path segments from innermost outward looking for a class
            segments = scope_path.split("/")
            for seg in reversed(segments):
                seg = seg.split("#")[0].split("(")[0]
                if not seg or seg == var_name:
                    continue
                result = scope_manager.resolve_symbol_strict(seg)
                if result and result.symbol_type in (
                    "CLASS", "STRUCT", "TRAIT", "INTERFACE",
                ):
                    return seg
            return None

        # Source 2: receiver_type hint in stub metadata
        # (extractor.py captures "ref.receiver_type" via _CONTAINS_HINT_CAPTURES)
        receiver_type = stub.metadata.get("receiver_type")
        if receiver_type:
            return receiver_type

        # Source 3: Look for a variable declaration in the same file with a type
        stub_file = getattr(stub, "file", "")
        if stub_file:
            for entity in graph.entities.values():
                if getattr(entity, "file", "") != stub_file:
                    continue
                if entity.name == var_name and entity.metadata.get("declared_type"):
                    return entity.metadata["declared_type"]

        return None

    def _check_stdlib_method(
        self, var_type: str, method_name: str, scope_manager: ScopeManager
    ) -> Optional[Any]:
        """Check if method_name is a known stdlib method on var_type.

        Uses the StdlibSymbolTable to verify the method exists on the type,
        then resolves the stdlib module as the resolution target.
        """
        from batho.modules.dependency.stdlib_tables import StdlibSymbolTable

        table = StdlibSymbolTable()
        module_path = self._TYPE_TO_STDLIB_MODULE.get(var_type, var_type)

        # Try Rust first (most common case for the tokenizers benchmark),
        # then JavaScript/TypeScript.
        for lang in ("rust", "javascript", "typescript"):
            methods = table.get_symbols(lang, module_path)
            if methods and method_name in methods:
                return scope_manager.resolve_symbol_dotpath(module_path)

        return None

    def resolve_contextual_stubs(
        self,
        graph: "GraphBackend",
        scope_manager: ScopeManager,
        lazy: bool = False,
    ) -> tuple[int, int]:
        """Resolve contextual stubs in the graph using the global ScopeManager.

        Returns:
            (resolved_count, unresolved_count)

        Phase 4 additions:
        - Confidence scoring: each resolved stub is tagged with
          ``resolution_confidence`` and ``resolution_strategy`` in its metadata.
        - Conservative pruning: unresolved stubs whose target is a common
          stdlib method name on an unknown receiver type are marked as
          ``stub_resolution_state: "pruned"`` instead of left as pending gaps.

        Phase 5 additions:
        - Lazy mode: when ``lazy=True``, stubs are not resolved upfront.
          They remain in ``"pending"`` state and can be resolved on-demand
          via :meth:`resolve_stub_on_demand`. This implements the
          rust-analyzer/Pyright on-demand evaluation pattern, avoiding
          the cost of resolving stubs that no query will ever reference.
        """
        self.logger.info("resolving_contextual_stubs", lazy=lazy)
        stubs = [ent for ent in graph.entities.values() if ent.is_contextual_stub]
        self.logger.info("stubs_found_in_graph", count=len(stubs))

        # Phase 5: Lazy mode — skip upfront resolution entirely.
        # Stubs will be resolved on-demand by resolve_stub_on_demand().
        if lazy:
            pending = sum(
                1 for s in stubs
                if s.metadata.get("stub_resolution_state") not in ("resolved", "pruned")
            )
            self.logger.info(
                "contextual_stub_resolution_complete",
                stubs_found=len(stubs),
                resolved=0,
                unresolved=pending,
                pruned=0,
                lazy=True,
            )
            return 0, pending

        resolved_count = 0
        unresolved_count = 0
        stub_to_target: dict[str, str] = {}
        # Phase 4: track resolution strategy per stub for confidence scoring
        stub_to_strategy: dict[str, str] = {}

        for stub in stubs:
            caller_scope = stub.metadata.get("caller_scope")
            target_name = stub.metadata.get("target_name")
            self.logger.debug("checking_stub", stub_id=stub.id, target_name=target_name, caller_scope=caller_scope)
            if not target_name:
                continue

            resolved_info, strategy = self._resolve_single_stub(
                stub, graph, scope_manager
            )

            if resolved_info:
                self.logger.debug("stub_resolved", stub_id=stub.id, target_id=resolved_info.symbol_id)
                stub_to_target[stub.id] = resolved_info.symbol_id
                stub_to_strategy[stub.id] = strategy
                resolved_count += 1
            else:
                unresolved_count += 1

        # Phase 4: Set confidence on resolved relationships
        new_relationships = []
        for rel in graph.relationships:
            if rel.target_id in stub_to_target:
                strategy = stub_to_strategy.get(rel.target_id, "exact_match")
                confidence = _RESOLUTION_CONFIDENCE.get(strategy, 0.5)
                new_relationships.append(
                    rel._evolve(
                        target_id=stub_to_target[rel.target_id],
                        confidence=confidence,
                    )
                )
            else:
                new_relationships.append(rel)

        graph.update_relationships(new_relationships)

        # Phase 4: Tag resolved stubs with confidence and resolution strategy
        for stub_id, target_id in stub_to_target.items():
            stub = graph.get_entity(stub_id)
            if stub:
                strategy = stub_to_strategy.get(stub_id, "exact_match")
                updated_meta = dict(stub.metadata)
                updated_meta["stub_resolution_state"] = "resolved"
                updated_meta["resolved_target_id"] = target_id
                updated_meta["resolution_strategy"] = strategy
                updated_meta["resolution_confidence"] = _RESOLUTION_CONFIDENCE.get(strategy, 0.5)
                graph.update_entity(stub_id, stub._evolve(metadata=updated_meta))

        # Phase 4: Conservative pruning — mark common stdlib method names on
        # unknown receiver types as "pruned" instead of leaving them as
        # unresolved gaps. This reduces graph noise without hiding genuine
        # resolution failures (Eclipse CDT pattern).
        pruned_count = 0
        for stub in stubs:
            if stub.id in stub_to_target:
                continue  # Already resolved
            if self._should_prune_stub(stub):
                updated_meta = dict(stub.metadata)
                updated_meta["stub_resolution_state"] = "pruned"
                updated_meta["prune_reason"] = "common_method_unknown_receiver"
                updated_meta["resolution_confidence"] = 0.0
                updated_meta["resolution_strategy"] = "unresolved"
                graph.update_entity(stub.id, stub._evolve(metadata=updated_meta))
                pruned_count += 1
                unresolved_count -= 1

        self.logger.info(
            "contextual_stub_resolution_complete",
            stubs_found=len(stubs),
            resolved=resolved_count,
            unresolved=unresolved_count,
            pruned=pruned_count,
        )

        return resolved_count, unresolved_count

    def _resolve_single_stub(
        self,
        stub: Entity,
        graph: "GraphBackend",
        scope_manager: ScopeManager,
    ) -> tuple[Any, str]:
        """Resolve a single stub using the full resolution pipeline.

        Extracted from :meth:`resolve_contextual_stubs` for on-demand use
        (Phase 5 lazy resolution pattern).

        Returns:
            (resolved_info, strategy) — resolved_info is the ResolvedInfo
            object from the scope manager, or None if unresolved. strategy
            is the resolution strategy string used for confidence scoring.
        """
        target_name = stub.metadata.get("target_name")
        if not target_name:
            return None, "unresolved"

        caller_scope = stub.metadata.get("caller_scope")
        resolved_info = None
        strategy = "exact_match"

        # 1. Try resolving target_name directly
        resolved_info = scope_manager.resolve_symbol_dotpath(target_name)

        # 1b. Stdlib-prefix fast-path: if target_name starts with a known
        # stdlib module prefix (e.g., "std::", "os.", "re.", "fmt."),
        # try resolving the first segment as a module to catch stdlib refs
        # that weren't resolved by the dotpath lookup.
        if not resolved_info and "." in target_name:
            first_segment = target_name.split(".")[0]
            if first_segment in _STDLIB_MODULE_PREFIXES or first_segment.startswith("std::"):
                resolved_info = scope_manager.resolve_symbol_dotpath(first_segment)
                if resolved_info:
                    strategy = "stdlib_method"
                    return resolved_info, strategy

        # 1c. Receiver-type-aware method resolution: if the stub is a
        # method call (e.g., "cursor.execute"), infer the receiver type
        # and look up the method on that type. This resolves calls on
        # project-internal types and stdlib types (rust-analyzer pattern).
        if not resolved_info:
            resolved_info = self._resolve_method_call(stub, graph, scope_manager)
            if resolved_info:
                strategy = "receiver_type"
                return resolved_info, strategy

        # 2. Try building qualified path from parent stubs if any
        if not resolved_info:
            incoming = [r for r in graph.get_rels_by_endpoint(stub.id) if r.target_id == stub.id]
            for rel in incoming:
                source_ent = graph.get_entity(rel.source_id)
                if source_ent and source_ent.is_contextual_stub:
                    parent_name = source_ent.metadata.get("target_name")
                    if parent_name:
                        full_path = f"{parent_name}.{target_name}"
                        resolved_info = scope_manager.resolve_symbol_dotpath(full_path)
                        if resolved_info:
                            strategy = "parent_chain"
                            break

        if resolved_info:
            return resolved_info, strategy

        # 3. Caller-scope qualified path
        if caller_scope:
            parts = caller_scope.split()
            if len(parts) >= 5:
                scope_path = parts[4]
            else:
                scope_path = caller_scope

            base_path = scope_path.split('#')[0].split('(')[0]
            if '/' in base_path:
                parent_dir = base_path.rsplit('/', 1)[0]
                qualified_try = f"{parent_dir}/{target_name}"
                resolved_info = scope_manager.resolve_symbol_strict(qualified_try)
                if not resolved_info:
                    qualified_try_dot = qualified_try.replace('/', '.')
                    resolved_info = scope_manager.resolve_symbol_strict(qualified_try_dot)

                if resolved_info:
                    strategy = "scope_qualified"
                    return resolved_info, strategy

        return None, "unresolved"

    def resolve_stub_on_demand(
        self,
        stub_id: str,
        graph: "GraphBackend",
        scope_manager: ScopeManager,
    ) -> str | None:
        """Resolve a single stub on demand — called by graph queries.

        Implements rust-analyzer's on-demand evaluation pattern (Phase 5):
        - Check if already resolved (cache hit)
        - If not, run the full resolution pipeline for this single stub
        - Cache the result in stub metadata

        This avoids resolving thousands of stubs upfront; only resolves what
        queries actually need.

        Returns:
            The resolved target entity ID, or None if the stub could not be
            resolved or is not a contextual stub.
        """
        stub = graph.get_entity(stub_id)
        if not stub or not stub.is_contextual_stub:
            return None

        # Cache hit — already resolved
        if stub.metadata.get("stub_resolution_state") == "resolved":
            return stub.metadata.get("resolved_target_id")

        # Already pruned — nothing to do
        if stub.metadata.get("stub_resolution_state") == "pruned":
            return None

        # Run resolution pipeline for this single stub
        resolved_info, strategy = self._resolve_single_stub(
            stub, graph, scope_manager
        )

        if resolved_info:
            updated_meta = dict(stub.metadata)
            updated_meta["stub_resolution_state"] = "resolved"
            updated_meta["resolved_target_id"] = resolved_info.symbol_id
            updated_meta["resolution_strategy"] = strategy
            updated_meta["resolution_confidence"] = _RESOLUTION_CONFIDENCE.get(strategy, 0.5)
            graph.update_entity(stub.id, stub._evolve(metadata=updated_meta))
            return resolved_info.symbol_id

        # Try pruning — if it's a common method name on unknown receiver,
        # mark as pruned rather than leaving as pending
        if self._should_prune_stub(stub):
            updated_meta = dict(stub.metadata)
            updated_meta["stub_resolution_state"] = "pruned"
            updated_meta["prune_reason"] = "common_method_unknown_receiver"
            updated_meta["resolution_confidence"] = 0.0
            updated_meta["resolution_strategy"] = "unresolved"
            graph.update_entity(stub.id, stub._evolve(metadata=updated_meta))

        return None

    def _should_prune_stub(self, stub: Entity) -> bool:
        """Conservative pruning of common method names on unknown types.

        Pruning rules (Eclipse CDT pattern):
        1. Don't prune resolved stubs — they have a resolution target
        2. Prune stubs whose target is a common method name (unwrap, clone,
           map, etc.) AND whose receiver type is unknown — these are stdlib
           methods that don't need to be tracked as unresolved gaps
        3. Don't prune stubs with a known receiver type but unresolved method
           — that's a real gap worth keeping for investigation

        This reduces graph noise without hiding genuine resolution failures.
        """
        # Don't prune already-resolved stubs
        if stub.metadata.get("stub_resolution_state") == "resolved":
            return False

        target_name = stub.metadata.get("target_name", "")

        # Extract the method name (last segment after the dot)
        if "." in target_name:
            method_name = target_name.rsplit(".", 1)[-1]
        else:
            method_name = target_name

        if method_name in _PRUNABLE_METHOD_NAMES:
            # Check if receiver type is known
            receiver_type = stub.metadata.get("receiver_type")
            if not receiver_type:
                # Receiver type is unknown — this is a stdlib method on an
                # unknown type. Safe to prune.
                return True

        return False  # Keep for investigation

    def build_graph(
        self,
        root: str,
        extractor: ASTExtractor | None = None,
        extensions: list[str] | None = None,
        max_workers: int = 0,
        max_file_size_kb: int | None = None,
        verbose: bool = False,
        metrics_callback: Callable[[str, Dict[str, Any]], None] | None = None,
        index_id: str | None = None,
        ast_cache_enabled: bool | None = None,
        include_gaps: bool | None = None,
        file_list: list[str] | None = None,
        write_callback: Callable[[str, dict], None] | None = None,
        external_scope_manager: ScopeManager | None = None,
        graph_backend: str | None = None,
        skip_orphan_pruning: bool = False,
        lazy_stub_resolution: bool = False,
    ) -> "InMemoryGraph | ArrowGraph":
        """
        Walk *root* recursively, index every matching source file, and return
        a populated graph (InMemoryGraph or ArrowGraph depending on backend).

        When *extractor* is None (default), the language is inferred from the
        file extension via the registry — a mixed-language repo is fully indexed
        in a single pass.

        When *file_list* is provided, only those specific files are indexed
        (skipping the directory walk). This is used by incremental patch operations.

        Args:
            root: Root directory to walk.
            extractor: Optional explicit extractor (overrides registry).
            extensions: File extensions to include, e.g. [".py", ".ts"].
                        None includes every supported extension.
            max_workers: Number of parallel threads. 0 = auto (cpu_count * 2).
            max_file_size_kb: Skip files larger than this (KB). Default 500KB.
            verbose: Print progress to stdout.
            metrics_callback: Optional callback for metrics collection.
            index_id: Optional index ID to stamp on entities.
            ast_cache_enabled: Optional override for AST cache usage in this run.
            include_gaps: Optional override for gap entities and file snapshots.
            file_list: Optional list of specific file paths to index. When provided,
                       directory walk is skipped and only these files are processed.
            graph_backend: Optional backend override ("auto" | "in-memory" |
                       "arrow"). None resolves from graph.backend config.
            skip_orphan_pruning: When True, skip the orphan node pruning pass.
                       Used by incremental patch operations where only a subset
                       of files are parsed and entities may appear disconnected
                       only because their cross-file relationships are not yet
                       materialized in the batch graph.
            lazy_stub_resolution: When True, skip upfront stub resolution.
                       Stubs remain in "pending" state and can be resolved
                       on-demand via resolve_stub_on_demand(). This implements
                       the rust-analyzer/Pyright on-demand pattern for large
                       repos where indexing speed matters more than upfront
                       completeness. Default: False (eager resolution).

        Returns:
            Populated graph (compacted ArrowGraph when backend="arrow").

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

        # Load config early so memory thresholds and worker caps are config-driven
        cfg = get_config_cached()
        memory_cfg = cfg.get("memory", {})
        warning_threshold_mb = float(memory_cfg.get("warning_threshold_mb", 800.0))
        critical_threshold_mb = float(memory_cfg.get("critical_threshold_mb", 1500.0))
        rss_flush_threshold_mb = float(memory_cfg.get("rss_flush_threshold_mb", 1000.0))
        max_per_worker_mb = float(memory_cfg.get("max_per_worker_mb", 150.0))

        # Use memory monitoring for the entire indexing pipeline
        actual_workers: int = 1
        with memory_monitor(
            "build_graph",
            warning_threshold_mb=warning_threshold_mb,
            critical_threshold_mb=critical_threshold_mb,
        ) as monitor:
            from batho.modules.extraction.submodules.parser_factory.detector import default_detector
            from batho.modules.extraction.submodules.parser_factory.registry import get_extractor as _registry_get_extractor
            configured_max_file_size_kb = (
                max_file_size_kb
                if max_file_size_kb is not None
                else cfg["indexer"]["max_file_size_kb"]
            )
            configured_max_workers = (
                max_workers if max_workers > 0 else cfg["indexer"].get("max_workers", 0)
            )
            max_indexed_files_cap: Optional[int] = cfg["indexer"].get("max_indexed_files")
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
            bsg_cache_cfg = bsg_cfg.get("cache", {})
            # Extract bidirectional gap configuration
            bidirectional_cfg = bsg_cfg.get("bidirectional", {})
            include_gaps_cfg = bool(bidirectional_cfg.get("include_gaps", False))
            include_gaps_flag = (
                include_gaps_cfg if include_gaps is None else bool(include_gaps)
            )
            # Set parsing config for all extractors
            from batho.modules.extraction.submodules.parser_factory.registry import set_parsing_config

            bsg_parsing_cfg = bsg_cfg.get("parsing", {})
            set_parsing_config(bsg_parsing_cfg)

            bsg_symbol_cfg = bsg_cfg.get("symbol_resolution", {})
            symbol_resolution_enabled = bsg_symbol_cfg.get("enabled", True)
            max_unresolved_attempts = int(bsg_symbol_cfg.get("max_unresolved_attempts", 10))
            prune_unresolved = bool(bsg_symbol_cfg.get("prune_unresolved", True))

            ignore_spec = load_ignore_spec(
                root_path,
                extra_patterns=cfg["indexer"].get("ignore_patterns"),
                ignore_files=cfg["indexer"].get("ignore_files"),
                default_patterns_file=cfg["indexer"].get("default_patterns_file"),
            )

            # --- Collect files to process ---
            candidates: list[tuple[Path, str]] = []  # (path, rel_str)
            self._unindexed_files = []

            if file_list:
                # Use specific file list (incremental patch mode)
                for file_path_str in file_list:
                    file_path = Path(file_path_str).resolve()
                    if not file_path.is_file():
                        continue
                    # Check ignore patterns
                    try:
                        rel_path = file_path.relative_to(root_path).as_posix()
                    except ValueError:
                        rel_path = str(file_path)
                    if ignore_spec and ignore_spec.match_file(rel_path):
                        continue

                    suffix = file_path.suffix.lower()

                    if extractor is not None:
                        if ext_set is not None and suffix not in ext_set:
                            continue
                        candidates.append((file_path, str(file_path)))
                    else:
                        file_extractor = _registry_get_extractor(suffix)
                        if file_extractor is None:
                            self._unindexed_files.append((str(file_path), rel_path))
                            continue
                        if ext_set is not None and suffix not in ext_set:
                            continue
                        candidates.append((file_path, str(file_path)))

                    if max_indexed_files_cap and len(candidates) >= max_indexed_files_cap:
                        break
            else:
                # Walk directory tree (full build mode)
                for dirpath, dirnames, filenames in walk_ignored_filtered(root_path, spec=ignore_spec):
                    for filename in filenames:
                        file_path = dirpath / filename
                        if not file_path.is_file():
                            continue

                        suffix = file_path.suffix.lower()

                        if extractor is not None:
                            if ext_set is not None and suffix not in ext_set:
                                continue
                            candidates.append((file_path, str(file_path)))
                        else:
                            file_extractor = _registry_get_extractor(suffix)
                            if file_extractor is None:
                                try:
                                    rel = file_path.relative_to(root_path).as_posix()
                                except ValueError:
                                    rel = str(file_path)
                                self._unindexed_files.append((str(file_path), rel))
                                continue
                            if ext_set is not None and suffix not in ext_set:
                                continue
                            candidates.append((file_path, str(file_path)))

                        if max_indexed_files_cap and len(candidates) >= max_indexed_files_cap:
                            break
                    if max_indexed_files_cap and len(candidates) >= max_indexed_files_cap:
                        break

            # Check for case-insensitive collisions if on a case-insensitive filesystem
            from batho.utils.path_sanitizer import is_filesystem_case_insensitive
            if is_filesystem_case_insensitive(root_path):
                seen_lower = {}
                for file_path, rel in candidates:
                    rel_lower = rel.lower()
                    if rel_lower in seen_lower:
                        msg = f"Case-insensitive path collision detected: '{rel}' collides with '{seen_lower[rel_lower]}'."
                        self.logger.warning("path_case_collision", warning=msg)
                        if not hasattr(self, "warnings"):
                            self.warnings = []
                        self.warnings.append(msg)
                    else:
                        seen_lower[rel_lower] = rel

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

            # Cap by available RAM using configured per-worker footprint
            actual_workers = cap_workers_by_ram(actual_workers, max_per_worker_mb)
            self.logger.info(
                "indexer_workers_selected",
                workers=actual_workers,
                configured_max=configured_max_workers,
                max_per_worker_mb=max_per_worker_mb,
            )

            errors = 0

            # Check memory usage after operation and cleanup if needed
            if monitor and hasattr(monitor, "get_memory_stats"):
                final_stats = monitor.get_memory_stats()
                if final_stats.rss_mb > rss_flush_threshold_mb:  # If memory usage is high
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

            files_parsed = 0
            files_skipped = 0
            files_cached = 0
            start_ts = os.times().elapsed if hasattr(os, "times") else 0.0

            # --- Graph backend selection (in-memory vs arrow) ---
            from batho.modules.graph.builder.factory import (
                AVG_ENTITIES_PER_FILE,
                create_graph,
                resolve_graph_backend,
            )

            backend_cfg = cfg.get("graph", {}).get("backend", {})
            from batho.core.config.models import GraphBackendConfig as _GBC

            _gbd = _GBC()  # single source of truth for backend defaults
            configured_backend = graph_backend or backend_cfg.get("backend", _gbd.backend)
            estimated_entities = len(candidates) * AVG_ENTITIES_PER_FILE
            resolved_backend = resolve_graph_backend(
                configured_backend,
                len(candidates),
                estimated_entities,
                backend_cfg.get("auto_threshold_files", _gbd.auto_threshold_files),
                backend_cfg.get("auto_threshold_entities", _gbd.auto_threshold_entities),
            )
            self.logger.info(
                "graph_backend_selected",
                backend=resolved_backend,
                candidates=len(candidates),
                estimated_entities=estimated_entities,
                configured=configured_backend,
            )

            staging_dir: Path | None = None
            if resolved_backend == "arrow":
                # Containment: arrow_staging_dir comes from the indexed repo's
                # config/env — it must stay under <root>/.batho (absolute
                # paths and ".." escapes are rejected) because close() removes
                # staging artifacts at the end of the build.
                from batho.utils.path_sanitizer import PathSecurityError

                staging_cfg = backend_cfg.get("arrow_staging_dir", _gbd.arrow_staging_dir)
                staging_dir = (root_path / staging_cfg).resolve()
                batho_root = (root_path / ".batho").resolve()
                if staging_dir != batho_root and batho_root not in staging_dir.parents:
                    raise PathSecurityError(
                        f"graph.backend.arrow_staging_dir escapes {batho_root}: {staging_cfg!r}"
                    )
                # Preflight: fall back to in-memory when the staging area is
                # not writable (read-only mounts) instead of failing the build.
                try:
                    staging_dir.mkdir(parents=True, exist_ok=True)
                    probe = staging_dir / ".write_probe"
                    probe.write_bytes(b"")
                    probe.unlink()
                except OSError as exc:
                    self.logger.warning(
                        "graph_backend_arrow_unwritable_fallback",
                        staging_dir=str(staging_dir),
                        error=str(exc),
                    )
                    resolved_backend = "in-memory"
                    staging_dir = None

            graph = create_graph(
                resolved_backend,
                staging_dir=staging_dir,
                arrow_config=backend_cfg,
            )

            def _materialize_graph(
                results: list[tuple[str, list[Entity], list[Relationship], bool]]
            ) -> tuple[InMemoryGraph, int, int, int, int]:
                built_graph = InMemoryGraph()
                parsed = 0
                cached = 0
                skipped = 0
                local_errors = 0
                total = len(results)
                progress_interval = 0
                if total >= 1000:
                    progress_interval = max(200, total // 10)

                for index, (filepath, entities, relationships, cached_hit) in enumerate(
                    results, start=1
                ):
                    try:
                        built_graph.add_entities_batch(entities)
                        built_graph.add_relationships_batch(relationships)
                        parsed += 1
                        if cached_hit:
                            cached += 1
                        if progress_interval and index % progress_interval == 0:
                            self.logger.info(
                                "graph_materialize_progress",
                                processed=index,
                                total=total,
                                entities=len(built_graph.entities),
                                relationships=len(built_graph.relationships),
                            )
                    except Exception as graph_error:
                        _handle_file_error(filepath, graph_error, "graph_update")
                        local_errors += 1
                        skipped += 1
                return built_graph, parsed, cached, skipped, local_errors

            # --- SINGLE-PASS PARALLEL EXTRACTION & RESOLUTION ---
            package_obj = detect_package_from_config(root_path)
            package_dict = package_obj.to_dict() if package_obj else None

            # Store precompiled content hashes for async persistence/file tracking.
            # Heavy blobs are streamed to persistence via write_callback instead.
            self._precompiled_hashes: dict[str, str] = {}

            def on_result_extracted(res: tuple) -> None:
                if res is None:
                    return
                filepath = res[0]
                content_hash = res[1]
                hollow_bytes = res[2]
                rel_bytes = res[3]
                agent_blob = res[4]
                storage_blob = res[5]

                self._precompiled_hashes[filepath] = content_hash

                if write_callback is not None:
                    try:
                        file_rel = Path(filepath).relative_to(root_path).as_posix()
                    except ValueError:
                        file_rel = filepath
                    blob_data = {
                        "content_hash": content_hash,
                        "agent_blob": agent_blob,
                        "storage_blob": storage_blob,
                        "rels_blob": rel_bytes,
                    }
                    write_callback(file_rel, blob_data)

            self.logger.info("single_pass_extraction_started", candidates=len(candidates))
            bsg_cfg_payload = dict(bsg_cfg)
            bsg_cfg_payload["root_path"] = str(root_path)
            bsg_cfg_payload["rules"] = cfg.get("rules", {})

            # Ensure cache path is present so workers can initialize BathoCache
            _cache_cfg = dict(bsg_cfg_payload.get("cache", {}))
            if not _cache_cfg.get("path") and self._cache._db is not None:
                _cache_cfg["path"] = str(self._cache._db.repo_root)
                bsg_cfg_payload["cache"] = _cache_cfg

            ast_cache_dir_str = (
                str(self._cache._ast_cache.cache_dir)
                if self._cache._ast_cache is not None
                else None
            )
            results, extract_errors, merged_audit = extract_and_emit_parallel(
                candidates,
                configured_max_file_size_kb,
                bsg_cfg_payload,
                package_dict=package_dict,
                index_id=index_id,
                include_gaps=include_gaps_flag,
                result_callback=on_result_extracted,
                ast_cache_dir=ast_cache_dir_str,
            )
            errors += extract_errors

            # Add failed or skipped candidates to unindexed files so they are tracked as opaque snapshots
            successful_paths = {r[0] for r in results}
            for file_path, filepath in candidates:
                if filepath not in successful_paths:
                    try:
                        rel = file_path.relative_to(root_path).as_posix()
                    except ValueError:
                        rel = str(filepath)
                    if (str(file_path), rel) not in self._unindexed_files:
                        self._unindexed_files.append((str(file_path), rel))

            # Populate ScopeManager with all definition symbols from GlobalSymbolManifests
            scope_manager = ScopeManager()
            for result in results:
                # New 8-tuple: (filepath, content_hash, hollow_bytes, rel_bytes, agent_blob, storage_blob, global_manifest, local_hits)
                filepath, content_hash, hollow_bytes, rel_bytes, agent_blob, storage_blob, global_manifest, _ = result
                for entry in global_manifest:
                    scope_manager.define_global_symbol_qualified(
                        name=entry["name"],
                        symbol_id=entry["id"],
                        symbol_type=entry["type"],
                        filepath=filepath,
                        is_global=True,
                    )

            # Merge external (dependency) symbols into project scope
            if external_scope_manager is not None:
                _merge_external_scope(scope_manager, external_scope_manager)

            # Materialize graph using hollow topology (no raw_content/raw_bytes)
            import msgpack
            import zstandard as zstd
            zstd_decompressor = zstd.ZstdDecompressor()

            total_rules_applied = 0
            total_entities_tagged = 0
            total_rules_loaded = 0

            # Capture indexed file paths up front so `results` can be freed
            # incrementally during the materialization loop below.
            indexed_files = [result[0] for result in results]

            for i in range(len(results)):
                result = results[i]
                results[i] = None  # free heavy blobs as soon as consumed
                try:
                    # New 8-tuple: (filepath, content_hash, hollow_bytes, rel_bytes, agent_blob, storage_blob, global_manifest, local_hits)
                    filepath, content_hash, hollow_bytes, rel_bytes, agent_blob, storage_blob, _, local_hits = result
                    total_rules_applied += local_hits.get("rules_applied", 0)
                    total_entities_tagged += local_hits.get("entities_tagged", 0)
                    if not total_rules_loaded:
                        total_rules_loaded = local_hits.get("rules_loaded", 0)

                    # Deserialize hollow topology (lightweight - not compressed)
                    hollow_topology = msgpack.unpackb(hollow_bytes)

                    # Add hollow entities to graph using model_construct (bypasses Pydantic validation)
                    for node in hollow_topology:
                        # Convert integer type to EntityType enum for proper comparison
                        # (worker stores e.type.value which is an integer)
                        node_type = node["type"]
                        if isinstance(node_type, int):
                            node_type = EntityType(node_type)

                        # Preserve stub resolution metadata if present
                        metadata = {"is_hollow": True}
                        if "caller_scope" in node:
                            metadata["caller_scope"] = node["caller_scope"]
                        if "target_name" in node:
                            metadata["target_name"] = node["target_name"]
                        if "receiver_var" in node:
                            metadata["receiver_var"] = node["receiver_var"]

                        ent = Entity.model_construct(
                            id_override=node["id"],
                            name=node["name"],
                            type=node_type,
                            file=node["file"],
                            start_line=node.get("start_line", 1),
                            end_line=node.get("end_line", 1),
                            start_byte=node.get("start_byte", 0),
                            end_byte=node.get("end_byte", 0),
                            parent_id=node.get("parent_id"),
                            raw_content=None,
                            raw_bytes=None,
                            metadata=metadata
                        )
                        graph.add_entity(ent)

                    # Deserialize relationships
                    raw_rels = msgpack.unpackb(zstd_decompressor.decompress(rel_bytes))
                    relationships = [Relationship.from_dict(d) for d in raw_rels]
                    graph.add_relationships_batch(relationships)

                    files_parsed += 1
                except Exception as mat_error:
                    _handle_file_error(filepath, mat_error, "graph_materialize")
                    errors += 1
                    files_skipped += 1

            results.clear()  # release any remaining extraction buffers

            # Register all project-internal definitions as global symbols so
            # that stubs referencing project functions/classes/methods defined
            # in other files/scope can be resolved (rust-analyzer DefMap pattern).
            _t_project_symbols = time.monotonic()
            self._register_project_symbols(graph, scope_manager)
            project_symbol_ms = (time.monotonic() - _t_project_symbols) * 1000
            # Clear failed-lookup cache: new project symbols may resolve
            # stubs that previously failed during extraction.
            scope_manager.clear_failed_lookups()

            # Batch resolve contextual stubs using populated ScopeManager.
            # Phase 5: when lazy_stub_resolution=True, skip upfront resolution.
            _t_stub_res = time.monotonic()
            stub_resolved_count, stub_unresolved_count = self.resolve_contextual_stubs(
                graph, scope_manager, lazy=lazy_stub_resolution,
            )
            stub_resolution_ms = (time.monotonic() - _t_stub_res) * 1000

            # Materialize EXTERNAL_SYMBOL entities in the graph from the scope manager
            # (after stub resolution so only symbols actually used as resolution targets are kept)
            external_symbol_count = _materialize_external_symbols(graph, scope_manager)

            # Second stub resolution pass: now that EXTERNAL_SYMBOL entities exist
            # in the graph, stubs whose targets were just materialized can be
            # re-resolved. This catches stubs that reference stdlib/third-party
            # symbols which weren't in the graph during the first pass.
            # Skipped in lazy mode (on-demand resolution handles it).
            if external_symbol_count > 0 and not lazy_stub_resolution:
                # Clear failed-lookup cache: newly materialized external symbols
                # may resolve stubs that failed in the first pass.
                scope_manager.clear_failed_lookups()
                _t_stub_res_2 = time.monotonic()
                second_resolved, second_unresolved = self.resolve_contextual_stubs(graph, scope_manager)
                stub_resolved_count += second_resolved
                stub_unresolved_count = second_unresolved  # replace with latest count
                # Add only the second pass's own duration to avoid double-counting
                # the first pass + materialization time (which is already in
                # stub_resolution_ms from line 2037).
                stub_resolution_ms += (time.monotonic() - _t_stub_res_2) * 1000

            derived_hierarchy_edges = self._derive_hierarchy_relations(graph)
            derived_overrides_edges = self._derive_override_edges(graph)

            semantic_stats: dict[str, int] = {
                "semantic_tags_added": 0,
                "semantic_edges_added": 0,
            }
            try:
                from batho.modules.compression import apply_semantic_overlay

                semantic_stats = apply_semantic_overlay(
                    graph=graph,
                    root_path=root_path,
                    logger=self.logger,
                )
            except Exception as exc:
                self.logger.warning("bsg_semantic_stage_failed", error=str(exc))

            # Load and apply BSG rules
            rules_cfg = cfg.get("rules", {}) if isinstance(cfg, dict) else {}
            plugins_cfg = cfg.get("plugins", {}) if isinstance(cfg, dict) else {}
            if isinstance(rules_cfg, dict) and isinstance(plugins_cfg, dict):
                overrides = plugins_cfg.get("overrides")
                if overrides:
                    rules_cfg = {**rules_cfg, "plugins_overrides": overrides}

            rule_stats: dict[str, Any] = {
                "enabled": False,
                "rules_loaded": 0,
                "rules_applied": 0,
                "entities_updated": 0,
                "errors": [],
            }

            if rules_cfg and rules_cfg.get("enabled", False):
                rule_stats = {
                    "enabled": True,
                    "rules_loaded": total_rules_loaded,
                    "rules_applied": total_rules_applied,
                    "entities_updated": total_entities_tagged,
                    "security_audit": merged_audit,
                    "errors": [],
                }
            else:
                rule_stats = {
                    "enabled": bool(rules_cfg),
                    "rules_loaded": 0,
                    "rules_applied": 0,
                    "entities_updated": 0,
                    "security_audit": merged_audit,
                    "errors": [],
                }


            if skip_orphan_pruning:
                orphan_pruned_count = 0
                self.logger.info("orphan_pruning_skipped", reason="patch_mode")
            else:
                orphan_pruned_count = self.prune_orphan_nodes(graph)
            consistency_issues, cycle_counts, broken_relationships, cycle_fatal = (
                self._collect_consistency_issues(graph)
            )
            import_cycle_count = cycle_counts.get("imports", 0)
            inherit_cycle_count = cycle_counts.get("inherits", 0)

            # All post-processing complete: compact Arrow backend into its
            # memory-mapped read-only form (no-op for the in-memory backend).
            graph.compact()

            elapsed = (
                (os.times().elapsed if hasattr(os, "times") else 0.0) - start_ts
                if start_ts
                else None
            )

            self.build_stats = {
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
                "symbol_index_size": scope_manager.global_symbol_count,
                "import_cycle_count": int(import_cycle_count),
                "inherit_cycle_count": int(inherit_cycle_count),
                "orphan_pruned_count": int(orphan_pruned_count),
                "graph_consistency_issue_count": len(consistency_issues),
                "unresolved_entities_count": sum(
                    1 for e in graph.entities.values() if e.type in (EntityType.UNRESOLVED, EntityType.EXTERNAL_SYMBOL)
                ),
                "unresolved_pruned_count": sum(
                    1 for e in graph.entities.values()
                    if e.is_contextual_stub
                    and e.metadata.get("stub_resolution_state") == "pruned"
                ),
                "unresolved_resolved_count": int(stub_resolved_count),
                "external_symbol_count": int(external_symbol_count),
                # Phase 5: per-phase timing metrics (milliseconds)
                "project_symbol_ms": round(project_symbol_ms, 1),
                "stub_resolution_ms": round(stub_resolution_ms, 1),
                "lazy_stub_resolution": bool(lazy_stub_resolution),
                "derived_hierarchy_edges": derived_hierarchy_edges,
                "derived_overrides_edges": derived_overrides_edges,
                "semantic_tags_added": int(semantic_stats.get("semantic_tags_added", 0)),
                "semantic_edges_added": int(semantic_stats.get("semantic_edges_added", 0)),
                "rules_enabled": bool(rule_stats.get("enabled", False)),
                "rules_loaded": int(rule_stats.get("rules_loaded", 0)),
                "rules_applied": int(rule_stats.get("rules_applied", 0)),
                "entities_rule_tagged": int(rule_stats.get("entities_updated", 0)),
                "rules": rule_stats,
                "security_audit": rule_stats.get("security_audit"),
                "include_gaps": include_gaps_flag,
            }

            self.logger.info(
                "build_graph_complete",
                root=root,
                **self.build_stats,
            )

            if metrics_callback:
                try:
                    metrics_callback("batho.index", self.build_stats)
                except Exception as exc:
                    self.logger.warning("metrics_callback_failed", error=str(exc))

            if verbose:
                self.logger.info(
                    "index_verbose_summary",
                    files_parsed=files_parsed,
                    entity_count=len(graph.entities),
                    files_skipped=files_skipped,
                    files_cached=files_cached,
                )

            # Write snapshots for unindexed files to cache (Bug 1 & Bug 5 Fix)
            if bsg_cache_cfg.get("enabled", True):
                from batho.core.schemas import FileSnapshot
                from batho.utils.hash import compute_bytes_hash, _is_binary
                from batho.utils.file_io import read_file_bytes

                for abs_path_str, rel in self._unindexed_files:
                    try:
                        abs_path = Path(abs_path_str)
                        if abs_path.exists():
                            stat_info = abs_path.stat()
                            size = stat_info.st_size
                            content = read_file_bytes(abs_path_str, max_size_kb=configured_max_file_size_kb, detect_binary=True)
                            if content is not None:
                                content_hash = compute_bytes_hash(content)
                                existing_snap = self._cache.get_file_snapshot(abs_path_str) or self._cache.get_file_snapshot(rel)
                                if existing_snap is None or existing_snap.file_hash != content_hash:
                                    _snap = FileSnapshot.create_opaque(
                                        file_path=abs_path_str,
                                        content=content,
                                        file_size=size,
                                    )
                                    self._cache.set_file_snapshot(_snap)
                    except Exception as e:
                        self.logger.warning("failed_to_write_opaque_snapshot", filepath=abs_path_str, error=str(e))

            # Validate graph consistency before returning
            if consistency_issues:
                self.logger.warning(
                    "initial_graph_consistency_issues",
                    issue_count=len(consistency_issues),
                )
                if broken_relationships and (strict_mode or fail_on_warning):
                    raise RuntimeError(
                        "Initial graph build produced inconsistent relationships"
                    )
                if (import_cycle_count or inherit_cycle_count) and (
                    cycle_fatal or strict_mode or fail_on_warning
                ):
                    raise RuntimeError(
                        "Initial graph build detected cyclic dependencies"
                    )

            self._indexed_files = indexed_files

            self._graph = graph
            return graph

    def index_file(
        self,
        filepath: str,
        extractor: ASTExtractor,
        max_file_size_kb: int | None = None,
        include_gaps: bool = False,
    ) -> tuple[list[Entity], list[Relationship]]:
        """
        Index a single file on-demand (used by the MCP `index_file` tool).

        Always re-parses; updates the cache entry.

        Args:
            filepath: Absolute path to the file.
            extractor: Language-specific ASTExtractor instance.
            max_file_size_kb: Skip if file exceeds this size.
            include_gaps: When True, emit SYNTAX_GLUE entities for full byte coverage.

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
            entities, rels = extractor.parse_file(
                filepath, content, include_gaps=include_gaps
            )
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
                content_hash = compute_bytes_hash(content)
                ttl_days = bsg_cache_cfg.get("ttl_days", 30)
                self._cache.set_ast(
                    filepath,
                    content_hash,
                    entities,
                    rels,
                    mtime,
                    size,
                    ttl_days,
                    variant=build_ast_cache_variant(
                        include_gaps=include_gaps,
                        parsing_config=get_config_cached().get("bsg", {}).get("parsing", {}),
                    ),
                )
            except OSError:
                pass

        return entities, rels

    def reconstruct_file(
        self,
        file_path: str,
        entities: list[Entity] | None = None,
        original_hash: str | None = None,
        original_content: str | None = None,
    ) -> Any:
        """
        Reconstruct a file from its BSG entities.

        If *entities* is None, entities are looked up from the last built
        graph via :meth:`entities_by_file`.

        Args:
            file_path: Path to the file to reconstruct.
            entities: Optional explicit entity list.  If omitted, resolved
                      from the internal graph.
            original_hash: Optional expected SHA256 hash.
            original_content: Optional original content string.

        Returns:
            A ``ReconstructionResult``.

        Raises:
            ReconstructionError: If entities are missing or invalid.
            IntegrityError: If hash verification fails.
        """
        from batho.modules.graph.reconstructor.reconstructor import FileReconstructor

        reconstructor = FileReconstructor()

        # Resolve entities from the in-memory graph if not provided
        if entities is None and hasattr(self, "_graph"):
            entities = list(self._graph.entities_by_file(file_path))

        result = reconstructor.reconstruct_file(
            file_path=file_path,
            entities=entities or [],
            original_hash=original_hash,
            original_content=original_content,
        )
        self._last_reconstruction = result
        return result

    def invalidate(self, filepath: str) -> None:
        """Force re-parse of filepath on the next build_graph call."""
        self._cache.delete_ast_by_path(filepath)

    def stats(self) -> dict[str, int]:
        """Return cache statistics."""
        cache_stats = self._cache.get_stats()
        return {"cached_files": cache_stats["ast_entry_count"]}

    def get_cache_stats(self) -> dict[str, Any]:
        """Get detailed cache statistics for monitoring."""
        return self._cache.get_stats()

    def mark_keep_node(self, node_id: str) -> None:
        """Mark a node to be preserved during orphan pruning."""
        self._keep_nodes.add(node_id)

    def _cycle_key(self, cycle: list[str]) -> tuple[str, ...]:
        if not cycle:
            return ()
        base = cycle[:-1] if len(cycle) > 1 and cycle[0] == cycle[-1] else list(cycle)
        if not base:
            return ()
        rotations = [tuple(base[i:] + base[:i]) for i in range(len(base))]
        return min(rotations)

    def _format_cycle_path(self, graph: "GraphBackend", cycle: list[str]) -> str:
        labels: list[str] = []
        for node_id in cycle:
            entity = graph.get_entity(node_id)
            labels.append(entity.name if entity is not None else node_id)
        return " -> ".join(labels)

    def find_cycles(
        self, graph: "GraphBackend", relationship_type: RelationshipType
    ) -> list[list[str]]:
        adjacency: dict[str, list[str]] = defaultdict(list)
        for rel in graph.relationships:
            if rel.type == relationship_type:
                if rel.source_id == rel.target_id and relationship_type == RelationshipType.IMPORTS:
                    continue  # skip self-loops for imports (recursion, not a cycle)
                adjacency[rel.source_id].append(rel.target_id)

        visited: set[str] = set()
        seen_keys: set[tuple[str, ...]] = set()
        cycles: list[list[str]] = []

        for start_node in list(adjacency.keys()):
            if start_node in visited:
                continue

            path_index: dict[str, int] = {}
            path_list: list[str] = []

            # stack holds tuples of (node, neighbor_index)
            stack = [(start_node, 0)]
            visited.add(start_node)
            path_index[start_node] = 0
            path_list.append(start_node)

            while stack:
                node, edge_idx = stack[-1]
                neighbors = adjacency.get(node, [])

                if edge_idx < len(neighbors):
                    neighbor = neighbors[edge_idx]
                    stack[-1] = (node, edge_idx + 1)

                    if neighbor in path_index:
                        # Cycle detected!
                        start_index = path_index[neighbor]
                        cycle = path_list[start_index:] + [neighbor]
                        key = self._cycle_key(cycle)
                        if key and key not in seen_keys:
                            seen_keys.add(key)
                            cycles.append(cycle)
                    elif neighbor not in visited:
                        visited.add(neighbor)
                        path_index[neighbor] = len(path_list)
                        path_list.append(neighbor)
                        stack.append((neighbor, 0))
                else:
                    stack.pop()
                    path_index.pop(node)
                    path_list.pop()

        return cycles

    def _collect_consistency_issues(
        self, graph: "GraphBackend"
    ) -> tuple[list[str], dict[str, int], bool, bool]:
        cfg = get_config_cached()
        graph_cfg = cfg.get("graph", {}) if isinstance(cfg, dict) else {}
        cycle_cfg = graph_cfg.get("cycle_detection", {}) if isinstance(graph_cfg, dict) else {}
        cycle_enabled = bool(cycle_cfg.get("enabled", True))
        cycle_fatal = bool(cycle_cfg.get("fatal", False))

        issues: list[str] = []
        cycle_counts = {"imports": 0, "inherits": 0}

        updater = IncrementalGraphUpdater()
        broken_relationships = not updater.validate_graph_consistency(graph)
        if broken_relationships:
            issues.append("Broken relationships detected in graph")

        if cycle_enabled:
            import_cycles = self.find_cycles(graph, RelationshipType.IMPORTS)
            inherit_cycles = self.find_cycles(graph, RelationshipType.INHERITS)
            cycle_counts["imports"] = len(import_cycles)
            cycle_counts["inherits"] = len(inherit_cycles)

            log_fn = self.logger.error if cycle_fatal else self.logger.warning
            for cycle in import_cycles:
                issues.append(
                    f"Cyclic import detected: {self._format_cycle_path(graph, cycle)}"
                )
                log_fn(
                    "cyclic_import_detected",
                    cycle=self._format_cycle_path(graph, cycle),
                )
            for cycle in inherit_cycles:
                issues.append(
                    f"Cyclic inheritance detected: {self._format_cycle_path(graph, cycle)}"
                )
                log_fn(
                    "cyclic_inheritance_detected",
                    cycle=self._format_cycle_path(graph, cycle),
                )

        return issues, cycle_counts, broken_relationships, cycle_fatal

    def validate_graph_consistency(self, graph: "GraphBackend") -> list[str]:
        """Validate graph consistency and return a list of issues."""
        issues, _, _, _ = self._collect_consistency_issues(graph)
        return issues

    def _is_exported_entity(self, entity: Entity) -> bool:
        meta = dict(entity.metadata or {})
        if meta.get("is_exported"):
            return True
        if meta.get("exported"):
            return True
        return False

    def is_orphan(
        self,
        graph: "GraphBackend",
        node_id: str,
        *,
        keep_exports: bool | None = None,
        keep_entry_points: bool | None = None,
    ) -> bool:
        if node_id in self._keep_nodes:
            return False

        entity = graph.get_entity(node_id)
        if entity is None:
            return False

        cfg = get_config_cached()
        graph_cfg = cfg.get("graph", {}) if isinstance(cfg, dict) else {}
        orphan_cfg = graph_cfg.get("orphan_pruning", {}) if isinstance(graph_cfg, dict) else {}
        keep_entry = (
            keep_entry_points
            if keep_entry_points is not None
            else bool(orphan_cfg.get("keep_entry_points", True))
        )
        keep_exports_flag = (
            keep_exports
            if keep_exports is not None
            else bool(orphan_cfg.get("keep_exports", True))
        )

        if keep_entry and entity.type == EntityType.ENTRY_POINT:
            return False
        if keep_exports_flag and self._is_exported_entity(entity):
            return False

        return not (
            graph.has_incoming_edges(node_id) or graph.has_outgoing_edges(node_id)
        )

    def prune_orphan_nodes(
        self,
        graph: "GraphBackend",
        *,
        keep_exports: bool | None = None,
        keep_entry_points: bool | None = None,
    ) -> int:
        cfg = get_config_cached()
        graph_cfg = cfg.get("graph", {}) if isinstance(cfg, dict) else {}
        orphan_cfg = graph_cfg.get("orphan_pruning", {}) if isinstance(graph_cfg, dict) else {}
        if not bool(orphan_cfg.get("enabled", True)):
            return 0

        keep_entry = (
            keep_entry_points
            if keep_entry_points is not None
            else bool(orphan_cfg.get("keep_entry_points", True))
        )
        keep_exports_flag = (
            keep_exports
            if keep_exports is not None
            else bool(orphan_cfg.get("keep_exports", True))
        )

        # 1. O(E) pass to collect all connected entity IDs
        active_node_ids = set()
        for rel in graph.relationships:
            active_node_ids.add(rel.source_id)
            active_node_ids.add(rel.target_id)

        # 2. O(V) pass to identify orphans using C-optimized set logic
        all_entity_ids = set(graph.entities.keys())
        orphan_ids = all_entity_ids - active_node_ids

        orphans = []
        for node_id in orphan_ids:
            if node_id in self._keep_nodes:
                continue
            entity = graph.get_entity(node_id)
            if entity is None:
                continue
            if keep_entry and entity.type == EntityType.ENTRY_POINT:
                continue
            # EXTERNAL_SYMBOL entities are reference targets (stdlib/third-party)
            # that may not have incoming edges yet; keep them so dependency
            # resolution benchmarks can find them in the artifact.
            if entity.type == EntityType.EXTERNAL_SYMBOL:
                continue
            if keep_exports_flag and self._is_exported_entity(entity):
                continue
            orphans.append(node_id)

        for node_id in orphans:
            # remove_node handles all index cleanup (orphans have no rels by
            # construction, so this is equivalent to the previous inline pops).
            graph.remove_node(node_id)

        if orphans:
            self.logger.info(
                "orphan_nodes_pruned",
                pruned=len(orphans),
            )

        return len(orphans)

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

    def _derive_hierarchy_relations(self, graph: "GraphBackend") -> int:
        """Derive INHERITS/IMPLEMENTS edges from entity metadata."""
        if not graph.entities:
            return 0

        name_to_id: dict[str, str] = {}
        for ent in graph.entities.values():
            name_to_id[ent.name] = ent.id
            if "." in ent.name:
                name_to_id[ent.name.split(".")[-1]] = ent.id
            if ent.type == EntityType.MODULE:
                name_to_id[Path(ent.file).stem] = ent.id

        existing = {
            (
                rel.source_id,
                rel.target_id,
                rel.type,
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

    def _derive_override_edges(self, graph: "GraphBackend") -> int:
        """Derive OVERRIDES edges from CONTAINS + INHERITS relationships."""
        if not graph.entities:
            return 0

        class_methods: dict[str, dict[str, list[str]]] = defaultdict(
            lambda: defaultdict(list)
        )
        parent_map: dict[str, set[str]] = defaultdict(set)
        existing = {
            (
                rel.source_id,
                rel.target_id,
                rel.type,
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

    def _merge_security_audits(self, audit1: dict, audit2: dict) -> dict:
        merged = {
            "schema_version": "interception-stats.v1",
            "plugins": {},
        }
        for audit in (audit1, audit2):
            if not audit:
                continue
            for plugin_id, data in audit.get("plugins", {}).items():
                if plugin_id in merged["plugins"]:
                    merged["plugins"][plugin_id]["interceptions"] += data.get("interceptions", 0)
                else:
                    merged["plugins"][plugin_id] = {
                        "plugin_id": plugin_id,
                        "name": data.get("name", ""),
                        "interceptions": data.get("interceptions", 0),
                    }
        return merged
