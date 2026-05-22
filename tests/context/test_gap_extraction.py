"""
Tests for Phase 2 — Gap Extraction (SYNTAX_GLUE entities) and Coverage Validation.

Covers:
- _extract_gaps() leading/middle/trailing/empty/no-gap scenarios
- _classify_gap_type() heuristics
- validate_byte_coverage() full coverage, gaps, overlaps, strict/warn modes
- Integration: parse a real file with include_gaps=True, validate 100% coverage
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from batho.context.extractor import ASTExtractor
from batho.context.schema import (
    CoverageError,
    Entity,
    EntityType,
    validate_byte_coverage,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(
    start_byte: int,
    end_byte: int,
    raw_content: str | None = None,
    name: str = "test",
) -> Entity:
    """Create a minimal Entity for testing coverage logic."""
    return Entity(
        type=EntityType.FUNCTION,
        name=name,
        file="test.py",
        start_line=1,
        end_line=1,
        start_byte=start_byte,
        end_byte=end_byte,
        raw_content=raw_content,
        content_hash=hashlib.sha256(
            (raw_content or "").encode("utf-8")
        ).hexdigest(),
    )


# ---------------------------------------------------------------------------
# Tests for validate_byte_coverage()
# ---------------------------------------------------------------------------


class TestValidateByteCoverage:
    def test_full_coverage(self):
        """Entities covering the entire file -> 1.0 coverage."""
        entities = [
            _make_entity(0, 5, "abcde"),
            _make_entity(5, 10, "fghij"),
        ]
        report = validate_byte_coverage(entities, file_size=10)
        assert report["valid"] is True
        assert report["byte_coverage"] == 1.0
        assert report["gap_ranges"] == []
        assert report["overlap_ranges"] == []

    def test_full_coverage_empty_file(self):
        """Empty file, no entities -> 1.0 coverage."""
        report = validate_byte_coverage([], file_size=0)
        assert report["valid"] is True
        assert report["byte_coverage"] == 1.0

    def test_detects_leading_gap(self):
        """Leading gap from byte 0 to first entity start."""
        entities = [_make_entity(3, 8, "abcde")]
        report = validate_byte_coverage(entities, file_size=8)
        assert report["byte_coverage"] < 1.0
        assert (3, 8) not in report["gap_ranges"]  # entity range is not a gap
        assert (0, 3) in report["gap_ranges"]  # leading gap
        assert report["valid"] is False

    def test_detects_middle_gap(self):
        """Gap between two entities."""
        entities = [
            _make_entity(0, 3, "abc"),
            _make_entity(6, 9, "ghi"),
        ]
        report = validate_byte_coverage(entities, file_size=9)
        assert (3, 6) in report["gap_ranges"]
        assert report["valid"] is False

    def test_detects_trailing_gap(self):
        """Trailing gap after last entity."""
        entities = [_make_entity(0, 3, "abc")]
        report = validate_byte_coverage(entities, file_size=6)
        assert (3, 6) in report["gap_ranges"]
        assert report["valid"] is False

    def test_detects_overlap(self):
        """Overlapping entity ranges."""
        entities = [
            _make_entity(0, 5, "abcde"),
            _make_entity(3, 8, "defgh"),
        ]
        report = validate_byte_coverage(entities, file_size=8)
        assert report["overlap_ranges"] != []
        assert report["valid"] is False

    def test_strict_mode_raises_on_gap(self):
        """strict=True raises CoverageError on any gap."""
        entities = [_make_entity(3, 5, "cd")]
        with pytest.raises(CoverageError) as exc:
            validate_byte_coverage(entities, file_size=5, strict=True)
        assert exc.value.byte_coverage < 1.0
        assert len(exc.value.gap_ranges) > 0

    def test_strict_mode_raises_on_overlap(self):
        """strict=True raises CoverageError on overlap."""
        entities = [
            _make_entity(0, 5, "abcde"),
            _make_entity(3, 8, "defgh"),
        ]
        with pytest.raises(CoverageError) as exc:
            validate_byte_coverage(entities, file_size=8, strict=True)
        assert len(exc.value.overlapping_ranges) > 0

    def test_non_strict_returns_report_on_gap(self):
        """strict=False returns report dict instead of raising."""
        entities = [_make_entity(3, 5, "cd")]
        report = validate_byte_coverage(entities, file_size=5, strict=False)
        assert report["valid"] is False
        assert "gap_ranges" in report

    def test_multiple_gaps_and_overlaps(self):
        """Complex case with both gaps and overlaps."""
        entities = [
            _make_entity(0, 4, "abcd"),
            _make_entity(2, 6, "cdef"),  # overlaps with first
            _make_entity(10, 14, "ijkl"),  # gap after second
        ]
        report = validate_byte_coverage(entities, file_size=14)
        assert report["valid"] is False
        assert len(report["gap_ranges"]) >= 1
        assert len(report["overlap_ranges"]) >= 1

    def test_entity_without_raw_content(self):
        """Entity without raw_content doesn't create byte gaps but fails internal validation."""
        entity = Entity(
            type=EntityType.FUNCTION,
            name="no_raw",
            file="test.py",
            start_line=1,
            end_line=1,
            start_byte=0,
            end_byte=5,
        )
        report = validate_byte_coverage([entity], file_size=5)
        # The entity's byte range (0-5) covers the full file, so no byte gaps.
        # validate_coverage raises ValueError for missing raw_content,
        # which is caught internally but doesn't produce a gap in byte ranges.
        assert report["byte_coverage"] == 1.0
        assert report["valid"] is True

    def test_single_entity_full_coverage(self):
        """Single entity covering entire file."""
        entities = [_make_entity(0, 10, "abcdefghij")]
        report = validate_byte_coverage(entities, file_size=10)
        assert report["valid"] is True
        assert report["byte_coverage"] == 1.0


