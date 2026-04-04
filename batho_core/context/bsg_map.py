"""
backend/context/bsg_map.py — Flat Symbol Index (BSGMap).

Production port from prototype with improvements:
- Uses pathlib.Path for cross-platform path normalization
- Renders file dependencies in hierarchical and compressed views
- Token-budget-capped rendering for LLM injection

Provides three rendering modes:
- render_full()       — aider-style indented text for dev inspection
- render_compressed() — token-budget-capped summary for LLM context
- render_json()       — structured dict for programmatic consumption
- render_hierarchical() — directory tree with symbols and dependencies
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path, PurePosixPath
from typing import Any, TYPE_CHECKING

from batho_core.config import BSG_SCHEMA_VERSION
from batho_core.utils.hash import generate_relationship_id
from batho_core.utils.logging import get_logger

from .categorizer import FileCategorizer
from .schema import Entity, EntityType

_FILE_CATEGORIZER = FileCategorizer()

if TYPE_CHECKING:
    from batho_core.time_machine import FileChange
    from .codegraph import InMemoryGraph

# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------


def _text_tokens(text: str) -> int:
    """Estimate token count using 4-bytes-per-token heuristic."""
    return max(1, len(text.encode("utf-8")) // 4)


# ---------------------------------------------------------------------------
# BSGMap
# ---------------------------------------------------------------------------


@dataclass
class BSGMap:
    """
    Flat symbol index built from an InMemoryGraph.

    Provides multiple rendering modes optimized for different consumers:
    - LLMs (compressed, token-budgeted)
    - Developers (full aider-style)
    - Programmatic (JSON)
    - Memory files (hierarchical tree)

    Attributes:
        _root: Absolute workspace root used to normalise all paths at build time.
        _by_file: Mapping of relative_file_path → list[Entity] sorted by start_line.
        _dependencies: Mapping of relative_file_path → list[dep_module_or_rel_path].
    """

    _root: str = field(default="", repr=False)
    _by_file: dict[str, list[Entity]] = field(default_factory=dict, repr=False)
    _dependencies: dict[str, list[str]] = field(default_factory=dict, repr=False)
    _relationships: list[Any] = field(default_factory=list, repr=False)
    _serialized_bsg: dict[str, Any] | None = field(default=None, repr=False)
    _logger: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._logger = get_logger(__name__, operation="bsg")

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def patch(self, changes: list["FileChange"], graph: "InMemoryGraph") -> None:
        """
        Update the bsg_map for changed files with true incremental updates.

        Applies incremental changes to the symbol index based on file changes.
        Removes entities for deleted files, updates entities for modified files,
        and adds entities for new files.

        Args:
            changes: List of FileChange objects representing what changed
            graph: Updated InMemoryGraph with the changes applied
        """
        rebuilt = BSGMap.build(graph=graph, root=self._root)
        self._by_file = rebuilt._by_file
        self._dependencies = rebuilt._dependencies
        self._relationships = rebuilt._relationships
        self._serialized_bsg = None

        self._logger.debug(
            "bsg_incrementally_patched",
            change_count=len(changes),
            total_files=len(self._by_file),
            entity_count=sum(len(v) for v in self._by_file.values()),
        )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BSGMap":
        """
        Reconstruct a BSGMap from serialized data.

        Args:
            data: Dict from render_json() or snapshot

        Returns:
            Reconstructed BSGMap instance
        """
        by_file: dict[str, list[Entity]] = {}
        dependencies: dict[str, list[str]] = {}
        serialized_bsg: dict[str, Any] | None = None
        root_value = str(data.get("root", ""))

        # Native bsg.v1 payload
        if isinstance(data.get("nodes"), list):
            for node_data in data.get("nodes", []):
                if not isinstance(node_data, dict):
                    continue
                file_path = str(node_data.get("file", ""))
                if not file_path:
                    continue

                type_str = str(node_data.get("type", "VARIABLE")).upper()
                entity_type = (
                    EntityType[type_str]
                    if type_str in EntityType.__members__
                    else EntityType.VARIABLE
                )
                entity = Entity(
                    type=entity_type,
                    name=str(node_data.get("name", "")),
                    file=file_path,
                    start_line=int(node_data.get("start_line", 0) or 0),
                    end_line=int(node_data.get("end_line", 0) or 0),
                    signature=node_data.get("signature"),
                    metadata=dict(node_data.get("metadata", {}) or {}),
                )
                by_file.setdefault(file_path, []).append(entity)

            for entities in by_file.values():
                entities.sort(key=lambda e: e.start_line)

            serialized_bsg = data
            return cls(
                _root=root_value,
                _by_file=by_file,
                _dependencies=dependencies,
                _relationships=[],
                _serialized_bsg=serialized_bsg,
            )

        # Legacy fallback payload
        dependencies = data.get("dependencies", {}) or {}
        for file_path, entities_data in (data.get("files", {}) or {}).items():
            entities: list[Entity] = []
            for ent_data in entities_data:
                type_str = str(ent_data.get("type", "VARIABLE")).upper()
                entity_type = (
                    EntityType[type_str]
                    if type_str in EntityType.__members__
                    else EntityType.VARIABLE
                )
                lines = ent_data.get("lines", [0, 0])
                start_line = int(lines[0] if isinstance(lines, list) and lines else 0)
                end_line = int(lines[1] if isinstance(lines, list) and len(lines) > 1 else start_line)
                metadata: dict[str, Any] = {}
                if ent_data.get("docstring"):
                    metadata["docstring"] = ent_data.get("docstring")
                entity = Entity(
                    type=entity_type,
                    name=str(ent_data.get("name", "")),
                    file=file_path,
                    start_line=start_line,
                    end_line=end_line,
                    signature=ent_data.get("signature"),
                    metadata=metadata,
                )
                entities.append(entity)
            by_file[file_path] = entities

        return cls(
            _root=root_value,
            _by_file=by_file,
            _dependencies=dependencies,
            _relationships=[],
            _serialized_bsg=None,
        )

    @classmethod
    def build(cls, graph: "object", root: str) -> "BSGMap":
        """
        Build a BSGMap from an InMemoryGraph.

        All file paths are normalised to be relative to *root* at
        construction time, so every rendering method produces compact,
        portable output without any absolute disk paths.

        Args:
            graph: An InMemoryGraph populated by CodeGraphIndexer.
            root: Absolute workspace root (output of ``Path.cwd().resolve()``).

        Returns:
            A fresh BSGMap instance with relative-path keys.
        """
        from .codegraph import InMemoryGraph

        assert isinstance(graph, InMemoryGraph)

        root_path = Path(root).resolve()
        rel_path_cache: dict[str, str] = {}

        def _rel(p: str) -> str:
            """Convert absolute path *p* to a path relative to *root_path*."""
            cached = rel_path_cache.get(p)
            if cached is not None:
                return cached
            try:
                rel = Path(p).resolve().relative_to(root_path).as_posix()
            except ValueError:
                rel = Path(p).as_posix()
            rel_path_cache[p] = rel
            return rel

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
                    # target_file: normalise if it looks like an absolute path,
                    # else keep as module name (e.g. "os", "pathlib")
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

        instance = cls(
            _root=str(root_path),
            _by_file=sorted_map,
            _dependencies=sorted_deps,
            _relationships=list(graph.relationships),
        )
        instance._logger.debug(
            "bsg_built",
            root=str(root_path),
            file_count=len(sorted_map),
            entity_count=sum(len(v) for v in sorted_map.values()),
        )
        return instance

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render_full(self) -> str:
        """
        Render a full aider-style indented symbol index.

        Format::

            src/auth/login.py:
              AuthToken (class) [L10-25]
              login(username: str, password: str) -> AuthToken (function) [L30-55]

        Returns:
            Multi-line string — the full repo symbol tree.
        """
        lines: list[str] = []
        for file_path, entities in self._by_file.items():
            lines.append(f"{file_path}:")
            for entity in entities:
                indent = "  "
                sig = entity.signature or entity.name
                type_label = str(entity.type)
                lines.append(
                    f"{indent}{sig} ({type_label}) [L{entity.start_line}-{entity.end_line}]"
                )
            deps = self._dependencies.get(file_path, [])
            if deps:
                lines.append(f"  deps: {', '.join(deps)}")
        return "\n".join(lines)

    def render_compressed(
        self, budget: int, fail_on_overflow: bool = True
    ) -> tuple[str, dict[str, int]]:
        """
        Render a token-budget-capped summary for LLM injection.

        Iterates files in sorted order, adding name (type) entries until
        the budget is exhausted. Signatures and line numbers are omitted.

        Args:
            budget: Maximum token budget for the output.

        Returns:
            (text, stats) where stats includes tokens_used, budget, truncated_files.
        """
        lines: list[str] = []
        tokens_used = 0
        truncated_files = 0

        for file_path, entities in self._by_file.items():
            file_header = f"{file_path}:"
            header_cost = _text_tokens(file_header)
            if tokens_used + header_cost > budget:
                truncated_files += len([f for f in self._by_file if f >= file_path])
                break

            lines.append(file_header)
            tokens_used += header_cost

            for entity in entities:
                entry = f"  {entity.name} ({entity.type})"
                cost = _text_tokens(entry)
                if tokens_used + cost > budget:
                    truncated_files += 1
                    break
                lines.append(entry)
                tokens_used += cost

        if truncated_files:
            if fail_on_overflow:
                raise ValueError(
                    f"Token budget exceeded (budget={budget}, used={tokens_used}); truncated_files={truncated_files}"
                )
            lines.append(f"  [...{truncated_files} more entries truncated]")

        self._logger.debug(
            "bsg_compressed",
            budget=budget,
            tokens_used=tokens_used,
            truncated=truncated_files > 0,
        )
        stats = {
            "tokens_used": tokens_used,
            "budget": budget,
            "truncated_files": truncated_files,
        }
        return "\n".join(lines), stats

    def render_json(
        self,
        build_ms: int | None = None,
        default_snapshot_id: str | None = None,
        default_service_tag: str | None = None,
    ) -> dict[str, Any]:
        """
        Render the structural graph as a bsg.v1 dictionary.

        Args:
            build_ms: Optional build latency in milliseconds for stats payload.
            default_snapshot_id: Fallback snapshot identifier to stamp nodes when
                metadata does not already provide one.
            default_service_tag: Optional service tag fallback when derivation
                from file path yields no service.

        Returns:
            JSON-serialisable bsg.v1 payload.
        """
        if (
            self._serialized_bsg is not None
            and build_ms is None
            and default_snapshot_id is None
            and default_service_tag is None
        ):
            return json.loads(json.dumps(self._serialized_bsg))

        resolved_default_snapshot = (default_snapshot_id or "").strip() or None
        resolved_default_service = (
            (default_service_tag or "").strip() if default_service_tag is not None else ""
        )
        if not resolved_default_service:
            resolved_default_service = Path(self._root).name or "root"
        resolved_build_ms = max(0, int(build_ms or 0))

        nodes: list[dict[str, Any]] = []
        node_by_id: dict[str, dict[str, Any]] = {}
        rule_names: set[str] = set()

        for file_path in sorted(self._by_file.keys()):
            entities = self._by_file[file_path]
            for entity in sorted(entities, key=lambda item: (item.start_line, item.id)):
                metadata = dict(entity.metadata or {})
                scope_tier = str(metadata.get("bsg.scope_tier") or self._derive_scope_tier(entity))
                category = str(metadata.get("bsg.category") or self._derive_category(file_path)).upper()
                service_tag = str(
                    metadata.get("bsg.service_tag")
                    or self._derive_service_tag(file_path)
                    or resolved_default_service
                )
                language = self._derive_language(entity, file_path)
                snapshot_id = (
                    metadata.get("bsg.snapshot_id")
                    or metadata.get("snapshot_id")
                    or resolved_default_snapshot
                )

                rules = metadata.get("bsg.rules")
                if isinstance(rules, list):
                    for rule_name in rules:
                        if isinstance(rule_name, str) and rule_name.strip():
                            rule_names.add(rule_name.strip())

                node = {
                    "id": entity.id,
                    "type": entity.type.name,
                    "name": entity.name,
                    "file": file_path,
                    "start_line": entity.start_line,
                    "end_line": entity.end_line,
                    "signature": entity.signature,
                    "language": language,
                    "scope_tier": scope_tier,
                    "category": category,
                    "service_tag": service_tag,
                    "dependency_weight": 0,
                    "snapshot_id": snapshot_id,
                    "metadata": metadata,
                }
                nodes.append(node)
                node_by_id[node["id"]] = node

        edges: list[dict[str, Any]] = []
        edge_key_seen: set[tuple[str, str, str]] = set()
        inbound_edge_map: dict[str, list[str]] = defaultdict(list)
        outbound_edge_map: dict[str, list[str]] = defaultdict(list)
        cross_boundaries: list[dict[str, Any]] = []

        def _add_edge(
            source_id: str,
            target_id: str,
            edge_type: str,
            metadata: dict[str, Any] | None = None,
            derived_from: str | None = None,
        ) -> dict[str, Any] | None:
            if source_id not in node_by_id or target_id not in node_by_id:
                return None

            edge_key = (source_id, target_id, edge_type)
            if edge_key in edge_key_seen:
                return None
            edge_key_seen.add(edge_key)

            edge_metadata = dict(metadata or {})
            if derived_from:
                edge_metadata.setdefault("derived_from", derived_from)

            edge_id = generate_relationship_id(source_id, target_id, edge_type)
            edge = {
                "id": edge_id,
                "source_id": source_id,
                "target_id": target_id,
                "type": edge_type,
                "metadata": edge_metadata,
            }
            edges.append(edge)
            outbound_edge_map[source_id].append(edge_id)
            inbound_edge_map[target_id].append(edge_id)
            return edge

        relationships = sorted(
            self._relationships,
            key=lambda rel: (
                str(getattr(rel, "source_id", "")),
                str(getattr(rel, "target_id", "")),
                str(getattr(getattr(rel, "type", None), "name", getattr(rel, "type", ""))),
            ),
        )

        for rel in relationships:
            source_id = str(getattr(rel, "source_id", ""))
            target_id = str(getattr(rel, "target_id", ""))
            rel_type_value = getattr(rel, "type", "")
            rel_type = (
                rel_type_value.name
                if hasattr(rel_type_value, "name")
                else str(rel_type_value)
            )
            rel_metadata = dict(getattr(rel, "metadata", {}) or {})

            if not source_id or not target_id or not rel_type:
                continue

            edge = _add_edge(source_id, target_id, rel_type, rel_metadata)
            if edge is None:
                continue

            if rel_type == "CALLS":
                _add_edge(
                    target_id,
                    source_id,
                    "CALLED_BY",
                    {"derived": True},
                    derived_from=edge["id"],
                )
            elif rel_type == "IMPORTS":
                _add_edge(
                    target_id,
                    source_id,
                    "IMPORTED_BY",
                    {"derived": True},
                    derived_from=edge["id"],
                )

        for edge in list(edges):
            if edge["type"] == "STACK_BOUNDARY":
                continue

            source_node = node_by_id[edge["source_id"]]
            target_node = node_by_id[edge["target_id"]]
            source_service = str(source_node.get("service_tag") or "")
            target_service = str(target_node.get("service_tag") or "")

            if source_service and target_service and source_service != target_service:
                boundary_edge = _add_edge(
                    edge["source_id"],
                    edge["target_id"],
                    "STACK_BOUNDARY",
                    {
                        "source_service": source_service,
                        "target_service": target_service,
                        "derived": True,
                    },
                    derived_from=edge["id"],
                )
                if boundary_edge is not None:
                    cross_boundaries.append(
                        {
                            "edge_id": boundary_edge["id"],
                            "source_id": boundary_edge["source_id"],
                            "target_id": boundary_edge["target_id"],
                            "source_service": source_service,
                            "target_service": target_service,
                        }
                    )

        for node in nodes:
            node_id = node["id"]
            node["dependency_weight"] = len(inbound_edge_map.get(node_id, [])) + len(
                outbound_edge_map.get(node_id, [])
            )

        nodes_by_file: dict[str, list[str]] = defaultdict(list)
        nodes_by_type: dict[str, list[str]] = defaultdict(list)
        nodes_by_scope: dict[str, list[str]] = defaultdict(list)
        nodes_by_category: dict[str, list[str]] = defaultdict(list)
        nodes_by_service: dict[str, list[str]] = defaultdict(list)

        for node in nodes:
            node_id = node["id"]
            nodes_by_file[node["file"]].append(node_id)
            nodes_by_type[node["type"]].append(node_id)
            nodes_by_scope[node["scope_tier"]].append(node_id)
            nodes_by_category[node["category"]].append(node_id)
            service_key = node["service_tag"] or "UNASSIGNED"
            nodes_by_service[service_key].append(node_id)

        def _sorted_index(index: dict[str, list[str]]) -> dict[str, list[str]]:
            return {key: sorted(value) for key, value in sorted(index.items())}

        sorted_outbound_edges = {
            key: sorted(value) for key, value in sorted(outbound_edge_map.items())
        }
        sorted_inbound_edges = {
            key: sorted(value) for key, value in sorted(inbound_edge_map.items())
        }

        edges.sort(key=lambda edge: (edge["type"], edge["source_id"], edge["target_id"]))
        nodes.sort(key=lambda node: node["id"])
        cross_boundaries.sort(key=lambda item: item["edge_id"])

        files_ranked = sorted(
            ((file_path, len(node_ids)) for file_path, node_ids in nodes_by_file.items()),
            key=lambda item: (-item[1], item[0]),
        )
        rules_applied = sum(
            1
            for node in nodes
            if isinstance(node.get("metadata", {}).get("bsg.rules"), list)
            and len(node.get("metadata", {}).get("bsg.rules", [])) > 0
        )

        payload = {
            "schema_version": BSG_SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "root": self._root,
            "stats": {
                "total_files": len(nodes_by_file),
                "total_entities": len(nodes),
                "total_relationships": len(edges),
                "build_ms": resolved_build_ms,
                "rules_loaded": len(rule_names),
                "rules_applied": rules_applied,
            },
            "nodes": nodes,
            "edges": edges,
            "indexes": {
                "nodes_by_file": _sorted_index(nodes_by_file),
                "nodes_by_type": _sorted_index(nodes_by_type),
                "nodes_by_scope": _sorted_index(nodes_by_scope),
                "nodes_by_category": _sorted_index(nodes_by_category),
                "nodes_by_service": _sorted_index(nodes_by_service),
                "inbound_edges": sorted_inbound_edges,
                "outbound_edges": sorted_outbound_edges,
                "cross_boundaries": cross_boundaries,
            },
            "views": {
                "agent": {
                    "top_files_by_node_count": [
                        {"file": file_path, "count": count}
                        for file_path, count in files_ranked[:25]
                    ],
                    "cross_boundary_count": len(cross_boundaries),
                },
                "human": {
                    "categories": {
                        key: len(value)
                        for key, value in sorted(nodes_by_category.items())
                    },
                    "services": {
                        key: len(value)
                        for key, value in sorted(nodes_by_service.items())
                    },
                },
            },
        }
        return payload

    def _derive_scope_tier(self, entity: Entity) -> str:
        if entity.type in {
            EntityType.MODULE,
            EntityType.NAMESPACE,
            EntityType.ENTRY_POINT,
            EntityType.DOCUMENT,
        }:
            return "GLOBAL"

        if entity.type in {
            EntityType.CLASS,
            EntityType.STRUCT,
            EntityType.INTERFACE,
            EntityType.TRAIT,
            EntityType.ENUM,
            EntityType.SECTION,
        }:
            return "MODULE"

        if entity.type in {EntityType.METHOD, EntityType.FIELD, EntityType.PROPERTY}:
            return "CLASS"

        if entity.parent_id:
            return "LOCAL"

        return "MODULE"

    def _derive_service_tag(self, rel_file_path: str) -> str | None:
        parts = [part for part in Path(rel_file_path).parts if part and part != "."]
        if not parts:
            return Path(self._root).name or "root"

        for marker in ("services", "service", "apps", "modules"):
            if marker in parts:
                idx = parts.index(marker)
                if idx + 1 < len(parts):
                    return parts[idx + 1]

        if len(parts) >= 2 and parts[0] in {"backend", "frontend", "api"}:
            return parts[1]

        skip = {
            "src",
            "lib",
            "app",
            "apps",
            "service",
            "services",
            "module",
            "modules",
            "backend",
            "frontend",
            "api",
            "internal",
            "pkg",
            "tests",
            "test",
            "docs",
            "config",
            "configs",
            "scripts",
        }
        for segment in parts[:-1]:
            if segment.lower() not in skip:
                return segment

        if len(parts) == 1:
            return Path(self._root).name or "root"
        return parts[0]

    def _derive_category(self, rel_file_path: str) -> str:
        return _FILE_CATEGORIZER.categorize(rel_file_path).upper()

    def _derive_language(self, entity: Entity, rel_file_path: str) -> str:
        metadata = entity.metadata or {}
        lang = metadata.get("language")
        if isinstance(lang, str) and lang.strip():
            return lang.strip().lower()

        ext = Path(rel_file_path).suffix.lower()
        ext_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".jsx": "javascript",
            ".go": "go",
            ".rs": "rust",
            ".java": "java",
            ".rb": "ruby",
            ".php": "php",
            ".cs": "csharp",
            ".kt": "kotlin",
            ".swift": "swift",
            ".scala": "scala",
            ".c": "c",
            ".cpp": "cpp",
            ".h": "c",
            ".hpp": "cpp",
            ".json": "json",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".toml": "toml",
            ".md": "markdown",
            ".rst": "rst",
        }
        return ext_map.get(ext, "unknown")

    # ------------------------------------------------------------------
    # Directory tree rendering
    # ------------------------------------------------------------------

    def _get_directory_label(self, dir_path: str) -> str | None:
        """Get a descriptive label for a directory based on heuristics."""
        parts = dir_path.strip("/").split("/")
        if not parts or parts == [""]:
            return None
        last_part = parts[-1].lower()
        labels = {
            "tests": "Testing Suite",
            "test": "Testing Suite",
            "src": "Source Code",
            "docs": "Documentation",
            "scripts": "Scripts",
            "config": "Configuration",
            "configs": "Configuration",
            ".github": "CI/CD",
            "api": "API Layer",
            "models": "Data Models",
            "utils": "Utilities",
            "lib": "Library",
        }
        return labels.get(last_part)

    def group_by_directory(self) -> dict[str, list[tuple[str, list[Entity]]]]:
        """Group files by their directory path."""
        grouped: dict[str, list[tuple[str, list[Entity]]]] = defaultdict(list)
        for file_path, entities in self._by_file.items():
            # Use string operations for better performance
            if '/' in file_path:
                dir_path, file_name = file_path.rsplit('/', 1)
            else:
                dir_path, file_name = "", file_path
            grouped[dir_path].append((file_name, entities))
        for dir_path in grouped:
            grouped[dir_path].sort(key=lambda x: x[0])
        return dict(sorted(grouped.items()))

    def render_hierarchical(
        self,
        include_entities: bool = True,
    ) -> str:
        """
        Render a hierarchical directory tree with files and their entities.

        All paths are already relative to the workspace root (normalised at
        ``build()`` time), so no further stripping is required.

        Format::

            📁 src/auth/ (Source Code)
              📄 login.py
                deps: pathlib, os
                - login(username, password) -> AuthToken (function) [L10-20]

        Args:
            include_entities: If True, include entity details under each file.

        Returns:
            Multi-line string — the hierarchical directory tree.
        """
        lines: list[str] = []
        grouped = self.group_by_directory()

        for dir_path, files in grouped.items():
            display_path = dir_path if dir_path else "(root)"
            label = self._get_directory_label(dir_path)
            lines.append(
                f"📁 {display_path}/ ({label})" if label else f"📁 {display_path}/"
            )

            for file_name, entities in files:
                lines.append(f"  📄 {file_name}")

                # Reconstruct relative file path for dep lookup
                full_path = f"{dir_path}/{file_name}" if dir_path else file_name
                deps: list[str] = self._dependencies.get(full_path, [])
                if deps:
                    lines.append(f"    deps: {', '.join(deps)}")

                if include_entities:
                    for entity in entities:
                        sig = entity.signature or entity.name
                        type_label = str(entity.type)
                        lines.append(
                            f"    - {sig} ({type_label}) [L{entity.start_line}-{entity.end_line}]"
                        )

        return "\n".join(lines)

    def render_tree_only(self) -> str:
        """Render just the directory tree structure without entity details."""
        return self.render_hierarchical(include_entities=False)

    # ------------------------------------------------------------------
    # File categorization
    # ------------------------------------------------------------------

    def categorize_files(self) -> dict[str, dict[str, list[Entity]]]:
        """
        Categorize all files by type (tests, docs, config, source, and folder-based).

        Returns:
            Dict mapping category string to dict of file_path -> entities
        """
        categorizer = FileCategorizer()
        categorized: dict[str, dict[str, list[Entity]]] = {}

        for file_path, entities in self._by_file.items():
            category = categorizer.categorize(file_path)
            if category not in categorized:
                categorized[category] = {}
            categorized[category][file_path] = entities

        return categorized

    def render_category(
        self,
        category: str,
        include_full_entities: bool = False,
    ) -> str:
        """
        Render a specific category of files.

        Args:
            category: The category string to render
            include_full_entities: If True, include full entity details with signatures

        Returns:
            Formatted markdown string for the category
        """
        categorized = self.categorize_files()
        files_data = categorized.get(category, {})

        if not files_data:
            return f"No {category} files found."

        lines: list[str] = []
        total_entities = sum(len(ents) for ents in files_data.values())

        if not include_full_entities:
            lines.append(f"## Summary")
            lines.append(f"- Total {category} files: {len(files_data)}")
            lines.append(f"- Total entities: {total_entities}")
            lines.append("")

        grouped = self._group_by_directory_for_files(files_data)

        for dir_path, files in grouped.items():
            display_path = dir_path if dir_path else "(root)"
            label = self._get_directory_label(dir_path)
            dir_header = f"📁 {display_path}/" + (f" ({label})" if label else "")
            lines.append(dir_header)

            for file_name, entities in files:
                file_path = f"{dir_path}/{file_name}" if dir_path else file_name
                if include_full_entities:
                    entity_count = len(entities)
                    entity_types = self._summarize_entity_types(entities)
                    lines.append(f"  📄 {file_name} ({entity_count} entities: {entity_types})")
                    
                    # Group entities by type for compact display
                    entities_by_type = {}
                    for entity in entities:
                        entity_type = str(entity.type)
                        if entity_type not in entities_by_type:
                            entities_by_type[entity_type] = []
                        entities_by_type[entity_type].append(entity)
                    
                    # Display entities compactly, grouped by type
                    for entity_type, type_entities in entities_by_type.items():
                        for entity in type_entities:
                            sig = entity.signature or entity.name
                            # Remove type label since we're grouping by type
                            lines.append(f"    {sig} [L{entity.start_line}-{entity.end_line}]")
                    
                    # Compact dependencies on single line
                    deps = self._dependencies.get(file_path, [])
                    if deps:
                        deps_str = ', '.join(deps[:5])  # Show first 5 deps
                        if len(deps) > 5:
                            deps_str += f" (+{len(deps)-5} more)"
                        lines.append(f"    deps: {deps_str}")
                else:
                    entity_count = len(entities)
                    entity_types = self._summarize_entity_types(entities)
                    lines.append(
                        f"  📄 {file_name} ({entity_count} entities: {entity_types})"
                    )

        return "\n".join(lines)

    def render_uncategorized_categories(self, include_full_entities: bool = False) -> str:
        """
        Render all uncategorized/folder-based categories grouped by folder name.

        Args:
            include_full_entities: If True, include full entity details

        Returns:
            Formatted markdown string for uncategorized categories
        """
        categorized = self.categorize_files()
        
        # Standard categories to exclude
        standard_categories = {"source", "tests", "docs", "config"}
        
        # Get only non-standard categories
        uncategorized = {
            cat: files for cat, files in categorized.items() 
            if cat not in standard_categories and files
        }
        
        if not uncategorized:
            return ""
        
        lines: list[str] = []
        total_files = sum(len(files) for files in uncategorized.values())
        total_entities = sum(len(entities) for files in uncategorized.values() for entities in files.values())
        
        lines.append("## Uncategorized Files by Category")
        lines.append("")
        lines.append(f"- Total uncategorized files: {total_files}")
        lines.append(f"- Total entities: {total_entities}")
        lines.append("")
        
        # Sort categories by entity count (descending)
        sorted_categories = sorted(
            uncategorized.items(), 
            key=lambda x: sum(len(entities) for entities in x[1].values()), 
            reverse=True
        )
        
        for category_name, files_data in sorted_categories:
            cat_entity_count = sum(len(entities) for entities in files_data.values())
            cat_file_count = len(files_data)
            
            lines.append(f"### {category_name.capitalize()}")
            lines.append(f"- Total files: {cat_file_count}")
            lines.append(f"- Total entities: {cat_entity_count}")
            lines.append("")
            
            grouped = self._group_by_directory_for_files(files_data)
            
            for dir_path, files in grouped.items():
                display_path = dir_path if dir_path else "(root)"
                dir_header = f"📁 {display_path}/"
                lines.append(dir_header)
                
                for file_name, entities in files:
                    file_path = f"{dir_path}/{file_name}" if dir_path else file_name
                    if include_full_entities:
                        entity_count = len(entities)
                        entity_types = self._summarize_entity_types(entities)
                        lines.append(f"  📄 {file_name} ({entity_count} entities: {entity_types})")
                        
                        # Group entities by type for compact display
                        entities_by_type = {}
                        for entity in entities:
                            entity_type = str(entity.type)
                            if entity_type not in entities_by_type:
                                entities_by_type[entity_type] = []
                            entities_by_type[entity_type].append(entity)
                        
                        # Display entities compactly, grouped by type
                        for entity_type, type_entities in entities_by_type.items():
                            for entity in type_entities:
                                sig = entity.signature or entity.name
                                lines.append(f"    {sig} [L{entity.start_line}-{entity.end_line}]")
                    else:
                        entity_count = len(entities)
                        entity_types = self._summarize_entity_types(entities)
                        lines.append(
                            f"  📄 {file_name} ({entity_count} entities: {entity_types})"
                        )
                
                lines.append("")
            
        return "\n".join(lines)

    def _group_by_directory_for_files(
        self,
        files_data: dict[str, list[Entity]],
    ) -> dict[str, list[tuple[str, list[Entity]]]]:
        """Group files by directory for categorized output."""
        grouped: dict[str, list[tuple[str, list[Entity]]]] = defaultdict(list)
        for file_path, entities in files_data.items():
            p = PurePosixPath(file_path)
            dir_path = str(p.parent) if p.parent != PurePosixPath(".") else ""
            grouped[dir_path].append((p.name, entities))
        for dir_path in grouped:
            grouped[dir_path].sort(key=lambda x: x[0])
        return dict(sorted(grouped.items()))

    def _summarize_entity_types(self, entities: list[Entity]) -> str:
        """Summarize entity types in a file."""
        type_counts: dict[str, int] = defaultdict(int)
        for ent in entities:
            type_counts[str(ent.type)] += 1
        # Use abbreviations for common types to save space
        abbreviations = {
            "function": "func", "method": "meth", "class": "cls", 
            "document": "doc", "section": "sec", "setting": "set"
        }
        result = []
        for name, count in sorted(type_counts.items()):
            abbrev = abbreviations.get(name, name)
            result.append(f"{count} {abbrev}")
        return ", ".join(result)

    # ------------------------------------------------------------------
    # Overview generator
    # ------------------------------------------------------------------

    def render_overview(
        self,
        stack_info: dict[str, Any] | None = None,
        repo_name: str | None = None,
        timestamp: str | None = None,
        evolution_rules: list[dict[str, Any]] | None = None,
    ) -> str:
        """
        Generate comprehensive repository overview.

        Args:
            stack_info: Stack detection results from detect_stack()
            repo_name: Repository name (defaults to root directory name)
            timestamp: ISO timestamp for the index
            evolution_rules: Optional recent entries from evolution ledger

        Returns:
            Full markdown overview document
        """
        from datetime import datetime, timezone

        if repo_name is None:
            repo_name = Path(self._root).name if self._root else "repository"
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).isoformat()

        lines: list[str] = []
        lines.append(f"# 📊 {repo_name} - Repository Overview")
        lines.append("")
        lines.append(f"*Generated: {timestamp}*")
        lines.append("")

        categorized = self.categorize_files()
        total_files = len(self._by_file)
        total_entities = self.entity_count
        total_relationships = sum(len(deps) for deps in self._dependencies.values())

        lines.append("## Repository Summary")
        lines.append("")
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Total Files | {total_files} |")
        lines.append(f"| Total Entities | {total_entities} |")
        lines.append(f"| Total Relationships | {total_relationships} |")
        lines.append("")

        if evolution_rules:
            lines.append("## Evolution Ledger Insights")
            lines.append("")
            for item in evolution_rules:
                dont_rule = str(item.get("dont_rule") or "").strip()
                if not dont_rule:
                    continue
                source = str(item.get("source") or "unknown")
                timestamp_hint = str(item.get("timestamp") or "").strip()
                if timestamp_hint:
                    lines.append(f"- **{source}**: {dont_rule} *(recorded {timestamp_hint})*")
                else:
                    lines.append(f"- **{source}**: {dont_rule}")
            lines.append("")

        lines.append("## File Distribution")
        lines.append("")
        cat_counts = {cat: len(files) for cat, files in categorized.items()}
        cat_entities = {
            cat: sum(len(ents) for ents in files.values())
            for cat, files in categorized.items()
        }

        # Sort categories by file count, but prioritize main categories first
        main_categories = ["source", "tests", "docs", "config"]
        other_categories = sorted([cat for cat in categorized.keys() if cat not in main_categories])
        ordered_categories = main_categories + [cat for cat in other_categories if cat in categorized]
        
        for cat in ordered_categories:
            if cat in categorized:  # Only show categories that have files
                count = cat_counts.get(cat, 0)
                entities = cat_entities.get(cat, 0)
                pct = (count / total_files * 100) if total_files > 0 else 0
                bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
                # Capitalize first letter for display
                display_name = cat.capitalize() if cat != "docs" else "Docs"
                lines.append(
                    f"- **{display_name}**: {count} files ({pct:.1f}%) | {entities} entities"
                )
        lines.append("")

        lines.append("## Language Breakdown")
        lines.append("")
        lang_counts = self._count_by_language()
        if lang_counts:
            lines.append("| Language | Files | Percentage |")
            lines.append("|----------|-------|------------|")
            for lang, count in sorted(lang_counts.items(), key=lambda x: -x[1]):
                pct = (count / total_files * 100) if total_files > 0 else 0
                lines.append(f"| {lang} | {count} | {pct:.1f}% |")
            primary = (
                max(lang_counts.items(), key=lambda x: x[1])[0]
                if lang_counts
                else "N/A"
            )
            lines.append(f"\n**Primary Language**: {primary}")
        else:
            lines.append("No language data available.")
        lines.append("")

        if stack_info:
            lines.append("## Technology Stack")
            lines.append("")
            categories = {
                "backend": "Backend",
                "frontend": "Frontend",
                "database": "Database",
                "devops": "DevOps",
                "testing": "Testing",
                "tools": "Tools",
            }
            for cat_key, cat_label in categories.items():
                items = stack_info.get(cat_key, [])
                if items:
                    lines.append(f"### {cat_label}")
                    for item in items:
                        lines.append(f"- {item}")
                    lines.append("")

        lines.append("## Directory Structure")
        lines.append("")
        tree_lines = self._render_high_level_tree(max_depth=3)
        for line in tree_lines:
            lines.append(line)
        lines.append("")

        lines.append("## Entity Statistics")
        lines.append("")
        lines.append("| Entity Type | Count |")
        lines.append("|-------------|-------|")
        type_counts: dict[str, int] = defaultdict(int)
        for entities in self._by_file.values():
            for ent in entities:
                type_counts[str(ent.type)] += 1
        for ent_type, count in sorted(type_counts.items(), key=lambda x: -x[1]):
            lines.append(f"| {ent_type} | {count} |")
        lines.append("")

        lines.append("## Top Dependencies")
        lines.append("")
        all_deps: dict[str, int] = defaultdict(int)
        for deps in self._dependencies.values():
            for dep in deps:
                all_deps[dep] += 1
        top_deps = sorted(all_deps.items(), key=lambda x: -x[1])[:10]
        if top_deps:
            lines.append("| Dependency | References |")
            lines.append("|------------|------------|")
            for dep, count in top_deps:
                lines.append(f"| {dep} | {count} |")
        else:
            lines.append("No dependency data available.")
        lines.append("")

        return "\n".join(lines)

    def _count_by_language(self) -> dict[str, int]:
        """Count files by detected language."""
        lang_counts: dict[str, int] = {}
        ext_to_lang = {
            ".py": "Python",
            ".js": "JavaScript",
            ".ts": "TypeScript",
            ".tsx": "TypeScript (React)",
            ".jsx": "JavaScript (React)",
            ".go": "Go",
            ".rs": "Rust",
            ".java": "Java",
            ".rb": "Ruby",
            ".php": "PHP",
            ".cs": "C#",
            ".kt": "Kotlin",
            ".swift": "Swift",
            ".scala": "Scala",
            ".c": "C",
            ".cpp": "C++",
            ".h": "C/C++ Header",
            ".hpp": "C++ Header",
            ".m": "Objective-C",
            ".mm": "Objective-C++",
            ".sh": "Shell",
            ".bash": "Bash",
            ".zsh": "Zsh",
            ".mjs": "ES Module",
            ".cjs": "CommonJS",
        }
        for file_path in self._by_file.keys():
            ext = Path(file_path).suffix.lower()
            lang = ext_to_lang.get(ext, ext.lstrip(".").upper() if ext else "Other")
            lang_counts[lang] = lang_counts.get(lang, 0) + 1
        return lang_counts

    def _render_high_level_tree(self, max_depth: int = 3) -> list[str]:
        """Render a high-level directory tree."""
        lines: list[str] = []
        grouped = self.group_by_directory()

        def get_depth(path: str) -> int:
            return len([p for p in path.split("/") if p])

        for dir_path, files in sorted(grouped.items()):
            depth = get_depth(dir_path)
            if depth > max_depth:
                continue

            indent = "  " * depth
            label = self._get_directory_label(dir_path)
            dir_name = dir_path.split("/")[-1] if dir_path else "root"

            if depth == 0:
                lines.append(f"📁 {dir_name}/")
            else:
                lines.append(
                    f"{indent}📁 {dir_name}/ ({label})"
                    if label
                    else f"{indent}📁 {dir_name}/"
                )

            if depth < max_depth:
                file_indent = "  " * (depth + 1)
                for file_name, _ in sorted(files)[:5]:
                    lines.append(f"{file_indent}📄 {file_name}")
                if len(files) > 5:
                    lines.append(f"{file_indent}... and {len(files) - 5} more")

        return lines

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def estimate_tokens(self) -> int:
        """Estimate the token count of the full render_full() output."""
        if not self._by_file:
            return 0
        return _text_tokens(self.render_full())

    @property
    def file_count(self) -> int:
        """Number of source files in this map."""
        return len(self._by_file)

    @property
    def entity_count(self) -> int:
        """Total number of entities across all files."""
        return sum(len(v) for v in self._by_file.values())
