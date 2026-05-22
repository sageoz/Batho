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
import bisect
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

from tree_sitter import Language, Node, Query, QueryCursor
from tree_sitter_language_pack import get_language, get_parser

from batho.utils.encoding import normalize_to_utf8
from batho.utils.hash import compute_bytes_hash
from batho.utils.logging import get_logger

from .schema import (
    CoverageError,
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
        "invocation",
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
    return (
        source[node.start_byte : node.end_byte]
        .decode("utf-8", errors="replace")
        .strip()
    )


def _clean_docstring(text: str) -> str:
    """Strip surrounding quote characters from docstrings."""
    t = text.strip()

    # Handle Python-prefixed literals captured as docstrings (e.g. b"""...""").
    prefix_match = re.match(r"(?i)^(?:br|rb|fr|rf|b|r|f|u)(?=[\"'])", t)
    if prefix_match:
        t = t[prefix_match.end() :].lstrip()

    for q in ('"""', "'''", '"', "'"):
        if t.startswith(q) and t.endswith(q) and len(t) >= 2 * len(q):
            return t[len(q) : -len(q)].strip()
    return t


def _relationship_capture_info(
    cap_name: str,
) -> tuple[RelationshipType | None, str | None]:
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


# File reading is now handled in batho.utils.file_io


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

    def __init__(
        self, language: str, parsing_config: dict[str, Any] | None = None
    ) -> None:
        """
        Initialise the extractor for *language*.

        Args:
            language: Language identifier accepted by tree-sitter-language-pack
                      (e.g. "python", "typescript", "rust").
            parsing_config: Optional parsing configuration dict with keys:
                - error_recovery: bool (default True)
                - partial_parsing: bool (default False)
                - skip_comments: bool (default False)
        """
        self._language_name: str = language
        self._ts_parser = get_parser(language)  # type: ignore[arg-type]
        self._ts_language: Language = get_language(language)  # type: ignore[arg-type]
        self._compiled_query: Query | None = None
        self._compile_failed: bool = False
        self._query_lock = threading.Lock()
        self._parsing_config: dict[str, Any] = parsing_config or {}
        self.logger = get_logger(__name__, operation="ast_extract").bind(
            language=language
        )

    def _get_compiled_query(self) -> Query | None:
        """Compile and cache the tree-sitter query once per extractor instance.

        Returns ``None`` when compilation has failed or the query is unavailable.
        Uses a flag to ensure a failed compilation is never retried.
        """
        # Fast path: already compiled (success) or already known to have failed.
        if self._compile_failed:
            return None
        if self._compiled_query is not None:
            return self._compiled_query

        with self._query_lock:
            # Re-check under the lock (another thread may have compiled).
            if self._compile_failed:
                return None
            if self._compiled_query is not None:
                return self._compiled_query

            try:
                self._compiled_query = Query(self._ts_language, self._query_source())
            except (TypeError, ValueError) as exc:
                self.logger.debug(
                    "query_compilation_failed",
                    error=str(exc),
                    language=getattr(self, '_language_name', 'unknown'),
                )
                # Set the flag so future calls skip the lock entirely.
                self._compile_failed = True
                return None
            return self._compiled_query

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
        index_id: str | None = None,
        include_gaps: bool = False,
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
            index_id: Optional index ID to stamp on entities.
            include_gaps: When True, emit SYNTAX_GLUE entities for every byte
                          not covered by semantic entities, producing 100% coverage.

        Returns:
            A 2-tuple ``(entities, relationships)``, both sorted by source position.
        """
        t0 = time.perf_counter()

        # Check if error recovery is enabled
        error_recovery = self._parsing_config.get("error_recovery", True)

        try:
            tree = self._ts_parser.parse(content)
        except (TypeError, ValueError) as exc:
            # Error recovery: tree-sitter still produces a tree on syntax errors.
            # A second parse() call with identical args will not change the result;
            # just log and return empty to avoid blocking the whole build.
            self.logger.warning(
                "parse_failed",
                filepath=filepath,
                error=str(exc),
            )
            return [], []

        # Check if we should skip comment nodes
        skip_comments = self._parsing_config.get("skip_comments", False)

        query = self._get_compiled_query()
        if query is None:
            self.logger.debug(
                "query_unavailable",
                filepath=filepath,
            )
            return [], []

        try:
            cursor = QueryCursor(query)
            # If skip_comments is enabled, we'll filter during capture processing
            raw_captures: dict[str, list[Node]] = cursor.captures(tree.root_node)

            if skip_comments:
                raw_captures = self._filter_comment_captures(raw_captures)

            entities, relationships = self._process_captures(
                raw_captures, content, filepath, index_id=index_id
            )
            entities = self._enrich_bidirectional_attributes(entities, content)
        except Exception as exc:
            if error_recovery:
                self.logger.warning(
                    "capture_processing_failed_with_recovery",
                    filepath=filepath,
                    error=str(exc),
                )
                # Return empty results but don't fail the entire build
                return [], []
            else:
                self.logger.warning(
                    "capture_processing_failed",
                    filepath=filepath,
                    error=str(exc),
                )
                return [], []

        if include_gaps:
            gap_entities = self._extract_gaps(content, filepath, entities)
            entities.extend(gap_entities)
            entities.sort(key=lambda e: e.start_byte)
        else:
            gap_entities = []

        parse_ms = round((time.perf_counter() - t0) * 1000, 2)
        self.logger.debug(
            "parse_file_complete",
            filepath=filepath,
            parse_ms=parse_ms,
            entity_count=len(entities),
            relationship_count=len(relationships),
            error_recovery=error_recovery,
            skip_comments=skip_comments,
            include_gaps=include_gaps,
            gap_count=len(gap_entities) if include_gaps else 0,
        )
        return entities, relationships

    def _filter_comment_captures(
        self, captures: dict[str, list[Node]]
    ) -> dict[str, list[Node]]:
        """
        Filter out comment-related captures when skip_comments is enabled.

        This removes captures that are primarily comment nodes, reducing AST size
        and processing time for comment-heavy files.
        """
        filtered: dict[str, list[Node]] = {}
        for key, nodes in captures.items():
            # Filter out nodes that are comment types
            # Common comment node types across languages
            filtered_nodes = [
                node
                for node in nodes
                if node.type
                not in {
                    "comment",
                    "line_comment",
                    "block_comment",
                    "doc_comment",
                    "docstring",
                }
            ]
            if filtered_nodes:
                filtered[key] = filtered_nodes
        return filtered

    # ------------------------------------------------------------------
    # Internal — capture processing
    # ------------------------------------------------------------------

    def _process_captures(
        self,
        captures: dict[str, list[Node]],
        source: bytes,
        filepath: str,
        index_id: str | None = None,
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

        entities = self._build_entities(
            definition_nodes, auxiliary_nodes, source, filepath, index_id=index_id
        )
        unresolved_entities, relationships = self._build_relationships(
            captures, entities, source, filepath
        )
        entities.extend(unresolved_entities)
        return entities, relationships

    def _build_entities(
        self,
        definition_nodes: dict[str, list[Node]],
        auxiliary_nodes: dict[tuple[str, str], list[Node]],
        source: bytes,
        filepath: str,
        index_id: str | None = None,
    ) -> list[Entity]:
        """Instantiate Entity models from grouped capture nodes."""
        entities: list[Entity] = []

        # Pre-decode source lines once for the whole file to avoid repeated
        # decode+splitlines in _extract_leading_doc_comment (EXT-04).
        try:
            _source_lines: list[str] = source.decode("utf-8", errors="replace").splitlines()
        except Exception:
            _source_lines = []

        for base_key, name_nodes in definition_nodes.items():
            entity_type = _CAPTURE_ENTITY_MAP.get(base_key)
            if entity_type is None:
                continue

            for name_node in name_nodes:
                name = _node_text(name_node, source)
                if not name:
                    continue

                decl_node: Node = (
                    name_node.parent if name_node.parent is not None else name_node
                )

                metadata = self._collect_metadata_with_source(
                    base_key, decl_node, auxiliary_nodes, source, source_lines=_source_lines
                )
                signature = self._build_signature(
                    name, base_key, decl_node, auxiliary_nodes, source
                )

                if index_id:
                    metadata["bsg.index_id"] = index_id

                normalized_name = name
                if entity_type == EntityType.ENTRY_POINT:
                    raw_snippet_value = metadata.get("invocation_snippet")
                    raw_snippet = (
                        str(raw_snippet_value)
                        if isinstance(raw_snippet_value, str)
                        and raw_snippet_value.strip()
                        else name
                    )
                    if (
                        "__name__" in raw_snippet and "__main__" in raw_snippet
                    ) or name == "__name__":
                        normalized_name = "__main__"
                        metadata["invocation_snippet"] = raw_snippet

                # Decode with strict UTF-8, storing raw_bytes on error
                raw_bytes_slice = source[decl_node.start_byte:decl_node.end_byte]
                decoded_content, stored_raw_bytes = self._safe_decode(
                    raw_bytes_slice, filepath, context=f"entity {normalized_name}"
                )

                entity = Entity(
                    type=entity_type,
                    name=normalized_name,
                    file=filepath,
                    start_line=decl_node.start_point[0] + 1,
                    end_line=decl_node.end_point[0] + 1,
                    start_byte=decl_node.start_byte,
                    end_byte=decl_node.end_byte,
                    signature=signature,
                    metadata=metadata,
                    raw_content=decoded_content,
                    content_hash=compute_bytes_hash(raw_bytes_slice),
                    raw_bytes=stored_raw_bytes,
                    ast_node_type=decl_node.type,
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
    ) -> tuple[list[Entity], list[Relationship]]:
        """Build Relationship models from reference captures.

        Returns unresolved entities alongside relationships so callers can merge
        them into the main entity list.
        """
        relationships: list[Relationship] = []
        unresolved_entities: list[Entity] = []
        emitted: set[tuple[str, str, str]] = set()
        unresolved_emitted: set[str] = set()

        # Compute timestamp once per _build_relationships call rather than per
        # unresolved entity (EXT-08: avoids repeated datetime.now() in hot loop).
        now_ts = datetime.now(timezone.utc).isoformat()

        def _make_unresolved(
            ref_text: str, line: int, rel_type: RelationshipType
        ) -> Entity:
            meta: dict[str, Any] = {
                "reference_type": rel_type.name.lower(),
                "resolution_reason": "not_found",
                "attempts": 1,
                "created_at": now_ts,
                "last_attempt": now_ts,
                "is_visible": False,
            }
            return Entity(
                type=EntityType.UNRESOLVED,
                name=ref_text,
                file=filepath,
                start_line=line,
                end_line=line,
                metadata=meta,
            )

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
        # O(N) monotonic stack algorithm (EXT-02: replaces O(N²) backward scan).
        # Entities are assumed sorted by start_byte ascending, end_byte descending
        # (i.e. outer entities appear before inner ones at the same start).
        # Stack entries: Entity objects whose byte range is still "open".
        parent_stack: list[Entity] = []
        for child in entities:
            # Pop any entries that cannot contain this child.
            while parent_stack and parent_stack[-1].end_byte < child.start_byte:
                parent_stack.pop()
            if parent_stack and parent_stack[-1].id != child.id:
                parent = parent_stack[-1]
                _add(parent.id, child.id, RelationshipType.CONTAINS, child.start_line)
            # Only push if this entity can contain future entities.
            if not parent_stack or child.end_byte <= parent_stack[-1].end_byte:
                parent_stack.append(child)
            elif child.end_byte > parent_stack[-1].end_byte:
                # This entity is wider than the current top — replace (unusual,
                # happens when entities overlap rather than nest cleanly).
                parent_stack.pop()
                parent_stack.append(child)

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
                    if source_ent is None:
                        continue
                    source_id = source_ent.id
                    target_ent = by_name.get(ref_text)
                    if target_ent is not None and source_id != target_ent.id:
                        _add(source_id, target_ent.id, rel_type, line_no, rel_meta)
                    elif target_ent is None:
                        unres = _make_unresolved(ref_text, line_no, rel_type)
                        if unres.id not in unresolved_emitted:
                            unresolved_emitted.add(unres.id)
                            unresolved_entities.append(unres)
                        _add(source_id, unres.id, rel_type, line_no, rel_meta)

                elif rel_type == RelationshipType.IMPORTS:
                    source_ent = _find_enclosing(node.start_byte)
                    if source_ent is None:
                        continue
                    source_id = source_ent.id
                    targets = _expand_import_targets(ref_text)
                    if not targets:
                        continue

                    for target_ref in targets:
                        target_ent = by_name.get(target_ref)
                        if target_ent is not None and source_id != target_ent.id:
                            _add(source_id, target_ent.id, rel_type, line_no, rel_meta)
                        elif target_ent is None:
                            unres = _make_unresolved(target_ref, line_no, rel_type)
                            if unres.id not in unresolved_emitted:
                                unresolved_emitted.add(unres.id)
                                unresolved_entities.append(unres)
                            _add(source_id, unres.id, rel_type, line_no, rel_meta)
                            self.logger.debug(
                                "unresolved_import",
                                filepath=filepath,
                                ref=target_ref,
                            )

                elif rel_type in (
                    RelationshipType.INHERITS,
                    RelationshipType.IMPLEMENTS,
                ):
                    source_ent = _find_enclosing(node.start_byte)
                    if source_ent is None:
                        continue

                    target_ent = by_name.get(ref_text)
                    if target_ent is not None and source_ent.id != target_ent.id:
                        _add(source_ent.id, target_ent.id, rel_type, line_no, rel_meta)
                    elif target_ent is None:
                        normalized_ref = _normalize_import_target(ref_text)
                        if normalized_ref:
                            unres = _make_unresolved(normalized_ref, line_no, rel_type)
                            if unres.id not in unresolved_emitted:
                                unresolved_emitted.add(unres.id)
                                unresolved_entities.append(unres)
                            _add(
                                source_ent.id,
                                unres.id,
                                rel_type,
                                line_no,
                                rel_meta,
                            )

        return unresolved_entities, relationships

    # ------------------------------------------------------------------
    # Internal — metadata / signature helpers
    # ------------------------------------------------------------------

    def _collect_metadata_with_source(
        self,
        base_key: str,
        decl_node: Node,
        auxiliary_nodes: dict[tuple[str, str], list[Node]],
        source: bytes,
        source_lines: list[str] | None = None,
    ) -> EntityMetadata:
        """Collect full EntityMetadata including text fields that require source bytes.

        Args:
            base_key:       Capture base key (e.g. ``"def.function"``).
            decl_node:      tree-sitter declaration node.
            auxiliary_nodes: Parsed capture auxiliary map.
            source:         Raw file bytes.
            source_lines:   Pre-split lines, passed to avoid repeated
                            decode+splitlines in ``_extract_leading_doc_comment``.
        """
        metadata: EntityMetadata = {}
        metadata["language"] = self._language_name

        suffix_key_map: list[tuple[str, str]] = [
            ("visibility", "visibility"),
            ("invocation", "invocation_snippet"),
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
            fallback_doc = self._extract_leading_doc_comment(
                decl_node=decl_node, source=source, lines=source_lines
            )
            if fallback_doc:
                metadata["docstring"] = _clean_docstring(fallback_doc)

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

    def _extract_leading_doc_comment(
        self,
        decl_node: Node,
        source: bytes,
        lines: list[str] | None = None,
    ) -> str | None:
        """Extract contiguous comment lines immediately above a declaration.

        Args:
            decl_node: The tree-sitter Node for the declaration.
            source:    Raw source bytes (used only when *lines* is not provided).
            lines:     Pre-split text lines.  When provided, the *source* bytes
                       are NOT decoded, avoiding repeated O(n) decode+split per
                       entity call (EXT-04).
        """
        if lines is None:
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

    # ------------------------------------------------------------------
    # UTF-8 decoding helpers
    # ------------------------------------------------------------------

    def _safe_decode(
        self, raw_bytes: bytes, filepath: str, context: str = ""
    ) -> tuple[str, bytes | None]:
        """Decode bytes with strict UTF-8, falling back to replace mode on error.

        Args:
            raw_bytes: Bytes to decode.
            filepath: File path for error reporting.
            context: Additional context for error messages.

        Returns:
            Tuple of (decoded_string, raw_bytes_for_storage).
            raw_bytes_for_storage is None if strict decode succeeded,
            otherwise contains the original bytes for lossless reconstruction.

        Note:
            When UTF-8 decode fails, the returned decoded_string uses replacement
            characters () for invalid bytes. The raw_bytes field preserves the
            original bytes for truly lossless reconstruction during the bidirectional
            phase. This means raw_content may not round-trip perfectly, but raw_bytes
            ensures exact byte-level reconstruction.
        """
        try:
            decoded = raw_bytes.decode("utf-8", errors="strict")
            return decoded, None
        except UnicodeDecodeError as exc:
            self.logger.warning(
                "utf8_decode_fallback",
                filepath=filepath,
                context=context,
                error=str(exc),
                bytes_length=len(raw_bytes),
            )
            # Store raw bytes for lossless reconstruction
            decoded = raw_bytes.decode("utf-8", errors="replace")
            return decoded, raw_bytes

    # ------------------------------------------------------------------
    # Gap extraction (SYNTAX_GLUE entities)
    # ------------------------------------------------------------------

    _COMMENT_PREFIXES: set[str] = {"#", "//", "--", ";", "%", "(*", "/*"}

    def _classify_gap_type(self, raw: str) -> str:
        """Classify a gap's content into a category.

        Returns one of: ``whitespace``, ``comment``, ``import``, ``code``,
        ``separator``, ``partial_entity``.
        """
        stripped = raw.strip()
        if not stripped:
            return "whitespace"
        # Check for separator patterns first (before comment detection,
        # since some separators like --- start with comment prefix --)
        if re.match(r"^[=\-*]{3,}$", stripped):
            return "separator"
        # Check for comment prefixes
        first_line = stripped.split("\n")[0].strip()
        if any(first_line.startswith(p) for p in self._COMMENT_PREFIXES):
            return "comment"
        # Check for import statements
        if (
            first_line.startswith("import ")
            or first_line.startswith("from ")
            or first_line.startswith("#include")
            or first_line.startswith("use ")
            or first_line.startswith("require")
            or "import " in first_line[:20]
        ):
            return "import"
        # If the gap is between entities where one or both have partial coverage
        # this is a heuristic fallback. We don't have AST access here but can infer
        # from content that looks like code (not whitespace/comments)
        return "code"

    def _extract_gaps(
        self,
        content: bytes,
        filepath: str,
        entities: list[Entity],
    ) -> list[Entity]:
        """Emit SYNTAX_GLUE entities for every byte gap between semantic entities.

        Args:
            content: Raw source bytes.
            filepath: Repo-relative path for the entity ``file`` field.
            entities: Semantic entities already extracted (sorted by start_byte).

        Returns:
            List of SYNTAX_GLUE Entity models covering uncovered byte ranges.
        """
        if not content:
            return []

        file_size = len(content)
        gap_entities: list[Entity] = []

        # Merged intervals representing covered regions
        intervals = [(e.start_byte, e.end_byte) for e in entities]
        merged_intervals = []
        if intervals:
            # Sort by start_byte, then end_byte descending to process outer intervals first
            sorted_intervals = sorted(intervals, key=lambda x: (x[0], -x[1]))
            merged_intervals.append(sorted_intervals[0])
            for start, end in sorted_intervals[1:]:
                prev_start, prev_end = merged_intervals[-1]
                if start <= prev_end:
                    merged_intervals[-1] = (prev_start, max(prev_end, end))
                else:
                    merged_intervals.append((start, end))

        # Precompute line start byte offsets using a single regex scan of newlines
        line_starts = [0] + [m.start() + 1 for m in re.finditer(b"\n", content)]

        # Helper to decode raw bytes with strict UTF-8 fallback
        def _decode_slice(start: int, end: int) -> tuple[str, bytes | None]:
            raw_bytes_slice = content[start:end]
            decoded, stored_raw_bytes = self._safe_decode(
                raw_bytes_slice, filepath, context=f"gap {start}-{end}"
            )
            return decoded, stored_raw_bytes

        # Helper to compute line number from byte offset using fast binary search
        def _byte_to_line(offset: int) -> int:
            off = min(offset, file_size)
            return bisect.bisect_right(line_starts, off)

        def _add_gap(start: int, end: int) -> None:
            if start >= end:
                return
            raw, raw_bytes = _decode_slice(start, end)
            gap_entities.append(
                Entity(
                    type=EntityType.SYNTAX_GLUE,
                    name="<glue>",
                    file=filepath,
                    start_line=_byte_to_line(start),
                    end_line=_byte_to_line(end),
                    start_byte=start,
                    end_byte=end,
                    raw_content=raw,
                    content_hash=compute_bytes_hash(content[start:end]),
                    raw_bytes=raw_bytes,
                    metadata={
                        "language": self._language_name,
                        "gap_type": self._classify_gap_type(raw),
                        "is_empty": not raw.strip(),
                        "contains_comments": any(
                            p in raw for p in self._COMMENT_PREFIXES
                        ),
                    },
                )
            )

        if not merged_intervals:
            _add_gap(0, file_size)
        else:
            # Leading gap
            _add_gap(0, merged_intervals[0][0])
            # Inter-interval gaps
            for i in range(len(merged_intervals) - 1):
                _add_gap(merged_intervals[i][1], merged_intervals[i+1][0])
            # Trailing gap
            _add_gap(merged_intervals[-1][1], file_size)

        return gap_entities

    def _enrich_bidirectional_attributes(
        self,
        entities: list[Entity],
        content: bytes,
    ) -> list[Entity]:
        """Compute parent_id, children_order, leading_whitespace, and trailing_whitespace.

        Uses a single-pass algorithm to resolve containment hierarchy via a
        monotonic stack, then applies whitespace and relationship data in one
        final ``_evolve()`` call per entity — avoiding the previous 3×
        frozen-model reconstruction overhead.

        Args:
            entities: Extracted semantic entities (any order).
            content: Raw file content bytes.

        Returns:
            List of updated Entity objects, in original input order.
        """
        if not content or not entities:
            return entities

        content_len = len(content)
        ws_set = b" \t\n\r"

        # ------------------------------------------------------------------
        # Step 1: Whitespace resolution
        # Compute leading/trailing whitespace bytes for each non-GLUE entity.
        # Stored as a parallel list indexed by entity position in `entities`.
        # ------------------------------------------------------------------
        leading_list: list[str] = [""] * len(entities)
        trailing_list: list[str] = [""] * len(entities)
        semantic_indices: list[int] = []  # positions of non-GLUE entities

        # First pass: identify semantic entities
        for idx, e in enumerate(entities):
            if e.type != EntityType.SYNTAX_GLUE:
                semantic_indices.append(idx)

        # Precompute limits for leading whitespace
        leading_ws_bytes: list[bytes] = [b""] * len(entities)
        for idx in semantic_indices:
            e = entities[idx]
            limit_left = 0
            for other_idx in semantic_indices:
                other = entities[other_idx]
                if other.end_byte <= e.start_byte and other.end_byte > limit_left:
                    limit_left = other.end_byte
            
            i = e.start_byte - 1
            while i >= limit_left and content[i] in ws_set:
                i -= 1
            leading_bytes = content[i + 1:e.start_byte]
            leading_ws_bytes[idx] = leading_bytes
            leading_list[idx] = leading_bytes.decode("utf-8", errors="replace")

        # Second pass: compute trailing whitespace with limits to avoid double counting
        for idx in semantic_indices:
            e = entities[idx]
            # Find the min start of leading whitespace of any semantic entity starting at or after e.end_byte
            limit_right = content_len
            for other_idx in semantic_indices:
                other = entities[other_idx]
                if other.start_byte >= e.end_byte:
                    other_leading_start = other.start_byte - len(leading_ws_bytes[other_idx])
                    if other_leading_start < limit_right:
                        limit_right = other_leading_start
            
            j = e.end_byte
            while j < limit_right and content[j] in ws_set:
                j += 1
            trailing_list[idx] = content[e.end_byte:j].decode("utf-8", errors="replace")

        # ------------------------------------------------------------------
        # Step 2: Containment hierarchy via monotonic stack
        # Sort semantic entities by (start_byte ASC, end_byte DESC) so that
        # parent entities always precede their children.
        # ------------------------------------------------------------------
        # Map original index -> semantic order position for stack work
        sorted_sem = sorted(
            semantic_indices,
            key=lambda idx: (entities[idx].start_byte, -entities[idx].end_byte),
        )

        stack: list[int] = []  # indices into `entities`
        parent_map: dict[str, str] = {}   # child entity.id -> parent entity.id
        children_map: dict[str, list[str]] = {}  # parent entity.id -> [child ids]

        for idx in sorted_sem:
            e = entities[idx]
            # Pop stack until we find a true ancestor
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
        # Step 3: Single-pass final Entity construction via _evolve()
        # Each entity is evolved at most once, applying whitespace + hierarchy
        # together to avoid the previous 3× frozen-model reconstruction.
        # ------------------------------------------------------------------
        result: list[Entity] = []
        for idx, e in enumerate(entities):
            if e.type == EntityType.SYNTAX_GLUE:
                result.append(e)
                continue

            p_id = e.parent_id or parent_map.get(e.id)
            c_order = children_map.get(e.id, [])
            leading = leading_list[idx]
            trailing = trailing_list[idx]

            # Only evolve if any attribute actually changed to avoid unnecessary
            # model_copy() overhead on already-correct entities
            if (
                p_id != e.parent_id
                or c_order != list(e.children_order)
                or leading != e.leading_whitespace
                or trailing != e.trailing_whitespace
            ):
                e = e._evolve(
                    parent_id=p_id,
                    leading_whitespace=leading,
                    trailing_whitespace=trailing,
                    children_order=c_order,
                )
            result.append(e)

        return result


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

    def __init__(
        self, language: str, parsing_config: dict[str, Any] | None = None
    ) -> None:
        self._language_name = language
        self._ts_parser = None
        self._ts_language = None
        self._parsing_config: dict[str, Any] = parsing_config or {}
        self.logger = get_logger(__name__, operation="markup_extract").bind(
            language=language
        )

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
        index_id: str | None = None,
        include_gaps: bool = False,
    ) -> tuple[list[Entity], list[Relationship]]:
        """Parse a markup or configuration file."""
        t0 = time.perf_counter()

        try:
            entities = self._extract_elements(content, filepath)

            # Enrich extracted elements with raw content, content hash, and raw bytes sliced from content
            enriched_entities = []
            for entity in entities:
                raw_content = entity.raw_content
                content_hash = entity.content_hash
                raw_bytes = entity.raw_bytes

                if raw_content is None or not content_hash:
                    start_byte = min(max(0, entity.start_byte), len(content))
                    end_byte = min(max(start_byte, entity.end_byte), len(content))
                    raw_bytes_slice = content[start_byte:end_byte]

                    decoded_content, stored_raw_bytes = self._safe_decode(
                        raw_bytes_slice, filepath, context=f"markup entity {entity.name}"
                    )
                    c_hash = compute_bytes_hash(raw_bytes_slice)

                    if raw_content is None:
                        raw_content = decoded_content
                    if not content_hash:
                        content_hash = c_hash
                    if raw_bytes is None:
                        raw_bytes = stored_raw_bytes

                enriched_entity = Entity(
                    type=entity.type,
                    name=entity.name,
                    file=entity.file,
                    start_line=entity.start_line,
                    end_line=entity.end_line,
                    start_byte=entity.start_byte,
                    end_byte=entity.end_byte,
                    signature=entity.signature,
                    metadata=entity.metadata,
                    parent_id=entity.parent_id,
                    raw_content=raw_content,
                    content_hash=content_hash,
                    raw_bytes=raw_bytes,
                    leading_whitespace=entity.leading_whitespace,
                    trailing_whitespace=entity.trailing_whitespace,
                    ast_node_type=entity.ast_node_type,
                    children_order=entity.children_order,
                )
                enriched_entities.append(enriched_entity)
            entities = enriched_entities

            if index_id:
                stamped_entities = []
                for entity in entities:
                    metadata = dict(entity.metadata or {})
                    metadata["bsg.index_id"] = index_id
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
                        raw_content=entity.raw_content,
                        content_hash=entity.content_hash,
                        raw_bytes=entity.raw_bytes,
                        leading_whitespace=entity.leading_whitespace,
                        trailing_whitespace=entity.trailing_whitespace,
                        ast_node_type=entity.ast_node_type,
                        children_order=entity.children_order,
                    )
                    stamped_entities.append(stamped_entity)
                entities = stamped_entities
            entities = self._enrich_bidirectional_attributes(entities, content)
            relationships = self._extract_references(content, filepath, entities)
            entities.sort(key=lambda e: e.start_byte)

            if include_gaps and entities:
                gap_entities = self._extract_gaps(content, filepath, entities)
                entities.extend(gap_entities)
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
            include_gaps=include_gaps,
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
