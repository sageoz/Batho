from __future__ import annotations

from types import SimpleNamespace

from batho.context.languages.json import JSONExtractor
from batho.context.schema import Entity, EntityType, Relationship


class TestJSONExtractor:

    def setup_method(self):
        self.extractor = JSONExtractor.__new__(JSONExtractor)
        self.extractor._language_name = "json"
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

    def test_json_arrays_are_rolled_up_without_indexed_children(self):
        source = b'{"files": [{"name": "a"}, {"name": "b"}], "tags": ["x", "y"]}'
        entities = self.extractor._extract_elements(source, "sample.json")

        array_sections = [
            e
            for e in entities
            if e.type == EntityType.SECTION and e.metadata.get("value_type") == "array"
        ]
        assert array_sections
        assert all("array_contents" in section.metadata for section in array_sections)
        assert all("item_count" in section.metadata for section in array_sections)

        indexed_children = [e for e in entities if ".[" in e.name]
        assert indexed_children == []

    def test_json_array_rollup_truncates_large_payload(self):
        large_values = [f"value_{i}" for i in range(200)]
        import json

        source = json.dumps({"big": large_values}).encode("utf-8")
        entities = self.extractor._extract_elements(source, "large.json")

        big_array = next(
            e
            for e in entities
            if e.type == EntityType.SECTION and e.name.endswith(".big")
        )
        payload = str(big_array.metadata.get("array_contents", ""))
        assert "truncated" in payload
        assert "hash:" in payload
