"""Tests for batho.core.schemas Entity/Relationship deserialization."""

from __future__ import annotations

from batho.core.schemas import Entity, EntityType


class TestEntityFromDict:
    """BUG-08: Serialized ID must be preserved unconditionally when non-None."""

    def test_from_dict_preserves_regular_id(self):
        """Verify that a regular serialized entity ID is preserved during deserialization.

        Scenario:
            A valid entity dict with a standard compound ID string is passed to Entity.from_dict.
            The resulting entity must retain that exact ID.

        Execution Flow:
            1. Construct an entity dict with a standard compound ID.
            2. Call Entity.from_dict.
            3. Assert both id_override and id match the original serialized value.

        Expectations:
            - Non-None serialized IDs are unconditionally preserved.
        """
        data = {
            "id": "ent|FUNCTION|foo.py|0|10|1|1|bar",
            "type": "function",
            "name": "bar",
            "file": "foo.py",
            "start_line": 1,
            "end_line": 1,
            "start_byte": 0,
            "end_byte": 10,
        }
        entity = Entity.from_dict(data)
        assert entity.id_override == "ent|FUNCTION|foo.py|0|10|1|1|bar"
        assert entity.id == "ent|FUNCTION|foo.py|0|10|1|1|bar"

    def test_from_dict_preserves_empty_string_id(self):
        """Empty-string IDs are non-None and must be preserved."""
        data = {
            "id": "",
            "type": "function",
            "name": "bar",
            "file": "foo.py",
            "start_line": 1,
            "end_line": 1,
            "start_byte": 0,
            "end_byte": 10,
        }
        entity = Entity.from_dict(data)
        assert entity.id_override == ""
        assert entity.id == ""

    def test_from_dict_preserves_unresolved_stub_id(self):
        """Unresolved stubs often have opaque IDs like 'unresolved:...'."""
        data = {
            "id": "unresolved:some_symbol",
            "type": "unresolved",
            "name": "some_symbol",
            "file": "foo.py",
            "start_line": 1,
            "end_line": 1,
            "start_byte": 0,
            "end_byte": 10,
        }
        entity = Entity.from_dict(data)
        assert entity.id_override == "unresolved:some_symbol"
        assert entity.id == "unresolved:some_symbol"

    def test_from_dict_existing_id_override_takes_precedence(self):
        """If id_override is already present in the dict, it wins."""
        data = {
            "id": "from_id_field",
            "id_override": "from_override_field",
            "type": "function",
            "name": "bar",
            "file": "foo.py",
            "start_line": 1,
            "end_line": 1,
            "start_byte": 0,
            "end_byte": 10,
        }
        entity = Entity.from_dict(data)
        assert entity.id_override == "from_override_field"

    def test_from_dict_none_id_ignored(self):
        """If the serialized id is explicitly None, don't set id_override."""
        data = {
            "id": None,
            "type": "function",
            "name": "bar",
            "file": "foo.py",
            "start_line": 1,
            "end_line": 1,
            "start_byte": 0,
            "end_byte": 10,
        }
        entity = Entity.from_dict(data)
        assert entity.id_override is None
        assert entity.id == "ent|FUNCTION|foo.py|0|10|1|1|bar"
