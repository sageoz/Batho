"""
context/languages/json.py — JSON MarkupConfigExtractor subclass.

Extracts:
  - SETTING: Key-value pairs from JSON objects
  - SECTION: Nested objects/arrays as sections
  - Relationships: CONTAINS (nested structures)

JSON structure:
  - Objects: {} containing key-value pairs → SECTION
  - Arrays: [] containing values → SECTION (indexed)
  - Key-value pairs: "key": value → SETTING
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from batho.modules.extraction.extractor import MarkupConfigExtractor
from batho.core.schemas import Entity, EntityMetadata, EntityType, Relationship, RelationshipType


class JSONExtractor(MarkupConfigExtractor):
    """Extractor for JSON configuration files."""

    def __init__(self, parsing_config: dict[str, Any] | None = None) -> None:
        super().__init__("json", parsing_config)

    def _extract_elements(
        self,
        source: bytes,
        filepath: str,
    ) -> list[Entity]:
        """Extract elements from JSON content."""
        entities: list[Entity] = []

        try:
            # Try to decode as JSON
            content = source.decode("utf-8")
            lines = content.split("\n")
            data = json.loads(content)

            # Process the JSON structure
            self._process_value(
                data,
                filepath,
                "root",
                entities,
                0,  # start_line
                source,
            )

            if entities:
                section_count = len(
                    [e for e in entities if e.type == EntityType.SECTION]
                )
                setting_count = len(
                    [e for e in entities if e.type == EntityType.SETTING]
                )
                doc_entity = self._create_entity(
                    entity_type=EntityType.DOCUMENT,
                    name="document",
                    filepath=filepath,
                    start_line=1,
                    end_line=len(lines),
                    start_byte=0,
                    end_byte=len(source),
                    metadata={
                        "language": "json",
                        "section_count": section_count,
                        "setting_count": setting_count,
                    },
                )
                entities.insert(0, doc_entity)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self.logger.debug(
                "json_parse_error",
                filepath=filepath,
                error=str(e),
            )

        return entities

    def _process_value(
        self,
        value: Any,
        filepath: str,
        name: str,
        entities: list[Entity],
        line_offset: int,
        source: bytes,
        parent_path: str = "",
    ) -> None:
        """Recursively process JSON values into entities."""
        path = f"{parent_path}.{name}" if parent_path else name

        if isinstance(value, dict):
            # Object → SECTION
            entity = self._create_entity(
                entity_type=EntityType.SECTION,
                name=path,
                filepath=filepath,
                start_line=line_offset + 1,
                end_line=line_offset + 1,
                start_byte=0,
                end_byte=len(source),
                metadata={
                    "language": "json",
                    "value_type": "object",
                    "key_count": len(value),
                },
            )
            entities.append(entity)

            # Process each key-value pair
            for key, val in value.items():
                # Recurse into nested values
                self._process_value(
                    val,
                    filepath,
                    key,
                    entities,
                    line_offset,
                    source,
                    parent_path=path,
                )

        elif isinstance(value, list):
            # Array → SECTION with rollup
            # Serialize array contents
            serialized = json.dumps(value)
            if len(serialized) > 500:
                # Truncate and add hash
                truncated = serialized[:500]
                array_hash = hashlib.md5(serialized.encode()).hexdigest()[:8]
                content = f"{truncated}... (array[{len(value)}] truncated, hash: {array_hash})"
            else:
                content = serialized

            entity = self._create_entity(
                entity_type=EntityType.SECTION,
                name=path,
                filepath=filepath,
                start_line=line_offset + 1,
                end_line=line_offset + 1,
                start_byte=0,
                end_byte=len(source),
                metadata={
                    "language": "json",
                    "value_type": "array",
                    "item_count": len(value),
                    "array_contents": content,
                },
            )
            entities.append(entity)

            # DO NOT process individual array items - rollup complete
            return

        else:
            # Primitive value → SETTING
            entity = self._create_entity(
                entity_type=EntityType.SETTING,
                name=path,
                filepath=filepath,
                start_line=line_offset + 1,
                end_line=line_offset + 1,
                start_byte=0,
                end_byte=len(source),
                metadata={
                    "language": "json",
                    "value": self._serialize_value(value),
                },
            )
            entities.append(entity)

    def _serialize_value(self, value: Any) -> Any:
        """Serialize a JSON value for metadata storage."""
        if isinstance(value, (dict, list)):
            return f"<{type(value).__name__}>"
        return value

    def _extract_references(
        self,
        source: bytes,
        filepath: str,
        entities: list[Entity],
    ) -> list[Relationship]:
        """Extract relationships from JSON content."""
        relationships: list[Relationship] = []

        # Build lookup for sections
        sections = {e.name: e for e in entities if e.type == EntityType.SECTION}
        doc = next((e for e in entities if e.type == EntityType.DOCUMENT), None)

        if doc:
            for entity in entities:
                if (
                    entity.type in (EntityType.SECTION, EntityType.SETTING)
                    and "." not in entity.name
                ):
                    if entity.id != doc.id:
                        relationships.append(
                            self._create_relationship(
                                source_id=doc.id,
                                target_id=entity.id,
                                rel_type=RelationshipType.CONTAINS,
                                line=entity.start_line,
                                definition_start_byte=entity.start_byte,
                                definition_end_byte=entity.end_byte,
                            )
                        )

        # Create CONTAINS relationships
        # Child sections/settings are contained by parent sections
        for entity in entities:
            if entity.type in (EntityType.SECTION, EntityType.SETTING):
                # Find parent section
                parts = entity.name.split(".")
                if len(parts) > 1:
                    # Parent is everything except the last part
                    parent_path = ".".join(parts[:-1])
                    # Find exact match or closest parent
                    parent = sections.get(parent_path)
                    if parent is None:
                        # Try to find any ancestor
                        for i in range(len(parts) - 2, 0, -1):
                            potential_parent = ".".join(parts[:i])
                            if potential_parent in sections:
                                parent = sections[potential_parent]
                                break

                    if parent and parent.id != entity.id:
                        relationships.append(
                            self._create_relationship(
                                source_id=parent.id,
                                target_id=entity.id,
                                rel_type=RelationshipType.CONTAINS,
                                line=entity.start_line,
                                definition_start_byte=entity.start_byte,
                                definition_end_byte=entity.end_byte,
                            )
                        )

        return relationships
