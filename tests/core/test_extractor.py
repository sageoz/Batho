"""Tests for batho.context.extractor module."""
from __future__ import annotations

from pathlib import Path

import pytest

from batho.context.extractor import (
    ASTExtractor,
    MarkupConfigExtractor,
    _clean_docstring,
)
from batho.utils.file_io import _read_file_bytes
from batho.context.schema import Entity, EntityType, Relationship, RelationshipType


# ---------------------------------------------------------------------------
# _read_file_bytes
# ---------------------------------------------------------------------------

class TestReadFileBytes:

    def test_read_normal_file(self, tmp_path: Path):
        f = tmp_path / "test.py"
        f.write_text("x = 1\n")
        result = _read_file_bytes(str(f))
        assert result is not None
        assert b"x = 1" in result

    def test_oversized_file_returns_none(self, tmp_path: Path):
        f = tmp_path / "big.py"
        f.write_bytes(b"x" * 600_000)  # > 500KB
        result = _read_file_bytes(str(f), max_size_kb=500)
        assert result is None

    def test_nonexistent_file_returns_none(self):
        result = _read_file_bytes("/no/such/file.py")
        assert result is None

    def test_normalizes_to_utf8(self, tmp_path: Path):
        f = tmp_path / "latin.py"
        f.write_bytes("café".encode("latin-1"))
        result = _read_file_bytes(str(f))
        assert result is not None
        # Should be valid UTF-8
        result.decode("utf-8")


# ---------------------------------------------------------------------------
# _clean_docstring
# ---------------------------------------------------------------------------

class TestCleanDocstring:

    def test_triple_double_quotes(self):
        assert _clean_docstring('"""Hello world"""') == "Hello world"

    def test_triple_single_quotes(self):
        assert _clean_docstring("'''Hello'''") == "Hello"

    def test_single_quotes(self):
        assert _clean_docstring("'Hello'") == "Hello"

    def test_no_quotes(self):
        assert _clean_docstring("plain text") == "plain text"

    def test_whitespace_stripping(self):
        assert _clean_docstring('"""  spaced  """') == "spaced"


# ---------------------------------------------------------------------------
# ASTExtractor.parse_file (via Python extractor)
# ---------------------------------------------------------------------------

class TestASTExtractorParseFile:

    def test_python_extraction(self):
        """Parse a simple Python source and verify entities are extracted."""
        from batho.context.languages.registry import get_extractor

        extractor = get_extractor(".py")
        assert extractor is not None

        content = b'''
def greet(name: str) -> str:
    """Say hello."""
    return f"Hello, {name}"

class Person:
    def __init__(self, name: str):
        self.name = name
'''
        entities, relationships = extractor.parse_file("test.py", content)
        names = [e.name for e in entities]
        assert "greet" in names
        assert "Person" in names

    def test_empty_content(self):
        from batho.context.languages.registry import get_extractor

        extractor = get_extractor(".py")
        entities, rels = extractor.parse_file("empty.py", b"")
        assert entities == []

    def test_malformed_content(self):
        """Malformed content should return empty, not raise."""
        from batho.context.languages.registry import get_extractor

        extractor = get_extractor(".py")
        # This is technically parseable by tree-sitter (error-tolerant)
        entities, rels = extractor.parse_file("bad.py", b"def (broken syntax{{{")
        # Should not raise — error isolation

    def test_entities_have_file_field(self):
        from batho.context.languages.registry import get_extractor

        extractor = get_extractor(".py")
        content = b"def foo(): pass\n"
        entities, _ = extractor.parse_file("src/main.py", content)
        for e in entities:
            assert e.file == "src/main.py"

    def test_parse_file_twice_is_stable(self):
        from batho.context.languages.registry import get_extractor

        extractor = get_extractor(".py")
        assert extractor is not None

        content = b"def foo(x: int) -> int:\n    return x\n"
        first_entities, first_rels = extractor.parse_file("src/a.py", content)
        second_entities, second_rels = extractor.parse_file("src/a.py", content)

        assert [entity.name for entity in first_entities] == [
            entity.name for entity in second_entities
        ]
        assert len(first_rels) == len(second_rels)


# ---------------------------------------------------------------------------
# MarkupConfigExtractor helpers
# ---------------------------------------------------------------------------

class TestMarkupConfigExtractor:

    def test_json_extraction(self):
        from batho.context.languages.registry import get_extractor

        extractor = get_extractor(".json")
        if extractor is None:
            pytest.skip("JSON extractor not in registry")

        content = b'{"name": "test", "version": "1.0"}'
        entities, rels = extractor.parse_file("config.json", content)
        # Should extract some elements
        assert isinstance(entities, list)
        doc_entities = [e for e in entities if e.type == EntityType.DOCUMENT]
        assert len(doc_entities) == 1

    def test_toml_extraction(self):
        from batho.context.languages.registry import get_extractor

        extractor = get_extractor(".toml")
        if extractor is None:
            pytest.skip("TOML extractor not in registry")

        content = b"""
        [app]
        name = "test"
        version = "1.0"
        """
        entities, rels = extractor.parse_file("config.toml", content)
        assert isinstance(entities, list)
        doc_entities = [e for e in entities if e.type == EntityType.DOCUMENT]
        assert len(doc_entities) == 1

    def test_markup_entities_include_language_metadata(self):
        from batho.context.languages.registry import get_extractor

        extractor = get_extractor(".json")
        if extractor is None:
            pytest.skip("JSON extractor not in registry")

        content = b'{"name": "test", "version": "1.0"}'
        entities, _ = extractor.parse_file("config.json", content)
        assert entities
        for entity in entities:
            assert entity.metadata.get("language") == "json"