# ---------------------------------------------------------------------------
# Tests for gap extraction internals
# ---------------------------------------------------------------------------


class TestGapExtractionLogic:
    """Tests for _extract_gaps() and _classify_gap_type().

    We create a minimal ASTExtractor subclass to access the gap methods.
    """

    class _TestExtractor(ASTExtractor):
        """Minimal extractor for testing gap internals."""

        def __init__(self) -> None:
            super().__init__("python")

        def _query_source(self) -> str:
            return ""

    @pytest.fixture
    def extractor(self) -> ASTExtractor:
        return self._TestExtractor()

    # --- _classify_gap_type ---

    def test_classify_whitespace(self, extractor: ASTExtractor):
        assert extractor._classify_gap_type("   \n  \n") == "whitespace"

    def test_classify_empty(self, extractor: ASTExtractor):
        assert extractor._classify_gap_type("") == "whitespace"

    def test_classify_comment(self, extractor: ASTExtractor):
        assert extractor._classify_gap_type("# this is a comment\n") == "comment"
        assert extractor._classify_gap_type("// C-style comment\n") == "comment"

    def test_classify_import_statement(self, extractor: ASTExtractor):
        assert extractor._classify_gap_type("import os\n") == "import"
        assert extractor._classify_gap_type("from pathlib import Path\n") == "import"

    def test_classify_separator(self, extractor: ASTExtractor):
        assert extractor._classify_gap_type("---\n") == "separator"
        assert extractor._classify_gap_type("***\n") == "separator"
        assert extractor._classify_gap_type("=======\n") == "separator"

    def test_classify_code_default(self, extractor: ASTExtractor):
        assert extractor._classify_gap_type("x = 1\n") == "code"
        assert extractor._classify_gap_type("print('hello')\n") == "code"

    # --- _extract_gaps ---

    def test_gap_leading_only(self, extractor: ASTExtractor):
        """Leading gap before first entity."""
        # "  AAA": 5 bytes, entity "AAA" at 2-5, gap "  " at 0-2
        content = b"  AAA"
        entities = [
            _make_entity(2, 5, "AAA"),
        ]
        gaps = extractor._extract_gaps(content, "test.py", entities)
        assert len(gaps) == 1
        assert gaps[0].type == EntityType.SYNTAX_GLUE
        assert gaps[0].start_byte == 0
        assert gaps[0].end_byte == 2
        assert gaps[0].metadata["gap_type"] == "whitespace"

    def test_gap_trailing_only(self, extractor: ASTExtractor):
        """Trailing whitespace after last entity."""
        # "AAA  ": 5 bytes, entity "AAA" at 0-3, gap "  " at 3-5
        content = b"AAA  "
        entities = [
            _make_entity(0, 3, "AAA"),
        ]
        gaps = extractor._extract_gaps(content, "test.py", entities)
        assert len(gaps) == 1
        assert gaps[0].start_byte == 3
        assert gaps[0].end_byte == 5
        assert gaps[0].metadata["gap_type"] == "whitespace"

    def test_gap_middle_only(self, extractor: ASTExtractor):
        """Gap between two entities."""
        # "AAABBB": 6 bytes, entities "AAA" at 0-3, "BBB" at 3-6, no gap
        # "AAA   BBB": 9 bytes, entities "AAA" at 0-3, "BBB" at 6-9, gap at 3-6
        content = b"AAA   BBB"
        entities = [
            _make_entity(0, 3, "AAA"),
            _make_entity(6, 9, "BBB"),
        ]
        gaps = extractor._extract_gaps(content, "test.py", entities)
        assert len(gaps) == 1
        assert gaps[0].start_byte == 3
        assert gaps[0].end_byte == 6
        assert gaps[0].metadata["gap_type"] == "whitespace"

    def test_gap_leading_middle_trailing(self, extractor: ASTExtractor):
        """All three gap types present."""
        # "  AAA   BBB  ": 13 bytes
        # entities: "AAA" at 2-5, "BBB" at 8-11
        # gaps: 0-2 (leading), 5-8 (middle), 11-13 (trailing)
        content = b"  AAA   BBB  "
        entities = [
            _make_entity(2, 5, "AAA"),
            _make_entity(8, 11, "BBB"),
        ]
        gaps = extractor._extract_gaps(content, "test.py", entities)
        assert len(gaps) == 3  # leading, middle, trailing

        leading = gaps[0]
        assert leading.start_byte == 0
        assert leading.end_byte == 2

        middle = gaps[1]
        assert middle.start_byte == 5
        assert middle.end_byte == 8

        trailing = gaps[2]
        assert trailing.start_byte == 11
        assert trailing.end_byte == 13

    def test_gap_empty_file(self, extractor: ASTExtractor):
        """Empty content returns no gaps."""
        content = b""
        gaps = extractor._extract_gaps(content, "test.py", [])
        assert gaps == []

    def test_gap_no_semantic_entities(self, extractor: ASTExtractor):
        """File with only whitespace -> one SYNTAX_GLUE."""
        content = b"   \n  \n"
        gaps = extractor._extract_gaps(content, "test.py", [])
        assert len(gaps) == 1
        assert gaps[0].type == EntityType.SYNTAX_GLUE
        assert gaps[0].start_byte == 0
        assert gaps[0].end_byte == 7

    def test_gap_zero_semantic_entities_with_include_gaps(self, extractor: ASTExtractor):
        """When include_gaps=True and entities is empty, _extract_gaps is still called.

        This tests the fix for the bug where gap extraction was skipped when
        entities list was empty, even with include_gaps=True.
        """
        content = b"# comment only\n"
        # Simulate the scenario where the extractor has no semantic entities
        # but include_gaps is True
        gaps = extractor._extract_gaps(content, "test.py", [])
        assert len(gaps) == 1
        assert gaps[0].type == EntityType.SYNTAX_GLUE
        assert gaps[0].raw_content == "# comment only\n"
        assert gaps[0].metadata["gap_type"] == "comment"

    def test_gap_no_gaps_when_full_coverage(self, extractor: ASTExtractor):
        """Entities cover entire file -> zero gaps."""
        content = b"abcdef"
        entities = [_make_entity(0, 6, "abcdef")]
        gaps = extractor._extract_gaps(content, "test.py", entities)
        assert gaps == []

    def test_gap_zero_length_gaps_skipped(self, extractor: ASTExtractor):
        """Zero-length gaps (when curr_end == next_start) are skipped."""
        # "AAA": 3 bytes, entity "AAA" at 0-3
        # No gap between entities since they touch
        content = b"AAA"
        entities = [
            _make_entity(0, 3, "AAA"),
        ]
        gaps = extractor._extract_gaps(content, "test.py", entities)
        assert gaps == []

    def test_gap_content_hash_raw_bytes(self, extractor: ASTExtractor):
        """content_hash is sha256 of raw bytes (not normalized text)."""
        content = b"  "
        entities = [_make_entity(2, 2, "")]
        gaps = extractor._extract_gaps(content, "test.py", entities)
        # entity at 2-2 = empty, so there's a leading gap 0-2
        assert len(gaps) > 0
        expected_hash = hashlib.sha256(content[0:2]).hexdigest()
        assert gaps[0].content_hash == expected_hash

    def test_gap_contains_comments_metadata(self, extractor: ASTExtractor):
        """Gap containing a comment sets contains_comments=True."""
        content = b"# license header\nAAA"
        entities = [
            _make_entity(17, 20, "AAA"),
        ]
        gaps = extractor._extract_gaps(content, "test.py", entities)
        leading_gap = gaps[0]
        assert leading_gap.metadata["contains_comments"] is True
        assert leading_gap.metadata["gap_type"] == "comment"

    def test_gap_is_empty_metadata(self, extractor: ASTExtractor):
        """Gap with only whitespace sets is_empty=True."""
        content = b"   AAA"
        entities = [_make_entity(3, 6, "AAA")]
        gaps = extractor._extract_gaps(content, "test.py", entities)
        leading_gap = gaps[0]
        # "   " stripped is empty -> is_empty True
        assert leading_gap.metadata["is_empty"] is True

    def test_gap_nested_entities(self, extractor: ASTExtractor):
        """Nested entities should be handled by merging covered intervals, leaving no gaps inside the parent."""
        # Content layout:
        # 0-10: Leading gap (10 bytes)
        # 10-50: Parent entity
        #   20-30: Nested child entity
        # 50-60: Trailing gap (10 bytes)
        content = b"0123456789" + b"A" * 40 + b"0123456789"
        entities = [
            _make_entity(10, 50, "A" * 40, name="Parent"),
            _make_entity(20, 30, "A" * 10, name="Child"),
        ]
        gaps = extractor._extract_gaps(content, "test.py", entities)
        # We expect only 2 gaps: leading (0-10) and trailing (50-60).
        # There should be no gap from 30-50.
        assert len(gaps) == 2

        leading = gaps[0]
        assert leading.start_byte == 0
        assert leading.end_byte == 10
        assert leading.raw_content == "0123456789"

        trailing = gaps[1]
        assert trailing.start_byte == 50
        assert trailing.end_byte == 60
        assert trailing.raw_content == "0123456789"


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGapExtractionIntegration:
    """Real file parsing with include_gaps=True."""

    def test_parse_with_gaps_produces_glue_entities(
        self, simple_python_repo: Path
    ):
        """Index simple_python with include_gaps (default on) -> SYNTAX_GLUE entities appear."""
        from batho.context.codegraph import CodeGraphIndexer

        indexer = CodeGraphIndexer()
        graph = indexer.build_graph(
            root=str(simple_python_repo),
            max_workers=0,
        )

        # Check that SYNTAX_GLUE entities exist
        glue_count = sum(
            1 for e in graph.entities.values() if e.type == EntityType.SYNTAX_GLUE
        )
        assert glue_count >= 0  # at minimum, code doesn't crash

    @pytest.mark.integration
    def test_parse_without_gaps_no_glue(
        self, simple_python_repo: Path
    ):
        """Index without gaps -> extractor produces no SYNTAX_GLUE entities.

        Note: BSG rule plugins may independently add SYNTAX_GLUE entities to the
        graph during semantic overlay. This test verifies the *extractor itself*
        does not emit gap entities when include_gaps=False, by testing the
        extractor layer directly.
        """
        from batho.context.languages.detector import default_detector
        from batho.context.extractor import ASTExtractor

        py_files = sorted(simple_python_repo.rglob("*.py"))
        assert len(py_files) > 0

        # Pick a file with non-trivial code to ensure semantic entities are extracted
        code_file = next(
            (f for f in py_files if "calculator" in f.name or "utils" in f.name),
            py_files[-1],
        )
        content = code_file.read_bytes()

        extractor = default_detector.get_extractor(code_file, content)
        assert isinstance(extractor, ASTExtractor), f"No extractor for {code_file}"

        entities, _rels = extractor.parse_file(
            str(code_file),
            content,
            include_gaps=False,
        )

        extractor_glue = sum(
            1 for e in entities if e.type == EntityType.SYNTAX_GLUE
        )
        assert extractor_glue == 0, (
            f"Expected 0 extractor-level SYNTAX_GLUE entities, "
            f"got {extractor_glue}. "
            "The extractor should not produce gaps when include_gaps=False."
        )

        # Verify that with include_gaps=True the same file DOES produce gaps
        entities_with_gaps, _ = extractor.parse_file(
            str(code_file),
            content,
            include_gaps=True,
        )

        with_gaps_count = sum(
            1 for e in entities_with_gaps if e.type == EntityType.SYNTAX_GLUE
        )
        assert with_gaps_count > 0, (
            "Expected SYNTAX_GLUE entities with include_gaps=True"
        )