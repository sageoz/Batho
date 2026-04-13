"""
context/languages/html.py — HTML MarkupConfigExtractor subclass.

Extracts:
  - ELEMENT: HTML elements (tags)
  - ATTRIBUTE: Element attributes
  - SETTING: Text content within elements
  - Relationships: CONTAINS, HAS_ATTRIBUTE, LINKS_TO, IMPORTS_STYLE

HTML structure:
  - Tags: <tag> → ELEMENT
  - Attributes: name="value" → ATTRIBUTE
  - Links: <a href="..."> → LINKS_TO
  - Styles: <link rel="stylesheet"> → IMPORTS_STYLE
  - Scripts: <script src="..."> → IMPORTS (as relationship)
"""

from __future__ import annotations

import re
from typing import Any

from ..extractor import MarkupConfigExtractor
from ..schema import Entity, EntityType, Relationship, RelationshipType


class HTMLExtractor(MarkupConfigExtractor):
    """Extractor for HTML files."""

    def __init__(self, parsing_config: dict[str, Any] | None = None) -> None:
        super().__init__("html", parsing_config)

    def _extract_elements(
        self,
        source: bytes,
        filepath: str,
    ) -> list[Entity]:
        """Extract elements from HTML content."""
        entities: list[Entity] = []

        try:
            content = source.decode("utf-8")

            # Parse HTML tags using regex (lightweight approach)
            # Matches: <tag attr="value" ...>
            tag_pattern = re.compile(
                r"<([a-zA-Z][a-zA-Z0-9]*)"  # Tag name
                r"([^>]*)"  # Attributes
                r"(/?)>",  # Self-closing
                re.IGNORECASE,
            )

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

            # Track entity IDs for relationship building
            self._entity_ids: dict[str, Entity] = {}

            for match in tag_pattern.finditer(content):
                tag_name = match.group(1).lower()
                attrs_str = match.group(2)
                is_self_closing = match.group(3) == "/"

                start_byte = match.start()
                end_byte = match.end()
                start_line = get_line_from_offset(start_byte)
                end_line = get_line_from_offset(end_byte)

                # Parse attributes into dict
                element_attributes = {}
                if attrs_str:
                    attr_pattern = re.compile(
                        r"([a-zA-Z][a-zA-Z0-9\-:]*)"  # Attribute name
                        r'=(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))',  # Value
                    )

                    for attr_match in attr_pattern.finditer(attrs_str):
                        attr_name = attr_match.group(1).lower()
                        # Get the value (can be in quotes or unquoted)
                        attr_value = (
                            attr_match.group(2) or attr_match.group(3) or attr_match.group(4) or ""
                        )
                        element_attributes[attr_name] = attr_value

                # Create element entity with attributes in metadata
                element = self._create_entity(
                    entity_type=EntityType.ELEMENT,
                    name=tag_name,
                    filepath=filepath,
                    start_line=start_line,
                    end_line=end_line,
                    start_byte=start_byte,
                    end_byte=end_byte,
                    metadata={
                        "language": "html",
                        "tag_name": tag_name,
                        "self_closing": is_self_closing,
                        "attributes": element_attributes,
                    },
                )
                entities.append(element)
                self._entity_ids[f"{tag_name}:{start_byte}"] = element
                
                # DO NOT create separate ATTRIBUTE entities - stored in metadata

            # Also track the document itself
            doc_entity = self._create_entity(
                entity_type=EntityType.DOCUMENT,
                name="document",
                filepath=filepath,
                start_line=1,
                end_line=len(lines),
                start_byte=0,
                end_byte=len(source),
                metadata={
                    "language": "html",
                    "title": self._extract_title(content),
                },
            )
            entities.insert(0, doc_entity)

        except UnicodeDecodeError as e:
            self.logger.debug(
                "html_decode_error",
                filepath=filepath,
                error=str(e),
            )

        return entities

    def _extract_title(self, content: str) -> str | None:
        """Extract document title if present."""
        title_match = re.search(r"<title>([^<]*)</title>", content, re.IGNORECASE)
        if title_match:
            return title_match.group(1).strip()
        return None

    def _extract_references(
        self,
        source: bytes,
        filepath: str,
        entities: list[Entity],
    ) -> list[Relationship]:
        """Extract relationships from HTML content."""
        relationships: list[Relationship] = []

        try:
            content = source.decode("utf-8")

            # Build entity lookup
            elements = {e.name: e for e in entities if e.type == EntityType.ELEMENT}
            documents = {e.name: e for e in entities if e.type == EntityType.DOCUMENT}
            doc = documents.get("document")

            # No HAS_ATTRIBUTE relationships - attributes are in element metadata

            # Create CONTAINS relationships (document → elements)
            if doc:
                for element in [e for e in entities if e.type == EntityType.ELEMENT]:
                    relationships.append(
                        self._create_relationship(
                            source_id=doc.id,
                            target_id=element.id,
                            rel_type=RelationshipType.CONTAINS,
                            line=element.start_line,
                        )
                    )

            # Extract LINKS_TO relationships (anchor links)
            link_pattern = re.compile(
                r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>',
                re.IGNORECASE,
            )

            for match in link_pattern.finditer(content):
                href = match.group(1)
                if href.startswith(("http://", "https://", "//")):
                    # External link
                    line_no = content[: match.start()].count("\n") + 1
                    if doc:
                        relationships.append(
                            self._create_relationship(
                                source_id=doc.id,
                                target_id=f"external:{href}",
                                rel_type=RelationshipType.LINKS_TO,
                                line=line_no,
                            )
                        )

            # Extract IMPORTS_STYLE relationships (stylesheet links)
            style_pattern = re.compile(
                r'<link[^>]+rel=["\']stylesheet["\'][^>]+href=["\']([^"\']+)["\']',
                re.IGNORECASE,
            )

            for match in style_pattern.finditer(content):
                stylesheet = match.group(1)
                line_no = content[: match.start()].count("\n") + 1
                if doc:
                    relationships.append(
                        self._create_relationship(
                            source_id=doc.id,
                            target_id=f"stylesheet:{stylesheet}",
                            rel_type=RelationshipType.IMPORTS_STYLE,
                            line=line_no,
                        )
                    )

        except UnicodeDecodeError:
            pass

        return relationships
