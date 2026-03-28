"""
context/languages/toml.py — TOML MarkupConfigExtractor subclass.

Extracts:
  - SETTING: Key-value pairs from TOML
  - SECTION: Tables/arrays as sections
  - Relationships: CONTAINS (nested structures)

TOML structure:
  - Key-value pairs: key = value → SETTING
  - Tables: [section] → SECTION
  - Array of tables: [[section.sub]] → SECTION
"""

from __future__ import annotations

from typing import Any

from ..extractor import MarkupConfigExtractor
from ..schema import Entity, EntityType, Relationship, RelationshipType

try:
    import tomllib

    TOML_AVAILABLE = True
except ImportError:
    # Python < 3.11
    try:
        import tomli as tomllib

        TOML_AVAILABLE = True
    except ImportError:
        TOML_AVAILABLE = False


class TOMLExtractor(MarkupConfigExtractor):
    """Extractor for TOML configuration files."""

    def __init__(self) -> None:
        super().__init__("toml")

    def _extract_elements(
        self,
        source: bytes,
        filepath: str,
    ) -> list[Entity]:
        """Extract elements from TOML content."""
        if not TOML_AVAILABLE:
            self.logger.warning(
                "toml_library_not_available",
                filepath=filepath,
            )
            return []

        entities: list[Entity] = []

        try:
            content = source.decode("utf-8")
            lines = content.split("\n")
            data = tomllib.loads(content)

            # Process the TOML structure
            self._process_value(
                data,
                filepath,
                "root",
                entities,
                0,
                source,
            )

            if entities:
                section_count = len([e for e in entities if e.type == EntityType.SECTION])
                setting_count = len([e for e in entities if e.type == EntityType.SETTING])
                doc_entity = self._create_entity(
                    entity_type=EntityType.DOCUMENT,
                    name="document",
                    filepath=filepath,
                    start_line=1,
                    end_line=len(lines),
                    start_byte=0,
                    end_byte=len(source),
                    metadata={
                        "language": "toml",
                        "section_count": section_count,
                        "setting_count": setting_count,
                    },
                )
                entities.insert(0, doc_entity)

        except Exception as e:
            self.logger.debug(
                "toml_parse_error",
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
        """Recursively process TOML values into entities."""
        path = f"{parent_path}.{name}" if parent_path else name

        if isinstance(value, dict):
            # Table → SECTION
            entity = self._create_entity(
                entity_type=EntityType.SECTION,
                name=path,
                filepath=filepath,
                start_line=line_offset + 1,
                end_line=line_offset + 1,
                start_byte=0,
                end_byte=len(source),
                metadata={
                    "language": "toml",
                    "value_type": "table",
                    "key_count": len(value),
                },
            )
            entities.append(entity)

            # Process each key-value pair
            for key, val in value.items():
                if not isinstance(key, str):
                    key = str(key)

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
            # Array → SECTION
            entity = self._create_entity(
                entity_type=EntityType.SECTION,
                name=path,
                filepath=filepath,
                start_line=line_offset + 1,
                end_line=line_offset + 1,
                start_byte=0,
                end_byte=len(source),
                metadata={
                    "language": "toml",
                    "value_type": "array",
                    "item_count": len(value),
                },
            )
            entities.append(entity)

            # Process each item
            for i, item in enumerate(value):
                self._process_value(
                    item,
                    filepath,
                    f"[{i}]",
                    entities,
                    line_offset,
                    source,
                    parent_path=path,
                )

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
                    "language": "toml",
                    "value": self._serialize_value(value),
                },
            )
            entities.append(entity)

    def _serialize_value(self, value: Any) -> Any:
        """Serialize a TOML value for metadata storage."""
        if isinstance(value, (dict, list)):
            return f"<{type(value).__name__}>"
        return value

    def _extract_references(
        self,
        source: bytes,
        filepath: str,
        entities: list[Entity],
    ) -> list[Relationship]:
        """Extract relationships from TOML content."""
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
                            )
                        )

        # Create CONTAINS relationships
        for entity in entities:
            if entity.type in (EntityType.SECTION, EntityType.SETTING):
                # Find parent section
                parts = entity.name.split(".")
                if len(parts) > 1:
                    parent_path = ".".join(parts[:-1])
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
                            )
                        )

        return relationships
