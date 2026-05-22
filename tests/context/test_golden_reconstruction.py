"""
Golden file tests for BSG bidirectional roundtrip reconstruction.

Each test:
1. Parses a small fixture file with include_gaps=True via the extractor
2. Sets raw_content on all entities using original source bytes (post-processing)
3. Reconstructs the file from BSG entities using FileReconstructor
4. Verifies the output is byte-for-byte identical to the original

Covers edge cases: comments-only, imports-only, blank lines, mixed content.

Note: These tests use the extractor directly (not through CodeGraphIndexer)
to avoid shared cache interference and to test the core reconstruction
logic in isolation.  The extractor sets raw_content only on SYNTAX_GLUE
entities; a production pipeline would set it on all entities during
post-processing (mirrored here by :func:`_set_raw_content`).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from batho.context.extractor import ASTExtractor
from batho.context.languages.detector import default_detector
from batho.context.reconstructor import FileReconstructor
from batho.context.schema import EntityType, validate_byte_coverage


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent.parent / "testdata" / "fixtures"

GOLDEN_FIXTURES = [
    "golden_roundtrip_comment.py",
    "golden_roundtrip_import.py",
    "golden_roundtrip_blank_lines.py",
    "golden_roundtrip_mixed.py",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_raw_content(
    entities: list[Entity],
    content: bytes,
) -> list[Entity]:
    """Set raw_content on all entities based on their byte ranges.

    The extractor only sets ``raw_content`` on SYNTAX_GLUE entities.
    For reconstruction we need it on every entity.  This mirrors what a
    production post-processing step would do after extraction.
    """
    updated: list[Entity] = []
    for ent in entities:
        if ent.raw_content is not None:
            updated.append(ent)
            continue
        raw = content[ent.start_byte : ent.end_byte].decode(
            "utf-8", errors="replace"
        )
        h = hashlib.sha256(
            content[ent.start_byte : ent.end_byte]
        ).hexdigest()
        updated.append(
            ent.model_copy(update={"raw_content": raw, "content_hash": h})
        )
    return updated


# ---------------------------------------------------------------------------
# Fixture: parse a fixture file and return entities + original bytes
# ---------------------------------------------------------------------------


@pytest.fixture(params=GOLDEN_FIXTURES, ids=GOLDEN_FIXTURES)
def golden_fixture(request: pytest.FixtureRequest):
    """Yield (fixture_name, original_bytes, original_hash, entities) per fixture.

    Uses the detector + extractor to parse the file with include_gaps=True.
    Post-processes extracted entities to set raw_content on all of them.
    """
    fixture_name = request.param
    src = FIXTURES_DIR / fixture_name
    assert src.exists(), f"Golden fixture not found: {src}"

    original_bytes = src.read_bytes()
    original_hash = hashlib.sha256(original_bytes).hexdigest()

    # Detect language and get extractor
    extractor = default_detector.get_extractor(src, original_bytes)
    assert extractor is not None, f"No extractor found for {fixture_name}"
    assert isinstance(extractor, ASTExtractor), f"Not an ASTExtractor: {type(extractor)}"

    # Parse with include_gaps=True
    entities, _ = extractor.parse_file(
        fixture_name,
        original_bytes,
        include_gaps=True,
    )

    assert len(entities) > 0, (
        f"No entities extracted from {fixture_name}. "
        "The extractor should produce entities."
    )

    # Post-process: set raw_content on all entities
    entities = _set_raw_content(entities, original_bytes)

    yield fixture_name, original_bytes, original_hash, entities


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGoldenReconstruction:
    """Byte-for-byte reconstruction from BSG entities."""

    def test_reconstruction_roundtrip(
        self, golden_fixture: tuple
    ):
        """Reconstructed content must match original bytes exactly."""
        fixture_name, original_bytes, original_hash, entities = golden_fixture

        reconstructor = FileReconstructor()
        result = reconstructor.reconstruct_file(
            file_path=fixture_name,
            entities=entities,
            original_hash=original_hash,
        )

        assert result.success is True, (
            f"Reconstruction failed for {fixture_name}: {result.errors}"
        )

        # Byte-for-byte comparison
        reconstructed_bytes = result.reconstructed_content.encode("utf-8")
        assert reconstructed_bytes == original_bytes, (
            f"Byte mismatch for {fixture_name}:\n"
            f"  Original size: {len(original_bytes)}\n"
            f"  Reconstructed size: {len(reconstructed_bytes)}\n"
            f"  Original hash: {original_hash}\n"
            f"  Reconstructed hash: {result.reconstructed_hash}"
        )

    def test_reconstruction_hash_match(
        self, golden_fixture: tuple
    ):
        """Reconstructed hash must match original hash."""
        _fixture_name, _original_bytes, original_hash, entities = golden_fixture

        reconstructor = FileReconstructor()
        result = reconstructor.reconstruct_file(
            file_path=_fixture_name,
            entities=entities,
            original_hash=original_hash,
        )

        assert result.hash_match is True, (
            f"Hash mismatch for {_fixture_name}: "
            f"expected {original_hash}, got {result.reconstructed_hash}"
        )

    def test_reconstruction_includes_gap_entities(
        self, golden_fixture: tuple
    ):
        """Reconstruction should include SYNTAX_GLUE gap entities."""
        _fixture_name, _original_bytes, _original_hash, entities = golden_fixture

        glue_entities = [e for e in entities if e.type == EntityType.SYNTAX_GLUE]

        # All fixture files should have at least some gaps (whitespace, newlines)
        assert len(glue_entities) > 0, (
            f"No SYNTAX_GLUE entities found for {_fixture_name}. "
            "Gap extraction may not be running."
        )

    def test_reconstruction_full_byte_coverage(
        self, golden_fixture: tuple
    ):
        """Byte coverage should be 100%."""
        _fixture_name, original_bytes, _original_hash, entities = golden_fixture

        report = validate_byte_coverage(
            entities, file_size=len(original_bytes), strict=False
        )

        assert report["valid"] is True, (
            f"Byte coverage validation failed for {_fixture_name}:\n"
            f"  Coverage: {report['byte_coverage']:.2%}\n"
            f"  Gaps: {report['gap_ranges']}\n"
            f"  Overlaps: {report['overlap_ranges']}"
        )
        assert report["byte_coverage"] == 1.0, (
            f"Byte coverage is {report['byte_coverage']:.2%}, expected 100%"
        )

    def test_reconstruction_without_gaps_fails_coverage(
        self, tmp_path: Path
    ):
        """Reconstruction without gaps should fail coverage check."""
        content = b"import os\n\n\ndef foo():\n    pass\n"
        src = tmp_path / "test.py"
        src.write_bytes(content)

        extractor = default_detector.get_extractor(src, content)
        assert isinstance(extractor, ASTExtractor)

        entities, _ = extractor.parse_file(
            "test.py", content, include_gaps=False
        )

        report = validate_byte_coverage(entities, file_size=len(content))
        assert not report["valid"], (
            "Expected coverage to fail when gap extraction is off"
        )


class TestGoldenReconstructionEdgeCases:
    """Edge case roundtrip tests."""

    def test_empty_file(self, tmp_path: Path):
        """Empty file produces no entities — reconstruction is a no-op.

        An empty file has no semantic content and no gaps.  The extractor
        returns an empty list when ``include_gaps=True`` on an empty file.
        In this case reconstruction is trivially complete — there is nothing
        to rebuild.
        """
        content = b""
        src = tmp_path / "empty.py"
        src.write_bytes(content)

        extractor = default_detector.get_extractor(src, content)
        assert isinstance(extractor, ASTExtractor)

        entities, _ = extractor.parse_file(
            "empty.py", content, include_gaps=True
        )

        # Empty file → no entities
        assert entities == [], (
            f"Expected no entities for empty file, got {len(entities)}"
        )

    def test_single_function_file(self, tmp_path: Path):
        """Simple function definition with no gaps."""
        content = b"def foo():\n    return 42\n"
        src = tmp_path / "func.py"
        src.write_bytes(content)

        extractor = default_detector.get_extractor(src, content)
        assert isinstance(extractor, ASTExtractor)

        entities, _ = extractor.parse_file(
            "func.py", content, include_gaps=True
        )
        assert len(entities) > 0, (
            "Expected at least 1 entity for a function definition"
        )
        entities = _set_raw_content(entities, content)

        reconstructor = FileReconstructor()
        result = reconstructor.reconstruct_file(
            file_path="func.py",
            entities=entities,
        )

        reconstructed_bytes = result.reconstructed_content.encode("utf-8")
        assert reconstructed_bytes == content, (
            f"Function mismatch:\n  Expected: {content!r}\n  Got: {reconstructed_bytes!r}"
        )

    def test_file_with_only_comments_and_function(self, tmp_path: Path):
        """File with comments preceding a function."""
        content = b"# License header\n# Copyright 2026\n\ndef foo():\n    pass\n"
        src = tmp_path / "comments_and_code.py"
        src.write_bytes(content)

        extractor = default_detector.get_extractor(src, content)
        assert isinstance(extractor, ASTExtractor)

        entities, _ = extractor.parse_file(
            "comments_and_code.py", content, include_gaps=True
        )
        assert len(entities) > 0, (
            "Expected at least 1 entity for file with function"
        )
        entities = _set_raw_content(entities, content)

        reconstructor = FileReconstructor()
        result = reconstructor.reconstruct_file(
            file_path="comments_and_code.py",
            entities=entities,
            original_hash=hashlib.sha256(content).hexdigest(),
        )

        reconstructed_bytes = result.reconstructed_content.encode("utf-8")
        assert reconstructed_bytes == content
        assert result.hash_match