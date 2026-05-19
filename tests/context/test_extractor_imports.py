"""Tests for import target normalization and expansion helpers."""

from __future__ import annotations

from batho.context.extractor import _expand_import_targets, _normalize_import_target
from batho.context.languages.python import PythonExtractor
from batho.context.languages.r import RExtractor
from batho.context.schema import EntityType


class TestImportNormalization:
    def test_normalize_strips_quotes_alias_and_scope(self):
        normalized = _normalize_import_target('"foo::bar" as baz')
        assert normalized == "foo.bar"

    def test_expand_grouped_import_targets(self):
        targets = _expand_import_targets("foo::{bar, baz as qux, self, *}")
        assert "foo" in targets
        assert "foo.bar" in targets
        assert "foo.baz" in targets

    def test_expand_filters_import_stopwords(self):
        assert _expand_import_targets("library") == []
        assert _expand_import_targets("require") == []


class TestRExtractorImports:
    def test_r_import_calls_are_captured(self):
        extractor = RExtractor()
        source = b"""foo <- function(x) x
run_analysis <- function() {
    library(dplyr)
    require('ggplot2')
}
"""
        entities, relationships = extractor.parse_file("sample.R", source)

        # Verify UNRESOLVED entities were created for dplyr and ggplot2
        unresolved_names = sorted(
            e.name
            for e in entities
            if e.type == EntityType.UNRESOLVED
        )
        assert "dplyr" in unresolved_names
        assert "ggplot2" in unresolved_names

        # Verify that relationships target the UNRESOLVED entity IDs
        unresolved_ids = set(
            e.id for e in entities if e.type == EntityType.UNRESOLVED
        )
        import_targets = sorted(
            rel.target_id
            for rel in relationships
            if rel.type.name == "IMPORTS"
        )
        for target in import_targets:
            assert target in unresolved_ids, f"Target {target} should be an UNRESOLVED entity ID"


class TestLeadingCommentDocFallback:
    def test_python_leading_comment_becomes_docstring(self):
        extractor = PythonExtractor()
        source = b"# Resolve user by id\ndef find_user(user_id):\n    return user_id\n"
        entities, _ = extractor.parse_file("sample.py", source)

        fn_entity = next((entity for entity in entities if entity.name == "find_user"), None)
        assert fn_entity is not None
        assert fn_entity.metadata.get("docstring") == "Resolve user by id"
