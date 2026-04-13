from __future__ import annotations

from types import SimpleNamespace

import batho.context.languages.toml as toml_module
from batho.context.languages.toml import TOMLExtractor
from batho.context.schema import Entity, EntityType, Relationship, RelationshipType


class TestTOMLExtractor:

    def setup_method(self):
        self.extractor = TOMLExtractor.__new__(TOMLExtractor)
        self.extractor._language_name = "toml"
        self.extractor.logger = SimpleNamespace(debug=lambda *a, **k: None, warning=lambda *a, **k: None)

        def _create_entity(entity_type, name, filepath, start_line, end_line, start_byte, end_byte, metadata=None):
            return Entity(
                type=entity_type,
                name=name,
                file=filepath,
                start_line=start_line,
                end_line=end_line,
                start_byte=start_byte,
                end_byte=end_byte,
                metadata=metadata or {},
            )

        def _create_relationship(source_id, target_id, rel_type, line):
            return Relationship(
                source_id=source_id,
                target_id=target_id,
                type=rel_type,
                metadata={"line": line},
            )

        self.extractor._create_entity = _create_entity
        self.extractor._create_relationship = _create_relationship

    def test_extract_elements_and_relationships_for_nested_toml(self):
        source = b"""
[tool]
name = "batho"

[tool.section]
enabled = true
values = [1, 2]
"""
        entities = self.extractor._extract_elements(source, "pyproject.toml")
        assert entities

        docs = [e for e in entities if e.type == EntityType.DOCUMENT]
        sections = [e for e in entities if e.type == EntityType.SECTION]
        settings = [e for e in entities if e.type == EntityType.SETTING]

        assert len(docs) == 1
        assert len(sections) >= 2
        assert len(settings) >= 2

        rels = self.extractor._extract_references(source, "pyproject.toml", entities)
        contains = [r for r in rels if r.type == RelationshipType.CONTAINS]
        assert contains

    def test_extract_elements_handles_toml_unavailable(self, monkeypatch):
        monkeypatch.setattr(toml_module, "TOML_AVAILABLE", False)
        entities = self.extractor._extract_elements(b"a=1", "x.toml")
        assert entities == []

    def test_extract_elements_handles_parse_error_and_serialize_value(self):
        entities = self.extractor._extract_elements(b"= broken", "x.toml")
        assert entities == []

        assert self.extractor._serialize_value({"a": 1}) == "<dict>"
        assert self.extractor._serialize_value([1, 2]) == "<list>"
        assert self.extractor._serialize_value("ok") == "ok"

    def test_relationships_finds_ancestor_when_direct_parent_missing(self):
        doc = self.extractor._create_entity(
            EntityType.DOCUMENT,
            "document",
            "x.toml",
            1,
            1,
            0,
            1,
            {"language": "toml"},
        )
        root_section = self.extractor._create_entity(
            EntityType.SECTION,
            "root",
            "x.toml",
            1,
            1,
            0,
            1,
            {"language": "toml"},
        )
        deep_setting = self.extractor._create_entity(
            EntityType.SETTING,
            "root.missing.leaf",
            "x.toml",
            1,
            1,
            0,
            1,
            {"language": "toml"},
        )
        rels = self.extractor._extract_references(b"", "x.toml", [doc, root_section, deep_setting])
        contains = [r for r in rels if r.type == RelationshipType.CONTAINS]
        assert contains

    def test_toml_arrays_are_rolled_up_without_indexed_children(self):
        source = b"""
[tool]
values = [1, 2, 3]
"""
        entities = self.extractor._extract_elements(source, "pyproject.toml")

        array_sections = [
            e
            for e in entities
            if e.type == EntityType.SECTION and e.metadata.get("value_type") == "array"
        ]
        assert array_sections
        assert all("array_contents" in s.metadata for s in array_sections)
        assert all(s.metadata.get("item_count") == 3 for s in array_sections)

        indexed_children = [e for e in entities if ".[" in e.name]
        assert indexed_children == []
