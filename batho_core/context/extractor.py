"""
backend/context/extractor.py — Production ASTExtractor base class.

Hardened from the prototype with:
- Per-file exception isolation (one bad file won't abort the whole scan)
- Max file size guard (default 500KB) for generated/minified files
- Encoding detection fallback: UTF-8 → latin-1 → replace
- Consistent import path (no cross-package hacks)

Design principles:
- No raw dicts escape this layer — all outputs are frozen Pydantic models.
- Deterministic: same source always produces same entities.
- Uses QueryCursor(Query(...)).captures() — tree-sitter 0.25+ compliant API.
"""

from __future__ import annotations

import abc
import re
import time
from typing import Any

from tree_sitter import Language, Node, Query, QueryCursor
from tree_sitter_language_pack import get_language, get_parser

from batho_core.utils.encoding import normalize_to_utf8
from batho_core.utils.logging import get_logger

from .schema import (
    Entity,
    EntityMetadata,
    EntityType,
    Relationship,
    RelationshipType,
)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# Capture name suffixes that supply auxiliary metadata about a definition node.
_META_SUFFIXES: frozenset[str] = frozenset(
    {
        "params",
        "return_type",
        "visibility",
        "docstring",
        "bases",
        "implements",
        "extends",
        "trait",
        "receiver",
        "type",
    }
)

# Map from base capture key (e.g. "def.function") → EntityType
_CAPTURE_ENTITY_MAP: dict[str, EntityType] = {
    "def.function": EntityType.FUNCTION,
    "def.method": EntityType.METHOD,
    "def.class": EntityType.CLASS,
    "def.module": EntityType.MODULE,
    "def.struct": EntityType.STRUCT,
    "def.interface": EntityType.INTERFACE,
    "def.protocol": EntityType.INTERFACE,
    "def.field": EntityType.FIELD,
    "def.enum": EntityType.ENUM,
    "def.trait": EntityType.TRAIT,
    "def.type_alias": EntityType.TYPE_ALIAS,
    "def.constant": EntityType.CONSTANT,
    "def.namespace": EntityType.NAMESPACE,
    "def.entry_point": EntityType.ENTRY_POINT,
}

