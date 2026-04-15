"""
context/languages/hcl.py — HCL (Terraform) MarkupConfigExtractor subclass.

Extracts:
  - SETTING: Key-value pairs in HCL
  - SECTION: Blocks (resource, variable, output, etc.)
  - Relationships: CONTAINS (blocks contain settings)

HCL/Terraform structure:
  - Blocks: resource "type" "name" { } → SECTION
  - Attributes: key = value → SETTING
  - Nested blocks: → SECTION
"""

from __future__ import annotations

import re
from typing import Any

from ..extractor import MarkupConfigExtractor
from ..schema import Entity, EntityType, Relationship, RelationshipType


class HCLExtractor(MarkupConfigExtractor):
    """Extractor for HCL and Terraform files."""

    def __init__(self, parsing_config: dict[str, Any] | None = None) -> None:
        super().__init__("hcl", parsing_config)

    def _extract_elements(
        self,
        source: bytes,
        filepath: str,
    ) -> list[Entity]:
        """Extract elements from HCL content."""
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
            self._block_entities: dict[str, Entity] = {}

            # Parse HCL blocks
            # Pattern: block_type "label1" "label2" { ... }
            block_pattern = re.compile(
                r'([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:"([^"]*)"\s*)*(?:"([^"]*)"\s*)?\{',
            )

            # Track brace positions for proper parsing
            brace_positions = []
            in_string = False
            escape_next = False

            for i, char in enumerate(content):
                if escape_next:
                    escape_next = False
                    continue
                if char == "\\":
                    escape_next = True
                    continue
                if char == '"':
                    in_string = not in_string
                if not in_string:
                    if char == "{":
                        brace_positions.append(("open", i))
                    elif char == "}":
                        brace_positions.append(("close", i))

            # Find all blocks and their content
            for match in block_pattern.finditer(content):
                block_type = match.group(1)
                label1 = match.group(2) or ""
                label2 = match.group(3) or ""

                start_byte = match.start()
                end_byte = self._find_block_end(
                    content, start_byte + match.end() - 1, brace_positions
                )
                start_line = get_line_from_offset(start_byte)
                end_line = get_line_from_offset(end_byte)

                # Build block name
                if label1 and label2:
                    block_name = f"{block_type}.{label1}.{label2}"
                elif label1:
                    block_name = f"{block_type}.{label1}"
                else:
                    block_name = block_type

                # Extract block content
                block_content = content[match.end() : end_byte]

                # Create block entity
                block_entity = self._create_entity(
                    entity_type=EntityType.SECTION,
                    name=block_name,
                    filepath=filepath,
                    start_line=start_line,
                    end_line=end_line,
                    start_byte=start_byte,
                    end_byte=end_byte,
                    metadata={
                        "language": "hcl",
                        "block_type": block_type,
                        "label1": label1,
                        "label2": label2,
                    },
                )
                entities.append(block_entity)
                self._block_entities[f"{block_name}:{start_byte}"] = block_entity

                # Extract attributes within the block
                self._extract_attributes(
                    block_content,
                    filepath,
                    block_name,
                    entities,
                    start_line,
                    content,
                    get_line_from_offset,
                )

            # Also extract top-level attributes (not inside blocks)
            self._extract_attributes(
                content,
                filepath,
                "root",
                entities,
                0,
                get_line_from_offset,
                exclude_blocks=True,
            )

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
                        "language": "hcl",
                        "block_count": len(self._block_entities),
                    },
                )
                entities.insert(0, doc_entity)

        except UnicodeDecodeError as e:
            self.logger.debug(
                "hcl_decode_error",
                filepath=filepath,
                error=str(e),
            )

        return entities

    def _find_block_end(
        self, content: str, start_pos: int, brace_positions: list
    ) -> int:
        """Find the matching closing brace for a block."""
        depth = 1
        for pos_type, pos in brace_positions:
            if pos < start_pos:
                continue
            if pos_type == "open":
                depth += 1
            elif pos_type == "close":
                depth -= 1
                if depth == 0:
                    return pos
        return len(content)

    def _extract_attributes(
        self,
        content: str,
        filepath: str,
        parent_path: str,
        entities: list[Entity],
        line_offset: int,
        get_line_from_offset: Any,
        exclude_blocks: bool = False,
    ) -> None:
        """Extract key-value attributes from HCL content."""
        # Attribute pattern: key = value
        attr_pattern = re.compile(
            r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(.+)$",
            re.MULTILINE,
        )

        for match in attr_pattern.finditer(content):
            key = match.group(1)
            value = match.group(2).strip()

            # Skip if value looks like a block start
            if exclude_blocks and "{" in value:
                continue

            start_byte = match.start()
            end_byte = match.end()
            start_line = get_line_from_offset(
                line_offset + content[:start_byte].count("\n")
            )

            attr_path = f"{parent_path}.{key}" if parent_path != "root" else key

            # Create attribute entity
            attr_entity = self._create_entity(
                entity_type=EntityType.SETTING,
                name=attr_path,
                filepath=filepath,
                start_line=start_line,
                end_line=start_line,
                start_byte=start_byte,
                end_byte=end_byte,
                metadata={
                    "language": "hcl",
                    "key": key,
                    "value": value[:100],  # Truncate for metadata
                },
            )
            entities.append(attr_entity)

    def _extract_references(
        self,
        source: bytes,
        filepath: str,
        entities: list[Entity],
    ) -> list[Relationship]:
        """Extract relationships from HCL content."""
        relationships: list[Relationship] = []

        try:
            content = source.decode("utf-8")

            # Build entity lookup
            sections = {e.name: e for e in entities if e.type == EntityType.SECTION}
            settings = {e.name: e for e in entities if e.type == EntityType.SETTING}
            documents = {e.name: e for e in entities if e.type == EntityType.DOCUMENT}
            doc = documents.get("document")

            # Create CONTAINS relationships
            # Document → Blocks
            if doc:
                for section in sections.values():
                    relationships.append(
                        self._create_relationship(
                            source_id=doc.id,
                            target_id=section.id,
                            rel_type=RelationshipType.CONTAINS,
                            line=section.start_line,
                        )
                    )

            # Blocks → Settings
            for setting in settings:
                # Parse parent from setting name
                parts = setting.name.rsplit(".", 1)
                if len(parts) == 2:
                    parent_name = parts[0]
                    # Check if parent is a section
                    parent = sections.get(parent_name)
                    if parent:
                        relationships.append(
                            self._create_relationship(
                                source_id=parent.id,
                                target_id=setting.id,
                                rel_type=RelationshipType.CONTAINS,
                                line=setting.start_line,
                            )
                        )
                    elif doc and parent_name != "root":
                        # Top-level setting in document
                        relationships.append(
                            self._create_relationship(
                                source_id=doc.id,
                                target_id=setting.id,
                                rel_type=RelationshipType.CONTAINS,
                                line=setting.start_line,
                            )
                        )

            # Extract references to other resources
            # resource "type" "name"
            ref_pattern = re.compile(
                r'resource\s+"([^"]+)"\s+"([^"]+)"',
            )

            for match in ref_pattern.finditer(content):
                ref_type = match.group(1)
                ref_name = match.group(2)
                line_no = content[: match.start()].count("\n") + 1

                if doc:
                    relationships.append(
                        self._create_relationship(
                            source_id=doc.id,
                            target_id=f"resource:{ref_type}.{ref_name}",
                            rel_type=RelationshipType.REFERENCES,
                            line=line_no,
                        )
                    )

            # Extract variable references: var.name
            var_ref_pattern = re.compile(r"var\.([a-zA-Z_][a-zA-Z0-9_]*)")

            for match in var_ref_pattern.finditer(content):
                var_name = match.group(1)
                line_no = content[: match.start()].count("\n") + 1

                if doc:
                    relationships.append(
                        self._create_relationship(
                            source_id=doc.id,
                            target_id=f"variable:{var_name}",
                            rel_type=RelationshipType.USES,
                            line=line_no,
                        )
                    )

            # Extract module references
            module_ref_pattern = re.compile(r"module\.\w+")

            for match in module_ref_pattern.finditer(content):
                module_ref = match.group(0)
                line_no = content[: match.start()].count("\n") + 1

                if doc:
                    relationships.append(
                        self._create_relationship(
                            source_id=doc.id,
                            target_id=module_ref,
                            rel_type=RelationshipType.REFERENCES,
                            line=line_no,
                        )
                    )

        except UnicodeDecodeError:
            pass

        return relationships
