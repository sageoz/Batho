"""
backend/context/codegraph.py — Production Code Graph Indexer.

Improvements over prototype:
- JSON-based file state cache (no SQLAlchemy/aiosqlite dependency)
- mtime + SHA-256 hash check: skips unchanged files instantly (stat before hash)
- Parallel file extraction using ThreadPoolExecutor (I/O-bound, thread-safe)
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
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from batho_core.config import get_config_cached
from batho_core.utils.file_io import _read_file_content, read_file_bytes
from batho_core.utils.hash import compute_bytes_hash
from batho_core.utils.ignore import is_ignored, load_ignore_spec
from batho_core.utils.logging import get_logger

from .extractor import ASTExtractor
from .schema import Entity, EntityType, Relationship, RelationshipType

# Binary detection is now handled in batho_core.utils.file_io


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
        self.relationships: list[Relationship] = relationships if relationships is not None else []
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
        return (
            f"InMemoryGraph(entities={len(self.entities)}, relationships={len(self.relationships)})"
        )


# ---------------------------------------------------------------------------
# File state cache (JSON-based, replaces SQLAlchemy)
# ---------------------------------------------------------------------------


class _FileStateCache:
    """
    Lightweight JSON-based cache for file mtime + SHA-256.

    Structure: { "relative/path/to/file.py": {"mtime": float, "sha256": str} }

    All keys are stored as paths relative to *root* so the JSON file is
    portable and free of machine-specific absolute paths.

    The mtime check short-circuits the SHA-256 computation for unchanged
    files — stat() is orders of magnitude faster than hashing.
    """

    def __init__(self, cache_path: Path, root: Path | None = None) -> None:
        self._path = cache_path
        self._root = root  # workspace root for path normalisation
        self._data: dict[str, dict[str, Any]] = {}
        self._schema_version: str | None = None
        self._checksum_valid: bool = True
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and "files" in raw:
                    self._schema_version = raw.get("schema_version")
                    files = raw.get("files", {})
                    checksum = raw.get("_checksum")
                    calc = compute_bytes_hash(json.dumps(files, sort_keys=True).encode("utf-8"))
                    if checksum and checksum != calc:
                        self._mark_corrupt("checksum_mismatch")
                    else:
                        self._data = files
                else:
                    # backward compatibility (flat mapping)
                    self._data = raw if isinstance(raw, dict) else {}
            except (json.JSONDecodeError, OSError):
                self._mark_corrupt("read_failed")

    def _mark_corrupt(self, reason: str) -> None:
        self._checksum_valid = False
        self._data = {}
        try:
            if self._path.exists():
                timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                backup = self._path.with_name(f"{self._path.name}.corrupt.{timestamp}")
                self._path.replace(backup)
                get_logger(__name__, operation="index").warning(
                    "cache_marked_corrupt",
                    filepath=str(self._path),
                    backup=str(backup),
                    reason=reason,
                )
        except OSError:
            pass

    @property
    def checksum_valid(self) -> bool:
        return self._checksum_valid

    def _normalise(self, filepath: str) -> str:
        """Convert *filepath* to a relative key (no-op if already relative)."""
        if self._root is None:
            return filepath
        try:
            return Path(filepath).relative_to(self._root).as_posix()
        except ValueError:
            return filepath

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": get_config_cached().get("file_cache_schema_version", "file-cache.v1"),
            "files": self._data,
            "_checksum": compute_bytes_hash(json.dumps(self._data, sort_keys=True).encode("utf-8")),
        }
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self._path)  # Atomic rename

    def is_cached(self, filepath: str, content_hash: str) -> bool:
        """Return True if filepath's stored hash matches content_hash."""
        entry = self._data.get(self._normalise(filepath))
        if entry is None:
            return False
        return entry.get("sha256") == content_hash

    def update(self, filepath: str, mtime: float, content_hash: str) -> None:
        self._data[self._normalise(filepath)] = {"mtime": mtime, "sha256": content_hash}

    def invalidate(self, filepath: str) -> None:
        self._data.pop(self._normalise(filepath), None)


# ---------------------------------------------------------------------------
# CodeGraphIndexer
# ---------------------------------------------------------------------------