# Map from reference capture key → RelationshipType
_CAPTURE_REL_MAP: dict[str, RelationshipType] = {
    "ref.call": RelationshipType.CALLS,
    "ref.import": RelationshipType.IMPORTS,
    "ref.inherit": RelationshipType.INHERITS,
    "ref.implement": RelationshipType.IMPLEMENTS,
    "ref.use": RelationshipType.USES,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _node_text(node: Node, source: bytes) -> str:
    """Slice raw bytes and decode to a clean UTF-8 string."""
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace").strip()


def _clean_docstring(text: str) -> str:
    """Strip surrounding quote characters from docstrings."""
    t = text.strip()
    for q in ('"""', "'''", '"', "'"):
        if t.startswith(q) and t.endswith(q) and len(t) >= 2 * len(q):
            return t[len(q) : -len(q)].strip()
    return t


def _relationship_capture_info(cap_name: str) -> tuple[RelationshipType | None, str | None]:
    """Map a capture name to relationship type and optional capture variant."""
    parts = cap_name.split(".")
    if len(parts) < 2 or parts[0] != "ref":
        return None, None

    base_key = f"{parts[0]}.{parts[1]}"
    rel_type = _CAPTURE_REL_MAP.get(base_key)
    if rel_type is None:
        return None, None

    suffix = ".".join(parts[2:]).strip() if len(parts) > 2 else ""
    return rel_type, suffix or None


def _normalize_import_target(raw: str) -> str:
    """Normalize a raw import string to improve cross-file matching."""
    text = raw.strip().strip(",;")
    if not text:
        return ""

    text = re.sub(r"\s+as\s+\w+$", "", text).strip()

    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'", "`"}:
        text = text[1:-1].strip()
    elif text.startswith("<") and text.endswith(">"):
        text = text[1:-1].strip()

    text = text.replace("::", ".")
    return text.strip()


def _expand_import_targets(raw: str) -> list[str]:
    """Expand grouped import forms into resolvable target candidates."""
    normalized = _normalize_import_target(raw)
    if not normalized:
        return []

    candidates: list[str] = []
    seen: set[str] = set()
    stopwords = {
        ".",
        "as",
        "from",
        "import",
        "include",
        "library",
        "load",
        "loadnamespace",
        "require",
        "require_relative",
        "requirenamespace",
        "source",
        "using",
    }

    def _push(candidate: str) -> None:
        token = _normalize_import_target(candidate)
        if token.lower() in stopwords:
            return
        if not token or token in seen:
            return
        seen.add(token)
        candidates.append(token)

    _push(normalized)

    # Rust-like grouped imports: foo::{bar, baz as qux, self, *}
    if "{" in normalized and "}" in normalized:
        prefix, remainder = normalized.split("{", 1)
        prefix = prefix.rstrip(":.").strip()
        members = remainder.rsplit("}", 1)[0]
        for member in members.split(","):
            token = member.strip()
            if not token:
                continue
            token = re.sub(r"\s+as\s+\w+$", "", token)
            if token in {"*", "self"}:
                _push(prefix)
                continue
            if prefix:
                _push(f"{prefix}.{token}")
            else:
                _push(token)

    if "/" in normalized:
        _push(normalized.rsplit("/", 1)[-1])

    if "." in normalized:
        _push(normalized.rsplit(".", 1)[-1])

    return candidates


# File reading is now handled in batho_core.utils.file_io


# ---------------------------------------------------------------------------
# ASTExtractor — base class for tree-sitter extractors
# ---------------------------------------------------------------------------


class ASTExtractor(abc.ABC):
    """
    Abstract base class for language-specific AST extractors.

    Subclasses implement :py:meth:`_query_source` to supply a tree-sitter
    SCM query string for their language.  The base class handles:

    - Parsing raw bytes via tree-sitter.
    - Grouping captures into definition / auxiliary buckets.
    - Instantiating frozen Pydantic Entity and Relationship models.
    - Emitting structured debug logs with parse timing metrics.

    Capture naming convention (SCM query side)::

        @def.function.name        — identifier node of a function definition
        @def.function.params      — parameter list node
        @def.function.return_type — return type annotation node
        @def.function.visibility  — visibility modifier (pub/public/private)
        @def.function.docstring   — docstring node
        @def.class.bases          — base class list (Python)
        @def.class.implements     — interface list (Java/TS)
        @def.class.extends        — superclass (Java)
        @ref.call                 — function call reference
        @ref.import               — import reference
    """

    def __init__(self, language: str) -> None:
        """
        Initialise the extractor for *language*.

        Args:
            language: Language identifier accepted by tree-sitter-language-pack
                      (e.g. "python", "typescript", "rust").
        """
        self._language_name: str = language
        self._ts_parser = get_parser(language)  # type: ignore[arg-type]
        self._ts_language: Language = get_language(language)  # type: ignore[arg-type]
        self.logger = get_logger(__name__, operation="ast_extract").bind(language=language)

    # ------------------------------------------------------------------
    # Subclass contract
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def _query_source(self) -> str:
        """
        Return the tree-sitter SCM query string for this language.

        The query must use the capture naming convention documented on the
        class docstring. At minimum it should capture ``@def.<type>.name``
        nodes for each symbol type of interest.
        """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse_file(
        self,
        filepath: str,
        content: bytes,
    ) -> tuple[list[Entity], list[Relationship]]:
        """
        Parse *content* and return extracted entities and relationships.

        This method is fully exception-isolated: any internal error is caught,
        logged, and an empty result is returned so the caller can continue
        processing other files.

        Args:
            filepath: Repo-relative path stored as the ``file`` field on every
                      extracted Entity.
            content:  Raw source bytes.

        Returns:
            A 2-tuple ``(entities, relationships)``, both sorted by source position.
        """
        t0 = time.perf_counter()

        try:
            tree = self._ts_parser.parse(content)
        except (TypeError, ValueError) as exc:
            self.logger.warning(
                "parse_failed",
                filepath=filepath,
                error=str(exc),
            )
            return [], []

        try:
            query = Query(self._ts_language, self._query_source())
        except (TypeError, ValueError) as exc:
            self.logger.debug(
                "query_creation_failed",
                filepath=filepath,
                error=str(exc),
            )
            return [], []

        try:
            cursor = QueryCursor(query)
            raw_captures: dict[str, list[Node]] = cursor.captures(tree.root_node)
            entities, relationships = self._process_captures(raw_captures, content, filepath)
        except Exception as exc:
            self.logger.warning(
                "capture_processing_failed",
                filepath=filepath,
                error=str(exc),
            )
            return [], []

        parse_ms = round((time.perf_counter() - t0) * 1000, 2)
        self.logger.debug(
            "parse_file_complete",
            filepath=filepath,
            parse_ms=parse_ms,
            entity_count=len(entities),
            relationship_count=len(relationships),
        )
        return entities, relationships

    # ------------------------------------------------------------------
    # Internal — capture processing
    # ------------------------------------------------------------------

    def _process_captures(
        self,
        captures: dict[str, list[Node]],
        source: bytes,
        filepath: str,
    ) -> tuple[list[Entity], list[Relationship]]:
        """
        Group raw captures into entity definitions + auxiliary metadata,
        then build frozen Pydantic models.
        """
        # definition_nodes: "def.function" → [name_node, ...]
        definition_nodes: dict[str, list[Node]] = {}
        # auxiliary_nodes: ("def.function", "params") → [node, ...]
        auxiliary_nodes: dict[tuple[str, str], list[Node]] = {}

        for cap_name, nodes in captures.items():
            parts = cap_name.split(".")
            if len(parts) == 3 and parts[0] == "def":
                base_key = f"{parts[0]}.{parts[1]}"
                suffix = parts[2]
                if suffix == "name":
                    definition_nodes.setdefault(base_key, []).extend(nodes)
                elif suffix in _META_SUFFIXES:
                    auxiliary_nodes.setdefault((base_key, suffix), []).extend(nodes)
            elif len(parts) == 2 and parts[0] in ("def", "ref"):
                definition_nodes.setdefault(cap_name, []).extend(nodes)

        entities = self._build_entities(definition_nodes, auxiliary_nodes, source, filepath)
        relationships = self._build_relationships(captures, entities, source, filepath)
        return entities, relationships

    def _build_entities(
        self,
        definition_nodes: dict[str, list[Node]],
        auxiliary_nodes: dict[tuple[str, str], list[Node]],
        source: bytes,
        filepath: str,
    ) -> list[Entity]:
        """Instantiate Entity models from grouped capture nodes."""
        entities: list[Entity] = []

        for base_key, name_nodes in definition_nodes.items():
            entity_type = _CAPTURE_ENTITY_MAP.get(base_key)
            if entity_type is None:
                continue

            for name_node in name_nodes:
                name = _node_text(name_node, source)
                if not name:
                    continue

                decl_node: Node = name_node.parent if name_node.parent is not None else name_node

                metadata = self._collect_metadata_with_source(
                    base_key, decl_node, auxiliary_nodes, source
                )
                signature = self._build_signature(
                    name, base_key, decl_node, auxiliary_nodes, source
                )

                entity = Entity(
                    type=entity_type,
                    name=name,
                    file=filepath,
                    start_line=decl_node.start_point[0] + 1,
                    end_line=decl_node.end_point[0] + 1,
                    start_byte=decl_node.start_byte,
                    end_byte=decl_node.end_byte,
                    signature=signature,
                    metadata=metadata,
                )
                entities.append(entity)

        entities.sort(key=lambda e: e.start_byte)
        return entities

    def _build_relationships(
        self,
        captures: dict[str, list[Node]],
        entities: list[Entity],
        source: bytes,
        filepath: str,
    ) -> list[Relationship]:
        """Build Relationship models from reference captures."""
        relationships: list[Relationship] = []
        emitted: set[tuple[str, str, str]] = set()

        def _add(
            src_id: str,
            tgt_id: str,
            rel_type: RelationshipType,
            line: int,
            extra_metadata: dict[str, Any] | None = None,
        ) -> None:
            key = (src_id, tgt_id, str(rel_type))
            if key not in emitted:
                emitted.add(key)
                metadata = {"line_number": line}
                if extra_metadata:
                    metadata.update(extra_metadata)
                relationships.append(
                    Relationship(
                        source_id=src_id,
                        target_id=tgt_id,
                        type=rel_type,
                        metadata=metadata,
                    )
                )

        # CONTAINS: parent entity → child entity
        for i, child in enumerate(entities):
            for j in range(i - 1, -1, -1):
                parent = entities[j]
                if (
                    parent.start_byte <= child.start_byte
                    and parent.end_byte >= child.end_byte
                    and parent.id != child.id
                ):
                    _add(parent.id, child.id, RelationshipType.CONTAINS, child.start_line)
                    break

        by_name: dict[str, Entity] = {e.name: e for e in entities}
        sorted_ents = entities

        def _find_enclosing(byte_offset: int) -> Entity | None:
            best: Entity | None = None
            for ent in sorted_ents:
                if ent.start_byte <= byte_offset <= ent.end_byte:
                    if best is None or (
                        ent.end_byte - ent.start_byte < best.end_byte - best.start_byte
                    ):
                        best = ent
            return best

        for cap_name, nodes in captures.items():
            rel_type, capture_variant = _relationship_capture_info(cap_name)
            if rel_type is None:
                continue
            if rel_type == RelationshipType.CONTAINS:
                continue

            for node in nodes:
                ref_text = _node_text(node, source)
                if not ref_text:
                    continue

                line_no = node.start_point[0] + 1

                rel_meta = {"capture": cap_name}
                if capture_variant:
                    rel_meta["capture_variant"] = capture_variant

                if rel_type in (
                    RelationshipType.CALLS,
                    RelationshipType.USES,
                    RelationshipType.REFERENCES,
                ):
                    source_ent = _find_enclosing(node.start_byte)
                    target_ent = by_name.get(ref_text)
                    if (
                        source_ent is not None
                        and target_ent is not None
                        and source_ent.id != target_ent.id
                    ):
                        _add(source_ent.id, target_ent.id, rel_type, line_no, rel_meta)

                elif rel_type == RelationshipType.IMPORTS:
                    source_ent = _find_enclosing(node.start_byte)
                    source_id = source_ent.id if source_ent else filepath
                    targets = _expand_import_targets(ref_text)
                    if not targets:
                        continue

                    for target_ref in targets:
                        target_ent = by_name.get(target_ref)
                        if target_ent is not None and source_id != target_ent.id:
                            _add(source_id, target_ent.id, rel_type, line_no, rel_meta)
                        elif target_ent is None:
                            # External import — store as unresolved reference.
                            # CodeGraphIndexer resolves these in a cross-file pass.
                            _add(
                                source_id,
                                f"unresolved:{target_ref}",
                                rel_type,
                                line_no,
                                rel_meta,
                            )
                            self.logger.debug(
                                "unresolved_import",
                                filepath=filepath,
                                ref=target_ref,
                            )

                elif rel_type in (RelationshipType.INHERITS, RelationshipType.IMPLEMENTS):
                    source_ent = _find_enclosing(node.start_byte)
                    if source_ent is None:
                        continue

                    target_ent = by_name.get(ref_text)
                    if target_ent is not None and source_ent.id != target_ent.id:
                        _add(source_ent.id, target_ent.id, rel_type, line_no, rel_meta)
                    elif target_ent is None:
                        normalized_ref = _normalize_import_target(ref_text)
                        if normalized_ref:
                            _add(
                                source_ent.id,
                                f"unresolved:{normalized_ref}",
                                rel_type,
                                line_no,
                                rel_meta,
                            )

        return relationships

    # ------------------------------------------------------------------
    # Internal — metadata / signature helpers
    # ------------------------------------------------------------------

    def _collect_metadata_with_source(
        self,
        base_key: str,
        decl_node: Node,
        auxiliary_nodes: dict[tuple[str, str], list[Node]],
        source: bytes,
    ) -> EntityMetadata:
        """Collect full EntityMetadata including text fields that require source bytes."""
        metadata: EntityMetadata = {}
        metadata["language"] = self._language_name

        suffix_key_map: list[tuple[str, str]] = [
            ("visibility", "visibility"),
            ("docstring", "docstring"),
            ("bases", "bases"),
            ("extends", "extends"),
            ("trait", "trait"),
            ("receiver", "receiver"),
        ]
        for suffix, meta_key in suffix_key_map:
            nodes = auxiliary_nodes.get((base_key, suffix), [])
            node = self._nearest_ancestor(nodes, decl_node)
            if node is None:
                continue
            text = _node_text(node, source)
            if suffix == "docstring":
                text = _clean_docstring(text)
            metadata[meta_key] = text

        if not metadata.get("docstring"):
            fallback_doc = self._extract_leading_doc_comment(decl_node=decl_node, source=source)
            if fallback_doc:
                metadata["docstring"] = fallback_doc

        # implements: comma-separated list
        impl_nodes = auxiliary_nodes.get((base_key, "implements"), [])
        impl_node = self._nearest_ancestor(impl_nodes, decl_node)
        if impl_node is not None:
            raw = _node_text(impl_node, source)
            metadata["implements"] = [s.strip() for s in raw.split(",") if s.strip()]

        # field_type
        ft_nodes = auxiliary_nodes.get((base_key, "type"), [])
        ft_node = self._nearest_ancestor(ft_nodes, decl_node)
        if ft_node is not None:
            metadata["field_type"] = _node_text(ft_node, source)

        return metadata

    def _extract_leading_doc_comment(self, decl_node: Node, source: bytes) -> str | None:
        """Extract contiguous comment lines immediately above a declaration."""
        try:
            text = source.decode("utf-8", errors="replace")
        except Exception:
            return None

        lines = text.splitlines()
        line_idx = decl_node.start_point[0] - 1
        if line_idx < 0:
            return None

        comment_prefixes = ["#", "//", "--", ";", "%"]
        collected: list[str] = []
        in_block = False

        while line_idx >= 0:
            raw = lines[line_idx].rstrip()
            stripped = raw.strip()

            if not stripped:
                if collected:
                    break
                line_idx -= 1
                continue

            if stripped.endswith("*/"):
                in_block = True

            if in_block:
                cleaned = stripped
                cleaned = cleaned.lstrip("/*").rstrip("*/").strip()
                if cleaned:
                    collected.append(cleaned)
                if stripped.startswith("/*"):
                    in_block = False
                line_idx -= 1
                continue

            matched_prefix = next(
                (prefix for prefix in comment_prefixes if stripped.startswith(prefix)),
                None,
            )
            if matched_prefix is not None:
                cleaned = stripped[len(matched_prefix) :].strip()
                if cleaned:
                    collected.append(cleaned)
                line_idx -= 1
                continue

            break

        if not collected:
            return None
        return "\n".join(reversed(collected)).strip() or None

    def _build_signature(
        self,
        name: str,
        base_key: str,
        decl_node: Node,
        auxiliary_nodes: dict[tuple[str, str], list[Node]],
        source: bytes,
    ) -> str | None:
        """Construct a human-readable signature string from params + return type."""
        params_nodes = auxiliary_nodes.get((base_key, "params"), [])
        rt_nodes = auxiliary_nodes.get((base_key, "return_type"), [])

        params_node = self._nearest_ancestor(params_nodes, decl_node)
        rt_node = self._nearest_ancestor(rt_nodes, decl_node)

        if params_node is None and rt_node is None:
            return None

        params_text = _node_text(params_node, source) if params_node else "()"
        rt_text = _node_text(rt_node, source) if rt_node else ""

        if rt_text:
            return f"{name}{params_text} -> {rt_text}"
        return f"{name}{params_text}"

    @staticmethod
    def _nearest_ancestor(nodes: list[Node], decl_node: Node) -> Node | None:
        """
        Return the node from *nodes* whose ancestor chain passes through
        *decl_node*, i.e. the auxiliary node that belongs to this specific
        definition. Falls back to the first node if none are nested.
        """
        if not nodes:
            return None
        for candidate in nodes:
            current: Node | None = candidate.parent
            while current is not None:
                if current.id == decl_node.id:
                    return candidate
                current = current.parent
        return nodes[0]

    def _enrich_entity(
        self,
        entity: Entity,
        decl_node: Node,
        auxiliary_nodes: dict[tuple[str, str], list[Node]],
        source: bytes,
    ) -> Entity:
        """Optional hook for subclasses to enrich an entity after construction."""
        base_key = f"def.{entity.type}"
        full_metadata = self._collect_metadata_with_source(
            base_key,
            decl_node,
            auxiliary_nodes,
            source,
        )
        return entity.model_copy(update={"metadata": full_metadata})


# ---------------------------------------------------------------------------
# MarkupConfigExtractor — base for markup and config file extractors
# ---------------------------------------------------------------------------


class MarkupConfigExtractor(ASTExtractor):
    """
    Abstract base class for markup and configuration file extractors.

    Handles HTML, CSS, Markdown, JSON, YAML, TOML, HCL — formats that
    have different structures than programming languages.

    Subclasses must implement:
    - _extract_elements(): Extract structural elements from the content
    - _extract_references(): Extract references/relationships between elements
    """

    def __init__(self, language: str) -> None:
        self._language_name = language
        self._ts_parser = None
        self._ts_language = None
        self.logger = get_logger(__name__, operation="markup_extract").bind(language=language)

    def _query_source(self) -> str:
        """Return empty query — subclasses override parse_file() directly."""
        return ""

    @abc.abstractmethod
    def _extract_elements(
        self,
        source: bytes,
        filepath: str,
    ) -> list[Entity]:
        """Extract elements from markup/config content."""

    @abc.abstractmethod
    def _extract_references(
        self,
        source: bytes,
        filepath: str,
        entities: list[Entity],
    ) -> list[Relationship]:
        """Extract relationships from markup/config content."""

    def parse_file(
        self,
        filepath: str,
        content: bytes,
    ) -> tuple[list[Entity], list[Relationship]]:
        """Parse a markup or configuration file."""
        t0 = time.perf_counter()

        try:
            entities = self._extract_elements(content, filepath)
            relationships = self._extract_references(content, filepath, entities)
            entities.sort(key=lambda e: e.start_byte)
        except Exception as exc:
            self.logger.warning(
                "markup_parse_failed",
                filepath=filepath,
                error=str(exc),
            )
            return [], []

        parse_ms = round((time.perf_counter() - t0) * 1000, 2)
        self.logger.debug(
            "parse_file_complete",
            filepath=filepath,
            parse_ms=parse_ms,
            entity_count=len(entities),
            relationship_count=len(relationships),
        )
        return entities, relationships

    def _create_entity(
        self,
        entity_type: EntityType,
        name: str,
        filepath: str,
        start_line: int,
        end_line: int,
        start_byte: int,
        end_byte: int,
        metadata: EntityMetadata | None = None,
    ) -> Entity:
        """Helper to create an Entity with consistent defaults."""
        payload = dict(metadata or {})
        payload.setdefault("language", self._language_name)
        return Entity(
            type=entity_type,
            name=name,
            file=filepath,
            start_line=start_line,
            end_line=end_line,
            start_byte=start_byte,
            end_byte=end_byte,
            signature=None,
            metadata=payload,
        )

    def _create_relationship(
        self,
        source_id: str,
        target_id: str,
        rel_type: RelationshipType,
        line: int,
    ) -> Relationship:
        """Helper to create a Relationship with consistent defaults."""
        return Relationship(
            source_id=source_id,
            target_id=target_id,
            type=rel_type,
            metadata={"line_number": line},
        )

    def _extract_key_value_pairs(
        self,
        source: bytes,
        filepath: str,
    ) -> list[Entity]:
        """Default implementation for extracting key-value pairs (no-op)."""
        return []
