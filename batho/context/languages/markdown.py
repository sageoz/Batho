"""
context/languages/markdown.py — Markdown MarkupConfigExtractor subclass.

Extracts:
  - DOCUMENT: The document itself
  - ELEMENT: Headers, code blocks, lists, tables
  - SETTING: Key-value pairs in frontmatter (YAML)
  - Relationships: CONTAINS, LINKS_TO

Markdown structure:
  - Headers: # H1, ## H2, etc. → ELEMENT
  - Code blocks: ```lang → ELEMENT
  - Links: [text](url) → LINKS_TO
  - Frontmatter: --- yaml --- → SETTING
"""

from __future__ import annotations

import re
from typing import Any

from ..extractor import MarkupConfigExtractor
from ..schema import Entity, EntityType, Relationship, RelationshipType

# Precompiled regex patterns for performance
_HEADER_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_CODE_BLOCK_PATTERN = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)
_LIST_PATTERN = re.compile(r"^(\s*[-*+]\s+|\s*\d+\.\s+)(.+)$", re.MULTILINE)
_TABLE_PATTERN = re.compile(
    r"^\|(.+)\|\n\|[-:\s|]+\|\n((?:\|.+\|\n?)+)",
    re.MULTILINE,
)
_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


class MarkdownExtractor(MarkupConfigExtractor):
    """Extractor for Markdown files."""

    def __init__(self, parsing_config: dict[str, Any] | None = None) -> None:
        super().__init__("markdown", parsing_config)

    def _extract_elements(
        self,
        source: bytes,
        filepath: str,
    ) -> list[Entity]:
        """Extract elements from Markdown content."""
        entities: list[Entity] = []

        try:
            content = source.decode("utf-8")

            # Track line positions
            lines = content.split("\n")
            line_offsets = [0]
            for line in lines:
                line_offsets.append(line_offsets[-1] + len(line) + 1)

            def get_line_from_offset(offset: int) -> int:
                """Find line number from byte offset."""
                for i, o in enumerate(line_offsets):
                    if o > offset:
                        return i
                return len(lines)

            # Extract frontmatter (YAML between ---)
            frontmatter = self._extract_frontmatter(content)
            if frontmatter:
                frontmatter_entity = self._create_entity(
                    entity_type=EntityType.SETTING,
                    name="frontmatter",
                    filepath=filepath,
                    start_line=1,
                    end_line=frontmatter["end_line"],
                    start_byte=0,
                    end_byte=frontmatter["end_byte"],
                    metadata={
                        "language": "markdown",
                        "frontmatter_keys": list(frontmatter["data"].keys()),
                    },
                )
                entities.append(frontmatter_entity)

            # Track headers for hierarchy and content rollup
            headers: list[tuple[int, str, int, int, Entity]] = []
            content_buffer: dict[str, list[str]] = {}  # entity_id -> content pieces

            # Extract headers (# H1, ## H2, etc.)
            for match in _HEADER_PATTERN.finditer(content):
                level = len(match.group(1))
                text = match.group(2).strip()

                start_byte = match.start()
                end_byte = match.end()
                start_line = get_line_from_offset(start_byte)
                end_line = get_line_from_offset(end_byte)

                # Create header element
                header_entity = self._create_entity(
                    entity_type=EntityType.ELEMENT,
                    name=f"header_{level}_{text}",
                    filepath=filepath,
                    start_line=start_line,
                    end_line=end_line,
                    start_byte=start_byte,
                    end_byte=end_byte,
                    metadata={
                        "language": "markdown",
                        "header_level": level,
                        "header_text": text,
                    },
                )
                entities.append(header_entity)
                headers.append((level, text, start_line, end_line, header_entity))
                content_buffer[header_entity.id] = []

            # Extract code blocks
            for match in _CODE_BLOCK_PATTERN.finditer(content):
                lang = match.group(1) or "text"
                code = match.group(2).strip()

                start_byte = match.start()
                end_byte = match.end()
                start_line = get_line_from_offset(start_byte)
                end_line = get_line_from_offset(end_byte)

                code_entity = self._create_entity(
                    entity_type=EntityType.ELEMENT,
                    name=f"codeblock_{lang}",
                    filepath=filepath,
                    start_line=start_line,
                    end_line=end_line,
                    start_byte=start_byte,
                    end_byte=end_byte,
                    metadata={
                        "language": "markdown",
                        "code_language": lang,
                        "code_length": len(code),
                    },
                )
                entities.append(code_entity)

            # Roll up lists into parent headers (no individual list item nodes)
            for match in _LIST_PATTERN.finditer(content):
                text = match.group(2).strip()
                start_line = get_line_from_offset(match.start())

                # Find nearest parent header
                parent_header = None
                for level, htext, hstart, hend, hentity in reversed(headers):
                    if hstart < start_line:
                        parent_header = hentity
                        break

                # Roll up content to parent header or document
                if parent_header and parent_header.id in content_buffer:
                    content_buffer[parent_header.id].append(f"- {text}")
                # If no header, we'll attach to document later

            # Extract tables
            for match in _TABLE_PATTERN.finditer(content):
                header = match.group(1)
                rows = match.group(2)

                start_byte = match.start()
                end_byte = match.end()
                start_line = get_line_from_offset(start_byte)
                end_line = get_line_from_offset(end_byte)

                # Count columns and rows
                cols = len([c for c in header.split("|") if c.strip()])
                row_count = len([r for r in rows.split("\n") if r.strip()])

                table_entity = self._create_entity(
                    entity_type=EntityType.ELEMENT,
                    name="table",
                    filepath=filepath,
                    start_line=start_line,
                    end_line=end_line,
                    start_byte=start_byte,
                    end_byte=end_byte,
                    metadata={
                        "language": "markdown",
                        "table_columns": cols,
                        "table_rows": row_count,
                    },
                )
                entities.append(table_entity)

            # Attach rolled-up content to headers
            for entity in entities:
                if entity.id in content_buffer and content_buffer[entity.id]:
                    # Update entity metadata with content_rollup
                    updated_metadata = dict(entity.metadata or {})
                    updated_metadata["content_rollup"] = "\n".join(
                        content_buffer[entity.id]
                    )
                    # Replace entity in list with updated version
                    idx = entities.index(entity)
                    entities[idx] = entity.model_copy(
                        update={"metadata": updated_metadata}
                    )

            # Document entity
            doc_entity = self._create_entity(
                entity_type=EntityType.DOCUMENT,
                name="document",
                filepath=filepath,
                start_line=1,
                end_line=len(lines),
                start_byte=0,
                end_byte=len(source),
                metadata={
                    "language": "markdown",
                    "title": headers[0][1] if headers else None,
                    "header_count": len(headers),
                    "has_frontmatter": bool(frontmatter),
                },
            )
            entities.insert(0, doc_entity)

        except UnicodeDecodeError as e:
            self.logger.debug(
                "markdown_decode_error",
                filepath=filepath,
                error=str(e),
            )

        return entities

    def _extract_frontmatter(self, content: str) -> dict[str, Any] | None:
        """Extract YAML frontmatter from markdown content."""
        # Check for frontmatter delimiter at start
        if not content.startswith("---"):
            return None

        # Find closing ---
        end_match = re.search(r"\n---", content[3:])
        if not end_match:
            return None

        end_line = content[: 3 + end_match.end()].count("\n")
        end_byte = 3 + end_match.end()
        yaml_content = content[3 : end_match.start()].strip()

        # Parse simple YAML key-value pairs
        data: dict[str, str] = {}
        for line in yaml_content.split("\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                data[key.strip()] = value.strip()

        return {
            "data": data,
            "end_line": end_line,
            "end_byte": end_byte,
        }

    def _extract_references(
        self,
        source: bytes,
        filepath: str,
        entities: list[Entity],
    ) -> list[Relationship]:
        """Extract relationships from Markdown content."""
        relationships: list[Relationship] = []

        try:
            content = source.decode("utf-8")

            # Build entity lookup
            elements = {e.name: e for e in entities if e.type == EntityType.ELEMENT}
            settings = {e.name: e for e in entities if e.type == EntityType.SETTING}
            documents = {e.name: e for e in entities if e.type == EntityType.DOCUMENT}
            doc = documents.get("document")

            # Create CONTAINS relationships
            # Document → all elements
            if doc:
                for element in elements.values():
                    relationships.append(
                        self._create_relationship(
                            source_id=doc.id,
                            target_id=element.id,
                            rel_type=RelationshipType.CONTAINS,
                            line=element.start_line,
                        )
                    )

            # Extract links: [text](url)
            for match in _LINK_PATTERN.finditer(content):
                text = match.group(1)
                url = match.group(2)
                line_no = content[: match.start()].count("\n") + 1

                if url.startswith(("http://", "https://", "//")):
                    # External link
                    if doc:
                        relationships.append(
                            self._create_relationship(
                                source_id=doc.id,
                                target_id=f"external:{url}",
                                rel_type=RelationshipType.LINKS_TO,
                                line=line_no,
                            )
                        )
                elif url.startswith("#"):
                    # Internal anchor link
                    anchor = url[1:]
                    relationships.append(
                        self._create_relationship(
                            source_id=doc.id if doc else "document",
                            target_id=f"anchor:{anchor}",
                            rel_type=RelationshipType.LINKS_TO,
                            line=line_no,
                        )
                    )
                else:
                    # Local file reference
                    if doc:
                        relationships.append(
                            self._create_relationship(
                                source_id=doc.id,
                                target_id=f"file:{url}",
                                rel_type=RelationshipType.LINKS_TO,
                                line=line_no,
                            )
                        )

            # Extract image references: ![alt](url)
            for match in _IMAGE_PATTERN.finditer(content):
                alt = match.group(1)
                url = match.group(2)
                line_no = content[: match.start()].count("\n") + 1

                if doc:
                    relationships.append(
                        self._create_relationship(
                            source_id=doc.id,
                            target_id=f"image:{url}",
                            rel_type=RelationshipType.LINKS_TO,
                            line=line_no,
                        )
                    )

        except UnicodeDecodeError:
            pass

        return relationships
