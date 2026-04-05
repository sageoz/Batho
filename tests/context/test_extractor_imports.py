"""Tests for import target normalization and expansion helpers."""

from __future__ import annotations

from batho.context.extractor import _expand_import_targets, _normalize_import_target
from batho.context.languages.python import PythonExtractor
from batho.context.languages.r import RExtractor


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
        source = b"foo <- function(x) x\nlibrary(dplyr)\nrequire('ggplot2')\n"
        _, relationships = extractor.parse_file("sample.R", source)

        targets = sorted(
            rel.target_id
            for rel in relationships
            if rel.type.name == "IMPORTS"
        )
        assert "unresolved:dplyr" in targets
        assert "unresolved:ggplot2" in targets


class TestLeadingCommentDocFallback:
    def test_python_leading_comment_becomes_docstring(self):
        extractor = PythonExtractor()
        source = b"# Resolve user by id\ndef find_user(user_id):\n    return user_id\n"
        entities, _ = extractor.parse_file("sample.py", source)

        fn_entity = next((entity for entity in entities if entity.name == "find_user"), None)
        assert fn_entity is not None
        assert fn_entity.metadata.get("docstring") == "Resolve user by id"
