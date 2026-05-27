"""
context/languages/yaml.py — YAML MarkupConfigExtractor subclass.

Extracts:
  - SETTING: Key-value pairs from YAML
  - SECTION: Nested mappings/sequences as sections
  - Relationships: CONTAINS (nested structures)

YAML structure:
  - Mappings: {key: value} → SECTION + SETTING
  - Sequences: [item1, item2] → SECTION
  - Documents: --- separated documents → DOCUMENT + SECTION
"""

from __future__ import annotations

import hashlib
from typing import Any

from batho.modules.extraction.extractor import MarkupConfigExtractor
from batho.core.schemas import Entity, EntityType, Relationship, RelationshipType

try:
    import yaml

    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


class YAMLExtractor(MarkupConfigExtractor):
    """Extractor for YAML configuration files."""

    def __init__(self, parsing_config: dict[str, Any] | None = None) -> None:
        super().__init__("yaml", parsing_config)

    def _extract_elements(
        self,
        source: bytes,
        filepath: str,
    ) -> list[Entity]:
        """Extract elements from YAML content."""
        if not YAML_AVAILABLE:
            self.logger.warning(
                "yaml_library_not_available",
                filepath=filepath,
            )
            return []

        entities: list[Entity] = []

        try:
            content = source.decode("utf-8")
            lines = content.split("\n")

            # Use safe_load for security
            data = yaml.safe_load(content)

            if data is None:
                return entities

            # Handle multiple documents
            if isinstance(data, list):
                # Multiple documents
                doc_count = len(data)
                for i, doc in enumerate(data):
                    doc_name = f"document_{i}"
                    self._process_value(
                        doc,
                        filepath,
                        doc_name,
                        entities,
                        0,
                        source,
                    )
            else:
                # Single document
                doc_count = 1
                self._process_value(
                    data,
                    filepath,
                    "root",
                    entities,
                    0,
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
                        "language": "yaml",
                        "document_count": doc_count,
                        "section_count": section_count,
                        "setting_count": setting_count,
                    },
                )
                entities.insert(0, doc_entity)

        except yaml.YAMLError as e:
            self.logger.debug(
                "yaml_parse_error",
                filepath=filepath,
                error=str(e),
            )
        except UnicodeDecodeError as e:
            self.logger.debug(
                "yaml_decode_error",
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
        """Recursively process YAML values into entities."""
        path = f"{parent_path}.{name}" if parent_path else name

        if isinstance(value, dict):
            # Mapping → SECTION
            entity = self._create_entity(
                entity_type=EntityType.SECTION,
                name=path,
                filepath=filepath,
                start_line=line_offset + 1,
                end_line=line_offset + 1,
                start_byte=0,
                end_byte=len(source),
                metadata={
                    "language": "yaml",
                    "value_type": "mapping",
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
            # Sequence → SECTION with rollup
            # Serialize sequence contents
            serialized = yaml.dump(value, default_flow_style=True).strip()
            if len(serialized) > 500:
                # Truncate and add hash
                truncated = serialized[:500]
                array_hash = hashlib.md5(serialized.encode()).hexdigest()[:8]
                content = f"{truncated}... (sequence[{len(value)}] truncated, hash: {array_hash})"
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
                    "language": "yaml",
                    "value_type": "sequence",
                    "item_count": len(value),
                    "array_contents": content,
                },
            )
            entities.append(entity)

            # DO NOT process individual sequence items - rollup complete
            return

        else:
            # Scalar → SETTING
            entity = self._create_entity(
                entity_type=EntityType.SETTING,
                name=path,
                filepath=filepath,
                start_line=line_offset + 1,
                end_line=line_offset + 1,
                start_byte=0,
                end_byte=len(source),
                metadata={
                    "language": "yaml",
                    "value": self._serialize_value(value),
                },
            )
            entities.append(entity)

    def _serialize_value(self, value: Any) -> Any:
        """Serialize a YAML value for metadata storage."""
        if isinstance(value, (dict, list)):
            return f"<{type(value).__name__}>"
        return value

    def _extract_references(
        self,
        source: bytes,
        filepath: str,
        entities: list[Entity],
    ) -> list[Relationship]:
        """Extract relationships from YAML content."""
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
