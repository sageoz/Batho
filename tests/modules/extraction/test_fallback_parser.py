"""Tests for fallback_parser entity extraction and deduplication."""

from __future__ import annotations

from pathlib import Path

from batho.core.schemas import EntityType
from batho.modules.extraction.fallback_parser import FallbackParser


class TestFallbackParserDeduplication:
    """BUG-06: Entities must be deduplicated by (name, type, start_line)."""

    def test_distinct_types_same_name_preserved(self):
        """A class and function with the same name are distinct entities."""
        content = "\n".join([
            "class Foo:",
            "    pass",
            "def Foo():",
            "    pass",
        ])
        parser = FallbackParser()
        result = parser.parse_file(Path("test.py"), content.encode("utf-8"))

        names = [e.name for e in result.entities]
        types = [e.type for e in result.entities]

        assert names.count("Foo") == 2
        assert EntityType.CLASS in types
        assert EntityType.FUNCTION in types

    def test_same_name_different_lines_preserved(self):
        """Two functions with the same name on different lines are distinct."""
        # Synthetic case: two def blocks with the same name on separate lines
        content = "\n".join([
            "def helper():",
            "    pass",
            "def helper():",
            "    return 1",
        ])
        parser = FallbackParser()
        result = parser.parse_file(Path("test.py"), content.encode("utf-8"))

        helpers = [e for e in result.entities if e.name == "helper"]
        assert len(helpers) == 2
        assert helpers[0].start_line != helpers[1].start_line

    def test_duplicate_exact_match_deduplicated(self):
        """An entity with identical (name, type, line) should be deduplicated."""
        # Python class pattern will match class Foo twice if we had two identical
        # lines, but we only have one line. Instead, test with JS-style class
        # and Python-style class both matching the same line.
        content = "class Foo {}\n"
        parser = FallbackParser()
        result = parser.parse_file(Path("test.js"), content.encode("utf-8"))

        # Both the generic JS class pattern and the generic "class" pattern may
        # fire, but deduplication by (name, type, line) should keep only one.
        foo_classes = [e for e in result.entities if e.name == "Foo" and e.type == EntityType.CLASS]
        assert len(foo_classes) == 1, (
            f"Expected 1 CLASS 'Foo', got {len(foo_classes)}"
        )

    def test_empty_content_returns_no_entities(self):
        parser = FallbackParser()
        result = parser.parse_file(Path("empty.py"), b"")
        assert result.entities == []
        assert result.status.value == "partial"
