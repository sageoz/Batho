"""
context/languages/css.py — CSS MarkupConfigExtractor subclass.

Extracts:
  - ELEMENT: CSS rules (selectors)
  - SETTING: CSS properties (key-value pairs)
  - ATTRIBUTE: Property values
  - Relationships: CONTAINS (rule → properties)

CSS structure:
  - Rules: selector { properties } → ELEMENT
  - Properties: property: value; → SETTING
  - At-rules: @media, @import, @keyframes → ELEMENT
  - Nested rules: SCSS/SASS style nested blocks
"""

from __future__ import annotations

import re
from typing import Any

from batho.modules.extraction.extractor import MarkupConfigExtractor
from batho.core.schemas import Entity, EntityType, Relationship, RelationshipType

# Precompiled regex patterns for performance
_RULE_PATTERN = re.compile(r"([^{}]+)\s*\{([^{}]*)\}", re.DOTALL)
_PROPERTY_PATTERN = re.compile(r"([a-zA-Z\-]+)\s*:\s*([^;]+);")
_PROPERTY_COUNT_PATTERN = re.compile(r"([a-zA-Z\-]+)\s*:")
_IMPORT_PATTERN = re.compile(
    r'@import\s+(?:url\()?["\']?([^"\')]+)["\']?\)?',
    re.IGNORECASE,
)


class CSSExtractor(MarkupConfigExtractor):
    """Extractor for CSS, SCSS, SASS, and LESS files."""

    def __init__(self, parsing_config: dict[str, Any] | None = None) -> None:
        super().__init__("css", parsing_config)

    def _extract_elements(
        self,
        source: bytes,
        filepath: str,
    ) -> list[Entity]:
        """Extract elements from CSS content."""
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

            # Track entities for relationship building
            self._rule_entities: dict[str, Entity] = {}

            # Parse CSS rules
            # Main pattern: selector { properties }
            for match in _RULE_PATTERN.finditer(content):
                selector = match.group(1).strip()
                properties = match.group(2).strip()

                if not selector:
                    continue

                start_byte = match.start()
                end_byte = match.end()
                start_line = get_line_from_offset(start_byte)
                end_line = get_line_from_offset(end_byte)

                # Determine rule type
                if selector.startswith("@"):
                    # At-rule: @media, @import, @keyframes, etc.
                    rule_type = "at-rule"
                    name = selector.split()[0] if " " in selector else selector
                else:
                    # Regular selector rule
                    rule_type = "rule"
                    name = selector.split(",")[0].strip()  # First selector

                # Create rule entity
                rule_entity = self._create_entity(
                    entity_type=EntityType.ELEMENT,
                    name=name,
                    filepath=filepath,
                    start_line=start_line,
                    end_line=end_line,
                    start_byte=start_byte,
                    end_byte=end_byte,
                    metadata={
                        "language": "css",
                        "rule_type": rule_type,
                        "selector": selector,
                        "property_count": self._count_properties(properties),
                    },
                )
                entities.append(rule_entity)
                self._rule_entities[f"{name}:{start_byte}"] = rule_entity

                # Extract properties within the rule
                if properties:
                    for prop_match in _PROPERTY_PATTERN.finditer(properties):
                        prop_name = prop_match.group(1).strip()
                        prop_value = prop_match.group(2).strip()

                        prop_start_byte = start_byte + prop_match.start()
                        prop_end_byte = start_byte + prop_match.end()
                        prop_start_line = get_line_from_offset(prop_start_byte)
                        prop_end_line = get_line_from_offset(prop_end_byte)

                        # Create property entity
                        prop_entity = self._create_entity(
                            entity_type=EntityType.SETTING,
                            name=f"{name}.{prop_name}",
                            filepath=filepath,
                            start_line=prop_start_line,
                            end_line=prop_end_line,
                            start_byte=prop_start_byte,
                            end_byte=prop_end_byte,
                            metadata={
                                "language": "css",
                                "property_name": prop_name,
                                "property_value": prop_value,
                            },
                        )
                        entities.append(prop_entity)

            # Document entity
            if entities:
                doc_entity = self._create_entity(
                    entity_type=EntityType.DOCUMENT,
                    name="document",
                    filepath=filepath,
                    start_line=1,
                    end_line=len(lines),
                    start_byte=0,
                    end_byte=len(source),
                    metadata={
                        "language": "css",
                        "rule_count": len(self._rule_entities),
                    },
                )
                entities.insert(0, doc_entity)

        except UnicodeDecodeError as e:
            self.logger.debug(
                "css_decode_error",
                filepath=filepath,
                error=str(e),
            )

        return entities

    def _count_properties(self, properties_block: str) -> int:
        """Count the number of properties in a CSS block."""
        if not properties_block:
            return 0
        # Count colons that are property declarations
        return len(_PROPERTY_COUNT_PATTERN.findall(properties_block))

    def _extract_references(
        self,
        source: bytes,
        filepath: str,
        entities: list[Entity],
    ) -> list[Relationship]:
        """Extract relationships from CSS content."""
        relationships: list[Relationship] = []

        try:
            content = source.decode("utf-8")

            # Build entity lookup
            elements = {e.name: e for e in entities if e.type == EntityType.ELEMENT}
            settings = {e.name: e for e in entities if e.type == EntityType.SETTING}
            documents = {e.name: e for e in entities if e.type == EntityType.DOCUMENT}
            doc = documents.get("document")

            # Create CONTAINS relationships
            # Document → Rules
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

            # Rule → Properties
            for setting in settings.values():
                # Parse rule name from property name
                parts = setting.name.rsplit(".", 1)
                if len(parts) == 2:
                    rule_name = parts[0]
                    rule = elements.get(rule_name)
                    if rule:
                        relationships.append(
                            self._create_relationship(
                                source_id=rule.id,
                                target_id=setting.id,
                                rel_type=RelationshipType.CONTAINS,
                                line=setting.start_line,
                            )
                        )

            # Extract @import references
            for match in _IMPORT_PATTERN.finditer(content):
                imported = match.group(1)
                line_no = content[: match.start()].count("\n") + 1
                if doc:
                    relationships.append(
                        self._create_relationship(
                            source_id=doc.id,
                            target_id=f"import:{imported}",
                            rel_type=RelationshipType.IMPORTS,
                            line=line_no,
                        )
                    )

        except UnicodeDecodeError:
            pass

        return relationships
