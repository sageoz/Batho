"""
batho/context/bsg_map/__init__.py — Flat Symbol Index (BSGMap).
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from batho.core.config import SCHEMA_VERSIONS
from batho.utils.hash import generate_relationship_id
from batho.utils.logging import get_logger

BSG_SCHEMA_VERSION = SCHEMA_VERSIONS["bsg"]

from batho.core.schemas import BSGViewType, Entity, EntityType, FileSnapshot, IntegrityError
from .relativizer import PathRelativizer
from .constants import EXT_TO_LANGUAGE_DISPLAY, EXT_TO_LANGUAGE_ID

if TYPE_CHECKING:
    from batho.modules.storage.cache.unified_cache import BathoCache
    from batho.modules.graph.builder.codegraph import InMemoryGraph


def _get_file_change_type() -> type:
    """Lazy import of FileChangeType to avoid circular imports at module load."""
    from batho.orchestrator.patch import FileChangeType  # noqa: PLC0415
    return FileChangeType


@dataclass
class BSGMap:
    """
    Flat symbol index built from an InMemoryGraph.
    """

    _root: str = field(default="", repr=False)
    _by_file: dict[str, list[Entity]] = field(default_factory=dict, repr=False)
    _dependencies: dict[str, list[str]] = field(default_factory=dict, repr=False)
    _relationships: list[Any] = field(default_factory=list, repr=False)
    _serialized_bsg: dict[str, Any] | None = field(default=None, repr=False)
    _serialization_config: dict[str, Any] = field(default_factory=dict, repr=False)
    _file_snapshots: dict[str, "FileSnapshot"] = field(default_factory=dict, repr=False)
    _opaque_snapshots: dict[str, "FileSnapshot"] = field(default_factory=dict, repr=False)
    _view_config: dict[str, Any] = field(default_factory=dict, repr=False)
    _view_cache_dirty: bool = field(default=True, repr=False)
    _logger: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._logger = get_logger(__name__, operation="bsg")

    def patch(
        self,
        changes: list[Any],
        graph: "InMemoryGraph",
        cache: "BathoCache | None" = None,
    ) -> None:
        """
        Incrementally update the BSGMap for changed files only.
        """
        from batho.modules.graph.builder.codegraph import InMemoryGraph

        assert isinstance(graph, InMemoryGraph)

        _rel = PathRelativizer(self._root)

        changed_rel_paths: set[str] = set()
        for change in changes:
            rel = _rel(str(change.path))
            changed_rel_paths.add(rel)

        for rel in changed_rel_paths:
            self._by_file.pop(rel, None)
            self._dependencies.pop(rel, None)

        new_by_file: dict[str, list] = {}
        for entity in graph.entities.values():
            rel = _rel(entity.file)
            if rel in changed_rel_paths:
                new_by_file.setdefault(rel, []).append(entity)

        for rel, entities in new_by_file.items():
            self._by_file[rel] = sorted(entities, key=lambda e: e.start_line)

        # NOTE: This iterates over ALL relationships for each patch operation.
        # For large graphs with 100k+ relationships, this is O(n) per patch.
        # Consider indexing relationships by source file for O(1) lookup.
        # See: https://github.com/batho/batho/issues/performance-123
        new_deps: dict[str, set[str]] = {}
        for rel in graph.relationships:
            if rel.type.name not in ("IMPORTS", "CALLS", "USES"):
                continue
            source_ent = graph.get_entity(rel.source_id)
            if source_ent is None:
                continue
            source_rel = _rel(source_ent.file)
            if source_rel not in changed_rel_paths:
                continue
            target_ent = graph.get_entity(rel.target_id)
            raw_target = target_ent.file if target_ent else rel.target_id
            target_rel = (
                _rel(raw_target) if raw_target.startswith("/") else raw_target
            )
            if source_rel != target_rel:
                new_deps.setdefault(source_rel, set()).add(target_rel)

        for rel_path, deps in new_deps.items():
            self._dependencies[rel_path] = sorted(deps)

        # PRE-CONDITION: `graph` must be the FULL merged InMemoryGraph (all files),
        # not a per-file subgraph.  _by_file and _dependencies are updated
        # incrementally (only changed files), but _relationships is replaced
        # wholesale with all relationships from graph.  Passing a partial graph
        # here would silently drop relationships from unchanged files.
        self._relationships = list(graph.relationships)
        self._serialized_bsg = None

        # Update _opaque_snapshots
        FileChangeType = _get_file_change_type()
        local_cache: BathoCache | None = None
        cache_created = False
        try:
            # Create local cache once if needed, outside the loop
            if cache is None:
                from batho.modules.storage.cache.unified_cache import BathoCache as BC
                local_cache = BC(self._root)
                cache_created = True
                c = local_cache
            else:
                c = cache

            for change in changes:
                change_rel = _rel(change.path)
                if change.change_type == FileChangeType.DELETED:
                    self._opaque_snapshots.pop(change_rel, None)
                elif change.change_type in (FileChangeType.ADDED, FileChangeType.MODIFIED):
                    has_entities = False
                    for entity in graph.entities.values():
                        entity_rel = _rel(entity.file)
                        if entity_rel == change_rel:
                            has_entities = True
                            break
                    if not has_entities:
                        try:
                            abs_path = change.path
                            if not Path(abs_path).is_absolute():
                                abs_path = str(Path(self._root) / change.path)
                            snap = c.get_file_snapshot(abs_path) or c.get_file_snapshot(change_rel)
                            if snap is not None:
                                self._opaque_snapshots[change_rel] = snap
                        except Exception as e:
                            self._logger.warning("patch_opaque_snapshot_load_failed", filepath=change.path, error=str(e))
                    else:
                        self._opaque_snapshots.pop(change_rel, None)
        finally:
            if local_cache is not None and cache_created:
                local_cache.close()

        self._logger.debug(
            "bsg_incrementally_patched",
            change_count=len(changes),
            changed_files=sorted(changed_rel_paths),
            total_files=len(self._by_file),
            entity_count=sum(len(v) for v in self._by_file.values()),
        )

    @classmethod
    def build(
        cls,
        graph: "object",
        root: str,
        serialization_config: dict[str, Any] | None = None,
        opaque_snapshots: "list[FileSnapshot] | None" = None,
    ) -> "BSGMap":
        """
        Build a BSGMap from an InMemoryGraph.
        """
        from batho.modules.graph.builder.codegraph import InMemoryGraph

        assert isinstance(graph, InMemoryGraph)

        _rel = PathRelativizer(root)

        by_file: dict[str, list[Entity]] = defaultdict(list)
        for entity in graph.entities.values():
            by_file[_rel(entity.file)].append(entity)

        dependencies: dict[str, set[str]] = defaultdict(set)
        for rel in graph.relationships:
            if rel.type.name in ("IMPORTS", "CALLS", "USES"):
                source_ent = graph.get_entity(rel.source_id)
                target_ent = graph.get_entity(rel.target_id)

                if source_ent:
                    source_file = _rel(source_ent.file)
                    raw_target = target_ent.file if target_ent else rel.target_id
                    target_file = (
                        _rel(raw_target) if raw_target.startswith("/") else raw_target
                    )
                    if source_file != target_file:
                        dependencies[source_file].add(target_file)

        sorted_map: dict[str, list[Entity]] = {
            path: sorted(entities, key=lambda e: e.start_line)
            for path, entities in sorted(by_file.items())
        }
        sorted_deps: dict[str, list[str]] = {
            path: sorted(list(deps)) for path, deps in dependencies.items()
        }

        opaque_map: dict[str, "FileSnapshot"] = (
            {_rel(snap.file_path): snap for snap in opaque_snapshots}
            if opaque_snapshots
            else {}
        )

        instance = cls(
            _root=str(_rel.root_path()),
            _by_file=sorted_map,
            _dependencies=sorted_deps,
            _relationships=list(graph.relationships),
            _serialization_config=serialization_config or {},
            _opaque_snapshots=opaque_map,
        )
        instance._logger.debug(
            "bsg_built",
            root=str(_rel.root_path()),
            file_count=len(sorted_map),
            opaque_file_count=len(opaque_map),
            entity_count=sum(len(v) for v in sorted_map.values()),
        )
        return instance

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], serialization_config: dict[str, Any] | None = None
    ) -> "BSGMap":
        """
        Reconstruct a BSGMap from serialized data.
        """
        if not isinstance(data, dict):
            raise TypeError("BSGMap.from_dict requires a dictionary input")

        by_file: dict[str, list[Entity]] = {}
        dependencies: dict[str, list[str]] = {}
        serialized_bsg: dict[str, Any] | None = None
        root_value = str(data.get("root", ""))

        if isinstance(data.get("nodes"), list):
            for node_data in data.get("nodes", []):
                if not isinstance(node_data, dict):
                    continue
                file_path = str(node_data.get("file", ""))
                if not file_path:
                    continue

                entity = Entity.from_dict(node_data)
                by_file.setdefault(file_path, []).append(entity)

            for entities in by_file.values():
                entities.sort(key=lambda e: e.start_line)

            serialized_bsg = data
        else:
            for file_path, entities_data in data.items():
                if not isinstance(entities_data, list):
                    continue
                entities = [
                    Entity(
                        type=EntityType.VARIABLE,
                        name=str(e.get("name", "")),
                        file=file_path,
                        start_line=int(e.get("start_line", 0) or 0),
                        end_line=int(e.get("end_line", 0) or 0),
                        signature=e.get("signature"),
                        metadata=dict(e.get("metadata", {}) or {}),
                    )
                    for e in entities_data
                    if isinstance(e, dict)
                ]
                by_file[file_path] = entities

        opaque_map = {}
        if isinstance(data.get("opaque_files"), list):
            from batho.core.schemas import FileSnapshot
            _rel = PathRelativizer(root_value)
            for item in data.get("opaque_files", []):
                if isinstance(item, dict) and "file_path" in item:
                    snap = FileSnapshot(
                        file_path=item["file_path"],
                        file_hash=item.get("file_hash", ""),
                        file_size=item.get("file_size", 0),
                        encoding=item.get("encoding", "utf-8"),
                    )
                    fp_rel = _rel(item["file_path"]) if Path(item["file_path"]).is_absolute() else item["file_path"]
                    opaque_map[fp_rel] = snap

        return cls(
            _root=root_value,
            _by_file=by_file,
            _dependencies=dependencies,
            _relationships=[],
            _serialized_bsg=serialized_bsg,
            _serialization_config=serialization_config or {},
            _opaque_snapshots=opaque_map,
        )

    def render_full(self) -> str:
        from .render_bsg import render_full as _render
        return _render(self)

    def render_hierarchical(self, include_entities: bool = True) -> str:
        from .render_bsg import render_hierarchical as _render
        return _render(self, include_entities=include_entities)

    def render_compressed(self, budget: int, fail_on_overflow: bool = True) -> tuple[str, dict[str, int]]:
        from .render_agent import render_compressed as _render
        return _render(self, budget, fail_on_overflow=fail_on_overflow)

    def render_json(self, **kwargs: Any) -> dict[str, Any]:
        from .render_storage import render_json as _render
        return _render(self, **kwargs)

    def render_overview_json(self, **kwargs: Any) -> dict[str, Any]:
        from .render_storage import render_overview_json as _render
        return _render(self, **kwargs)

    def render_files_json(self, **kwargs: Any) -> dict[str, Any]:
        from .render_storage import render_files_json as _render
        return _render(self, **kwargs)

    def to_dict(self, **kwargs: Any) -> dict[str, Any]:
        from .render_storage import to_dict as _render
        return _render(self, **kwargs)

    def render_json_streaming(self, **kwargs: Any) -> Any:
        from .render_storage import render_json_streaming as _render
        return _render(self, **kwargs)

    def categorize_files(self) -> dict[str, dict[str, list[Entity]]]:
        """
        Categorize all files by type (tests, docs, config, source, and folder-based).
        Uses bsg.category metadata set by BSG plugins.
        """
        categorized: dict[str, dict[str, list[Entity]]] = {}
        category_priority = {
            "TEST": 4,
            "CONFIG": 3,
            "DOC": 2,
            "INFRA": 2,
            "SOURCE": 1,
            "UNCATEGORIZED": 0,
        }

        for file_path, entities in self._by_file.items():
            if not entities:
                continue
            categories = set()
            for entity in entities:
                metadata = entity.metadata or {}
                cat = str(metadata.get("bsg.category", "SOURCE")).upper()
                categories.add(cat)
            category = "source"
            max_priority = -1
            for cat in categories:
                priority = category_priority.get(cat, 0)
                if priority > max_priority:
                    max_priority = priority
                    category = cat.lower()
            categorized.setdefault(category, {})[file_path] = entities
        return categorized

    def render_delta(
        self,
        previous: "BSGMap | None" = None,
        include_unchanged: bool = False,
    ) -> dict[str, Any]:
        """
        Render delta between this BSGMap and a previous one.
        
        Useful for incremental updates where only changes need to be transmitted.
        
        Args:
            previous: Previous BSGMap to compare against
            include_unchanged: If True, include unchanged files in output
            
        Returns:
            Delta representation with added, modified, and removed files
        """
        if previous is None:
            # No previous state - return full map as "added"
            return {
                "delta_type": "full",
                "added": dict(self._by_file),
                "modified": [],
                "removed": [],
                "unchanged": [],
            }
        
        current_files = set(self._by_file.keys())
        previous_files = set(previous._by_file.keys())
        
        added = current_files - previous_files
        removed = previous_files - current_files
        common = current_files & previous_files
        
        modified: list[str] = []
        unchanged: list[str] = []
        
        for f in common:
            curr_entities = self._by_file[f]
            prev_entities = previous._by_file[f]
            
            # Simple equality check - could be enhanced with entity hashing
            if curr_entities != prev_entities:
                modified.append(f)
            elif include_unchanged:
                unchanged.append(f)
        
        return {
            "delta_type": "incremental",
            "added": {f: self._by_file[f] for f in added},
            "modified": modified,
            "removed": list(removed),
            "unchanged": unchanged if include_unchanged else [],
            "stats": {
                "total_files": len(current_files),
                "added_count": len(added),
                "modified_count": len(modified),
                "removed_count": len(removed),
            }
        }

    # Internal helper methods for rendering
    def group_by_directory(self) -> dict[str, list[tuple[str, list[Entity]]]]:
        grouped = defaultdict(list)
        for rel_path, entities in self._by_file.items():
            path_obj = PurePosixPath(rel_path)
            dir_path = str(path_obj.parent)
            if dir_path == ".":
                dir_path = ""
            file_name = path_obj.name
            grouped[dir_path].append((file_name, entities))
        for dir_path in grouped:
            grouped[dir_path].sort(key=lambda x: x[0])
        return dict(sorted(grouped.items()))

    def _get_directory_label(self, dir_path: str) -> str:
        if not dir_path:
            return "Root"
        if "tests" in dir_path.lower():
            return "Tests"
        if "docs" in dir_path.lower():
            return "Documentation"
        return "Source Code"

    def _derive_scope_tier(self, entity: Entity) -> str:
        if entity.type in (EntityType.CLASS, EntityType.INTERFACE, EntityType.MODULE):
            return "public"
        return "internal"

    def _derive_category(self, file_path: str) -> str:
        if "test" in file_path.lower():
            return "TEST"
        if file_path.endswith((".yaml", ".yml", ".json", ".toml")):
            return "CONFIG"
        if "doc" in file_path.lower() or file_path.endswith(".md"):
            return "DOC"
        return "SOURCE"

    def _normalize_category(self, cat: str) -> str:
        c = cat.strip().upper()
        if c in ("TESTS", "TESTING"): return "TEST"
        if c in ("DOCS", "DOCUMENTATION"): return "DOC"
        if c == "INFRASTRUCTURE": return "INFRA"
        if c == "SRC": return "SOURCE"
        return c

    def _derive_language(self, entity: Entity, file_path: str) -> str:
        ext = Path(file_path).suffix.lower()
        return EXT_TO_LANGUAGE_ID.get(ext, "unknown")

    def _derive_service_tag(self, file_path: str) -> str | None:
        parts = Path(file_path).parts
        if len(parts) > 1:
            return parts[0]
        return None

    def _build_render_components(self, **kwargs: Any) -> dict[str, Any]:
        """Build reusable render components for JSON outputs."""
        from .render_storage import _build_render_components as _build
        return _build(self, **kwargs)

    def render_storage_view(self, file_paths: list[str] | None = None) -> dict[str, Any]:
        """Render a full-fidelity storage view suitable for file reconstruction."""
        target_paths = sorted(
            file_paths if file_paths is not None else list(self._by_file.keys())
        )

        files_data: list[dict[str, Any]] = []
        total_entities = 0
        total_snapshots = 0
        fully_covered_files = 0

        for file_path in target_paths:
            entities = self._by_file.get(file_path, [])
            if not entities:
                continue

            file_entities = sorted(entities, key=lambda e: e.start_byte)
            serialized_entities = [e.to_dict(view="storage") for e in file_entities]

            file_entry: dict[str, Any] = {
                "file_path": file_path,
                "entities": serialized_entities,
                "entity_count": len(file_entities),
            }

            snapshot = self._file_snapshots.get(file_path)
            if snapshot is not None:
                file_entry["snapshot"] = snapshot.model_dump()
                total_snapshots += 1
                if file_entities and snapshot.file_size:
                    from batho.modules.graph.reconstructor.reconstructor import FileReconstructor
                    if FileReconstructor._check_coverage(file_entities, snapshot.file_size):
                        fully_covered_files += 1

            files_data.append(file_entry)
            total_entities += len(file_entities)

        if total_snapshots > 0:
            coverage_pct = (fully_covered_files / total_snapshots) * 100
            byte_coverage = f"{coverage_pct:.0f}%"
        else:
            byte_coverage = "unknown"

        _rel = PathRelativizer(self._root)
        opaque_files_data = [
            {
                "file_path": _rel(snap.file_path),
                "file_hash": snap.file_hash,
                "file_size": snap.file_size,
                "encoding": snap.encoding,
            }
            for snap in sorted(self._opaque_snapshots.values(), key=lambda s: s.file_path)
        ]

        edges = []
        for rel in self._relationships:
            if hasattr(rel, "to_dict"):
                edges.append(rel.to_dict())
            else:
                edges.append(dict(rel))

        return {
            "view_type": str(BSGViewType.STORAGE),
            "schema_version": BSG_SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "includes_raw_content": True,
            "includes_syntax_glue": True,
            "entity_count": total_entities,
            "file_count": len(files_data),
            "snapshot_count": total_snapshots,
            "fully_covered_files": fully_covered_files,
            "byte_coverage": byte_coverage,
            "files": files_data,
            "relationships": edges,
            "opaque_files": opaque_files_data,
        }

    def render_agent_view(self, token_budget: int | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        """Render a compressed view optimised for LLM context injection."""
        from .render_agent import _text_tokens
        agent_cfg = self._get_agent_view_config()
        exclude_syntax_glue = agent_cfg.get("exclude_syntax_glue", True)
        max_docstring_chars = agent_cfg.get("max_docstring_chars", 200)

        tokens_used = 0
        truncated = False
        total_all_entities = 0
        total_agent_entities = 0
        files_data: list[dict[str, Any]] = []

        for file_path in sorted(self._by_file.keys()):
            entities = sorted(self._by_file[file_path], key=lambda e: e.start_byte)
            total_all_entities += len(entities)

            if exclude_syntax_glue:
                entities = [e for e in entities if e.type != EntityType.SYNTAX_GLUE]

            if not entities:
                continue

            if token_budget is not None and tokens_used >= token_budget:
                truncated = True
                break

            serialized: list[dict[str, Any]] = []
            for e in entities:
                ent_dict = e.to_dict(view="agent")
                if max_docstring_chars and "metadata" in ent_dict:
                    meta = ent_dict["metadata"]
                    for key in ("docstring", "comment", "docs"):
                        val = meta.get(key)
                        if isinstance(val, str) and len(val) > max_docstring_chars:
                            meta[key] = val[:max_docstring_chars] + "..."

                if token_budget is not None:
                    entry_text = json.dumps(ent_dict, sort_keys=True)
                    cost = _text_tokens(entry_text)
                    if tokens_used + cost > token_budget:
                        truncated = True
                        break
                    tokens_used += cost

                serialized.append(ent_dict)

            if serialized:
                files_data.append({
                    "file_path": file_path,
                    "entities": serialized,
                    "entity_count": len(serialized),
                })
                total_agent_entities += len(serialized)

            if truncated:
                break

        compression_ratio = (
            round(total_agent_entities / total_all_entities, 4)
            if total_all_entities > 0
            else 1.0
        )

        view_dict = {
            "view_type": str(BSGViewType.AGENT),
            "schema_version": BSG_SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "includes_raw_content": False,
            "includes_syntax_glue": not exclude_syntax_glue,
            "entity_count": total_agent_entities,
            "file_count": len(files_data),
            "compression_ratio": compression_ratio,
            "files": files_data,
        }

        stats = {
            "token_budget": token_budget,
            "tokens_used": tokens_used,
            "compression_ratio": compression_ratio,
            "truncated": truncated,
        }

        return view_dict, stats

    def reconstruct_file(self, file_path: str, original_hash: str | None = None) -> Any:
        """Reconstruct a file from its BSG entities using FileReconstructor."""
        from batho.modules.graph.reconstructor.reconstructor import FileReconstructor

        entities = self._by_file.get(file_path, [])
        if not entities:
            raise ValueError(f"No entities found for file: {file_path}")

        resolved_hash = original_hash
        if resolved_hash is None:
            snapshot = self._file_snapshots.get(file_path)
            if snapshot is not None and snapshot.file_hash:
                resolved_hash = snapshot.file_hash

        reconstructor = FileReconstructor()
        return reconstructor.reconstruct_file(
            file_path=file_path,
            entities=entities,
            original_hash=resolved_hash,
        )

    def verify_file_integrity(self, file_path: str) -> dict[str, Any]:
        """Verify that entities for a file can faithfully reproduce the original."""
        from batho.modules.graph.reconstructor.reconstructor import FileReconstructor

        snapshot = self._file_snapshots.get(file_path)
        if snapshot is None:
            return {
                "verified": False,
                "file_path": file_path,
                "hash_match": False,
                "errors": ["No snapshot available for integrity verification"],
            }

        entities = self._by_file.get(file_path, [])
        if not entities:
            return {
                "verified": False,
                "file_path": file_path,
                "hash_match": False,
                "errors": ["No entities found for file"],
            }

        reconstructor = FileReconstructor()
        try:
            result = reconstructor.reconstruct_file(
                file_path=file_path,
                entities=entities,
                original_hash=snapshot.file_hash or None,
            )
            return {
                "verified": result.hash_match,
                "hash_match": result.hash_match,
                "byte_coverage": result.byte_coverage,
                "reconstructed_hash": result.reconstructed_hash,
                "original_hash": result.original_hash,
                "entity_count": result.entity_count,
                "errors": result.errors,
                "warnings": result.warnings,
            }
        except IntegrityError as exc:
            return {
                "verified": False,
                "file_path": file_path,
                "hash_match": False,
                "expected_hash": exc.expected_hash,
                "actual_hash": exc.actual_hash,
                "errors": [str(exc)],
            }
        except Exception as exc:
            return {
                "verified": False,
                "file_path": file_path,
                "hash_match": False,
                "errors": [str(exc)],
            }

    def estimate_tokens(self) -> int:
        """Estimate the token count of the full render_full() output."""
        if not self._by_file:
            return 0
        text = self.render_full()
        return max(1, len(text.encode("utf-8")) // 4)

    @property
    def entity_count(self) -> int:
        """Return the total number of entities across all files."""
        return sum(len(entities) for entities in self._by_file.values())

    def render_overview(
        self,
        stack_info: dict[str, Any] | None = None,
        repo_name: str | None = None,
        timestamp: str | None = None,
        evolution_rules: list[dict[str, Any]] | None = None,
    ) -> str:
        """Render a markdown overview of the repository."""
        lines: list[str] = []

        # Header
        if repo_name:
            lines.append(f"# {repo_name} Context Overview")
        else:
            lines.append("# Repository Context Overview")

        if timestamp:
            lines.append(f"\n*Generated: {timestamp}*")

        # Summary stats
        total_files = len(self._by_file)
        total_entities = sum(len(entities) for entities in self._by_file.values())

        lines.append(f"\n## Summary")
        lines.append(f"- **Files indexed:** {total_files}")
        lines.append(f"- **Total entities:** {total_entities}")

        # Stack info
        if stack_info:
            lines.append(f"\n## Stack")
            for key, value in stack_info.items():
                lines.append(f"- **{key}:** {value}")

        # Evolution rules / Ledger Insights
        if evolution_rules:
            # Check if these are evolution ledger entries (have dont_rule)
            ledger_entries = [r for r in evolution_rules if r.get("dont_rule")]
            if ledger_entries:
                lines.append(f"\n## Evolution Ledger Insights")
                for entry in ledger_entries[:5]:
                    dont_rule = entry.get("dont_rule", "")
                    if dont_rule:
                        lines.append(f"- {dont_rule}")
            else:
                lines.append(f"\n## Recent Evolution")
                for rule in evolution_rules[:5]:
                    rule_name = rule.get("name", "unknown")
                    lines.append(f"- {rule_name}")

        # File breakdown
        categorized = self.categorize_files()
        if categorized:
            lines.append(f"\n## File Breakdown")
            for category, files in categorized.items():
                lines.append(f"- **{category}:** {len(files)} files")

        return "\n".join(lines)

    def render_files_md(
        self,
        repo_name: str | None = None,
        timestamp: str | None = None,
    ) -> str:
        """Render a markdown list of all files organized by category."""
        lines: list[str] = []

        # Header
        if repo_name:
            lines.append(f"# {repo_name} Files")
        else:
            lines.append("# Repository Files")

        if timestamp:
            lines.append(f"\n*Generated: {timestamp}*")

        # Categorize files
        categorized = self.categorize_files()

        if not categorized:
            lines.append("\n*No files indexed*")
            return "\n".join(lines)

        # Render each category
        for category in ("SOURCE", "TEST", "DOC", "CONFIG"):
            files = categorized.get(category, {})
            if not files:
                continue

            lines.append(f"\n## {category}")
            for file_path in sorted(files.keys()):
                entities = files[file_path]
                entity_count = len(entities)
                lines.append(f"- `{file_path}` ({entity_count} entities)")

        return "\n".join(lines)

    def _get_agent_view_config(self) -> dict[str, Any]:
        return self._view_config.get("agent", {})