class CodeGraphIndexer:
    """
    Production code graph indexer for batho-v1.

    Features:
    - mtime + SHA-256 hash caching: skips unchanged files without hashing
    - Parallel extraction with ThreadPoolExecutor
    - Per-file exception isolation
    - .gitignore + .bathoignore support via pathspec
    - Binary file detection and size guard
    - Cross-file import resolution pass

    Usage::

        indexer = CodeGraphIndexer(cache_path=".ctn/file_cache.json")
        graph = indexer.build_graph(
            root="/path/to/repo",
            max_workers=8,
            max_file_size_kb=500,
        )
    """

    def __init__(self, cache_path: str = ".ctn/file_cache.json", root: str | None = None) -> None:
        self.logger = get_logger(__name__, operation="index")
        root_path = Path(root).resolve() if root else None
        self._cache = _FileStateCache(Path(cache_path), root=root_path)
        self._root: Path | None = root_path
        self.stats: Dict[str, Any] = {}

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

        Returns:
            Populated InMemoryGraph.
        """
        from .languages.detector import default_detector
        from .languages.registry import get_extractor as _registry_get_extractor

        root_path = Path(root).resolve()
        cfg = get_config_cached()
        configured_max_file_size_kb = (
            max_file_size_kb if max_file_size_kb is not None else cfg["indexer"]["max_file_size_kb"]
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

        ignore_spec = _load_ignore_spec(
            root_path,
            extra_patterns=cfg["indexer"].get("ignore_patterns"),
            ignore_files=cfg["indexer"].get("ignore_files"),
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
            print(f"  📁 Found {len(candidates)} candidate files")

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

        def _process_file(
            args: tuple[Path, str],
        ) -> tuple[str, list[Entity], list[Relationship], bool] | None:
            """Worker: size/binary guard, cache check (for metrics), parse, update cache."""

            nonlocal errors
            file_path, filepath = args

            try:
                size = file_path.stat().st_size
            except OSError:
                return None
            if size > configured_max_file_size_kb * 1024:
                self.logger.debug("skipping_large_file", filepath=filepath, size_kb=size // 1024)
                return None

            content = _read_file_content(filepath, configured_max_file_size_kb)
            if content is None:
                return None

            content_hash = compute_bytes_hash(content)
            cached_hit = self._cache.is_cached(filepath, content_hash)

            from .languages.detector import default_detector
            from .languages.registry import get_extractor as _registry_get_extractor

            suffix = file_path.suffix.lower()
            if extractor is not None:
                file_extractor: ASTExtractor | None = extractor
            else:
                file_extractor = default_detector.get_extractor(
                    file_path, content
                ) or _registry_get_extractor(suffix)
            if file_extractor is None:
                return None

            try:
                entities, relationships = file_extractor.parse_file(filepath, content)
            except Exception as exc:
                errors += 1
                self.logger.warning("file_parse_failed", filepath=filepath, error=str(exc))
                return None

            try:
                mtime = file_path.stat().st_mtime
                self._cache.update(filepath, mtime, content_hash)
            except OSError:
                pass

            return (filepath, entities, relationships, cached_hit)

        graph = InMemoryGraph()
        files_parsed = 0
        files_skipped = 0
        files_cached = 0
        start_ts = os.times().elapsed if hasattr(os, "times") else 0.0

        with ThreadPoolExecutor(max_workers=actual_workers) as pool:
            futures = {pool.submit(_process_file, args): args for args in candidates}
            for future in as_completed(futures):
                result = future.result()
                if result is None:
                    files_skipped += 1
                    continue
                filepath, entities, relationships, cached_hit = result
                for entity in entities:
                    graph.add_entity(entity)
                for rel in relationships:
                    graph.add_relationship(rel)
                files_parsed += 1
                if cached_hit:
                    files_cached += 1

        try:
            self._cache.save()
        except Exception as exc:
            self.logger.warning("cache_save_failed", error=str(exc))

        graph = self._resolve_imports(graph)

        elapsed = (
            (os.times().elapsed if hasattr(os, "times") else 0.0) - start_ts if start_ts else None
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
            "cache_valid": self._cache.checksum_valid,
            "workers_used": actual_workers,
        }

        if (fail_on_warning or strict_mode) and errors > 0:
            raise RuntimeError(
                f"Parse errors encountered ({errors}); strict={strict_mode} fail_on_warning={fail_on_warning}"
            )

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
            print(
                f"  ✓ Indexed {files_parsed} files → {len(graph.entities)} entities "
                f"(skipped {files_skipped}, cached {files_cached})"
            )

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

        content = _read_file_content(filepath, configured_max_file_size_kb)
        if content is None:
            return [], []

        try:
            entities, rels = extractor.parse_file(filepath, content)
        except Exception as exc:
            self.logger.warning("index_file_failed", filepath=filepath, error=str(exc))
            return [], []

        content_hash = hashlib.sha256(content).hexdigest()
        try:
            mtime = Path(filepath).stat().st_mtime
            self._cache.update(filepath, mtime, content_hash)
            self._cache.save()
        except OSError:
            pass

        return entities, rels

    def invalidate(self, filepath: str) -> None:
        """Force re-parse of filepath on the next build_graph call."""
        self._cache.invalidate(filepath)
        try:
            self._cache.save()
        except Exception:
            pass

    def stats(self) -> dict[str, int]:
        """Return cache statistics."""
        return {"cached_files": len(self._cache._data)}

    # ------------------------------------------------------------------
    # Internal — cross-file import resolution
    # ------------------------------------------------------------------

    def _resolve_imports(self, graph: InMemoryGraph) -> InMemoryGraph:
        """
        Resolve "unresolved:X" relationship targets across the full graph.

        Builds a name → entity_id index and replaces unresolved targets with
        real entity IDs where possible. Stores unresolvable imports as plain
        module name strings for visualization purposes.
        """
        # Build name lookup: entity name → entity ID
        name_to_id: dict[str, str] = {}
        for ent in graph.entities.values():
            name_to_id[ent.name] = ent.id
            if "." in ent.name:
                name_to_id[ent.name.split(".")[-1]] = ent.id
            if ent.type == EntityType.MODULE:
                stem = Path(ent.file).stem
                name_to_id[stem] = ent.id

        unresolved = [r for r in graph.relationships if r.target_id.startswith("unresolved:")]
        resolved = []

        for rel in unresolved:
            ref_text = rel.target_id[11:]  # strip "unresolved:"
            target_id = name_to_id.get(ref_text)

            if not target_id and "/" in ref_text:
                target_id = name_to_id.get(ref_text.split("/")[-1])
            if not target_id and "." in ref_text:
                target_id = name_to_id.get(ref_text.split(".")[-1])

            resolved.append(
                Relationship(
                    source_id=rel.source_id,
                    target_id=target_id if target_id else ref_text,
                    type=rel.type,
                    metadata=rel.metadata,
                )
            )

        # Rebuild relationships: drop unresolved stubs, add resolved ones
        clean_rels = [r for r in graph.relationships if not r.target_id.startswith("unresolved:")]
        clean_rels.extend(resolved)
        graph.relationships = clean_rels

        self.logger.info(
            "import_resolution_complete",
            unresolved_count=len(unresolved),
            resolved_count=sum(
                1 for r in resolved if "." not in r.target_id and "/" not in r.target_id
            ),
        )
        return graph
