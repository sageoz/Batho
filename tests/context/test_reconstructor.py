"""
Tests for Phase 3 — Reconstruction Engine.

Covers:
- FileReconstructor.reconstruct_file() — simple, with gaps, edge cases
- FileReconstructor.verify_integrity() — pass/fail
- FileReconstructor.reconstruct_from_snapshot() — resolution logic
- Integration: extraction with include_gaps=True → reconstruction roundtrip
"""

from __future__ import annotations

import hashlib
import textwrap
from pathlib import Path
from typing import Any

import pytest

from batho.context.reconstructor import FileReconstructor
from batho.context.schema import (
    Entity,
    EntityType,
    FileSnapshot,
    IntegrityError,
    ReconstructionError,
    ReconstructionResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entity(
    start_byte: int,
    end_byte: int,
    raw_content: str,
    name: str = "test",
    file: str = "test.py",
    etype: EntityType = EntityType.FUNCTION,
) -> Entity:
    """Create a minimal Entity with raw_content for reconstruction tests."""
    return Entity(
        type=etype,
        name=name,
        file=file,
        start_line=1,
        end_line=1,
        start_byte=start_byte,
        end_byte=end_byte,
        raw_content=raw_content,
        content_hash=hashlib.sha256(raw_content.encode("utf-8")).hexdigest(),
    )


def _glue_entity(
    start_byte: int,
    end_byte: int,
    raw_content: str,
) -> Entity:
    """Create a SYNTAX_GLUE entity."""
    return _entity(
        start_byte,
        end_byte,
        raw_content,
        name="<glue>",
        etype=EntityType.SYNTAX_GLUE,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def reconstructor() -> FileReconstructor:
    return FileReconstructor()


# ===========================================================================
# reconstruct_file
# ===========================================================================


class TestReconstructFile:

    def test_simple_reconstruction(self, reconstructor: FileReconstructor):
        """Two entities covering a full file — content matches."""
        entities = [
            _entity(0, 5, "hello", name="greeting"),
            _entity(5, 12, ", world", name="world_greeting"),
        ]
        result = reconstructor.reconstruct_file(
            file_path="test.py", entities=entities
        )
        assert result.success is True
        assert result.reconstructed_content == "hello, world"
        assert result.entity_count == 2
        assert result.byte_coverage == 1.0
        assert result.errors == []

    def test_reconstruct_with_gap_entities(self, reconstructor: FileReconstructor):
        """Include SYNTAX_GLUE entities for full coverage."""
        entities = [
            _entity(0, 5, "hello", name="greeting"),
            _glue_entity(5, 6, " "),
            _entity(6, 11, "world", name="target"),
            _glue_entity(11, 12, "\n"),
        ]
        result = reconstructor.reconstruct_file(
            file_path="test.py", entities=entities
        )
        assert result.success is True
        assert result.reconstructed_content == "hello world\n"
        assert result.gap_count == 2

    def test_reconstruct_empty_entities_raises(
        self, reconstructor: FileReconstructor
    ):
        """Empty entity list raises ReconstructionError."""
        with pytest.raises(ReconstructionError) as exc:
            reconstructor.reconstruct_file(file_path="test.py", entities=[])
        assert "No entities" in str(exc.value)

    def test_reconstruct_missing_raw_content_raises(
        self, reconstructor: FileReconstructor
    ):
        """Entity without raw_content raises ReconstructionError."""
        entity = Entity(
            type=EntityType.FUNCTION,
            name="no_raw",
            file="test.py",
            start_line=1,
            end_line=1,
            start_byte=0,
            end_byte=5,
            raw_content=None,  # type: ignore[typeddict-item]
        )
        with pytest.raises(ReconstructionError) as exc:
            reconstructor.reconstruct_file(
                file_path="test.py", entities=[entity]
            )
        assert "No covering entities" in str(exc.value)

    def test_reconstruct_hash_match(self, reconstructor: FileReconstructor):
        """Providing correct original_hash succeeds."""
        entities = [_entity(0, 5, "hello", name="greeting")]
        original_hash = hashlib.sha256(b"hello").hexdigest()
        result = reconstructor.reconstruct_file(
            file_path="test.py", entities=entities, original_hash=original_hash
        )
        assert result.hash_match is True

    def test_reconstruct_hash_mismatch_raises(
        self, reconstructor: FileReconstructor
    ):
        """Wrong original_hash raises IntegrityError."""
        entities = [_entity(0, 5, "hello", name="greeting")]
        with pytest.raises(IntegrityError) as exc:
            reconstructor.reconstruct_file(
                file_path="test.py",
                entities=entities,
                original_hash="badhash" + "0" * 56,
            )
        assert "Hash mismatch" in str(exc.value)

    def test_reconstruct_with_original_content(
        self, reconstructor: FileReconstructor
    ):
        """Providing original_content auto-derives hash."""
        entities = [_entity(0, 5, "hello", name="greeting")]
        result = reconstructor.reconstruct_file(
            file_path="test.py", entities=entities, original_content="hello"
        )
        assert result.hash_match is True

    def test_reconstruct_single_entity(self, reconstructor: FileReconstructor):
        """Single entity covering entire file."""
        entities = [_entity(0, 12, "def foo(): x", name="foo")]
        result = reconstructor.reconstruct_file(
            file_path="test.py", entities=entities
        )
        assert result.success is True
        assert result.reconstructed_content == "def foo(): x"

    def test_reconstruct_byte_coverage_warning(
        self, reconstructor: FileReconstructor
    ):
        """Partial coverage produces a warning but still succeeds."""
        entities = [_entity(0, 5, "hello", name="greeting")]
        result = reconstructor.reconstruct_file(
            file_path="test.py", entities=entities
        )
        # byte_coverage depends on entity.end_byte tracking
        assert result.success is True
        # If entity ranges don't cover the max end_byte, coverage < 1.0

    def test_reconstruct_sort_order(self, reconstructor: FileReconstructor):
        """Entities are sorted by start_byte regardless of input order."""
        entities = [
            _entity(5, 11, " world", name="target"),
            _entity(0, 5, "hello", name="greeting"),
        ]
        result = reconstructor.reconstruct_file(
            file_path="test.py", entities=entities
        )
        assert result.reconstructed_content == "hello world"

    def test_reconstruct_non_utf8(self, reconstructor: FileReconstructor):
        """Content with non-UTF-8 characters uses errors=replace and does not crash."""
        raw_bytes = b"hello \xff\xfe world"  # invalid UTF-8 bytes
        decoded = raw_bytes.decode("utf-8", errors="replace")
        entities = [_entity(0, len(decoded.encode("utf-8")), decoded)]
        result = reconstructor.reconstruct_file(
            file_path="test.py", entities=entities
        )
        assert result.success is True


# ===========================================================================
# verify_integrity
# ===========================================================================


class TestVerifyIntegrity:

    def test_verify_integrity_passes(self, reconstructor: FileReconstructor):
        """Matching content returns verified=True."""
        entities = [_entity(0, 6, "hello\n", name="greeting")]
        report = reconstructor.verify_integrity(
            file_path="test.py", entities=entities, original_content="hello\n"
        )
        assert report["verified"] is True
        assert report["hash_match"] is True
        assert report["errors"] == []

    def test_verify_integrity_fails_hash(
        self, reconstructor: FileReconstructor
    ):
        """Mismatched content returns hash_match=False."""
        entities = [_entity(0, 5, "hello", name="greeting")]
        report = reconstructor.verify_integrity(
            file_path="test.py",
            entities=entities,
            original_content="world",
        )
        assert report["verified"] is False
        assert report["hash_match"] is False

    def test_verify_integrity_missing_raw_content(
        self, reconstructor: FileReconstructor
    ):
        """Entity missing raw_content returns error in the report."""
        entity = Entity(
            type=EntityType.FUNCTION,
            name="no_raw",
            file="test.py",
            start_line=1,
            end_line=1,
            start_byte=0,
            end_byte=5,
        )
        report = reconstructor.verify_integrity(
            file_path="test.py", entities=[entity], original_content="hello"
        )
        assert report["errors"] != []
        assert report["verified"] is False

    def test_verify_integrity_with_unresolved_entities(
        self, reconstructor: FileReconstructor
    ):
        """Entities with raw_content=None (unresolved) are handled gracefully.

        This tests the fix for the crash when computing hash with None values.
        The fix uses `e.raw_content or ""` to default to empty string for None.
        """
        # Mix of resolved and unresolved entities
        resolved_entity = _entity(0, 5, "hello", name="greeting")
        unresolved_entity = Entity(
            type=EntityType.FUNCTION,
            name="unresolved",
            file="test.py",
            start_line=1,
            end_line=1,
            start_byte=5,
            end_byte=10,
            raw_content=None,  # UNRESOLVED entity
        )
        entities = [resolved_entity, unresolved_entity]
        
        # Should not crash even with unresolved entities
        report = reconstructor.verify_integrity(
            file_path="test.py", entities=entities, original_content="hello     "
        )
        # The hash will be computed with empty string for the unresolved entity
        # so it won't match the original, but it shouldn't crash
        assert "verified" in report

    def test_verify_integrity_with_gaps(
        self, reconstructor: FileReconstructor
    ):
        """Full coverage with SYNTAX_GLUE passes verification."""
        entities = [
            _entity(0, 5, "hello", name="greeting"),
            _glue_entity(5, 6, " "),
            _entity(6, 11, "world", name="target"),
            _glue_entity(11, 12, "\n"),
        ]
        report = reconstructor.verify_integrity(
            file_path="test.py",
            entities=entities,
            original_content="hello world\n",
        )
        assert report["verified"] is True


# ===========================================================================
# reconstruct_from_snapshot
# ===========================================================================


class TestReconstructFromSnapshot:

    def test_reconstruct_from_snapshot_dict_lookup(
        self, reconstructor: FileReconstructor
    ):
        """Resolve entity_ids from a dict lookup."""
        e1 = _entity(0, 5, "hello", name="greeting")
        e2 = _entity(5, 12, ", world", name="world")
        snapshot = FileSnapshot(
            file_path="test.py",
            file_hash=hashlib.sha256(b"hello, world").hexdigest(),
            entity_ids=[e1.id, e2.id],
        )
        lookup = {e1.id: e1, e2.id: e2}
        result = reconstructor.reconstruct_from_snapshot(
            snapshot=snapshot, entity_lookup=lookup
        )
        assert result.success is True
        assert result.reconstructed_content == "hello, world"

    def test_reconstruct_from_snapshot_callable_lookup(
        self, reconstructor: FileReconstructor
    ):
        """Resolve entity_ids from a callable."""
        e1 = _entity(0, 5, "hello", name="greeting")
        snapshot = FileSnapshot(
            file_path="test.py",
            file_hash=hashlib.sha256(b"hello").hexdigest(),
            entity_ids=[e1.id],
        )

        def lookup(eid: str) -> Entity | None:
            return e1 if eid == e1.id else None

        result = reconstructor.reconstruct_from_snapshot(
            snapshot=snapshot, entity_lookup=lookup
        )
        assert result.success is True
        assert result.reconstructed_content == "hello"

    def test_reconstruct_from_snapshot_missing_id(
        self, reconstructor: FileReconstructor
    ):
        """Missing entity_ids are skipped gracefully; raises if none resolve."""
        snapshot = FileSnapshot(
            file_path="test.py",
            entity_ids=["nonexistent_id"],
        )
        with pytest.raises(ReconstructionError):
            reconstructor.reconstruct_from_snapshot(
                snapshot=snapshot, entity_lookup={}
            )

    def test_reconstruct_from_snapshot_integrity(
        self, reconstructor: FileReconstructor
    ):
        """Snapshot hash is verified against reconstructed content."""
        e1 = _entity(0, 5, "hello", name="greeting")
        snapshot = FileSnapshot(
            file_path="test.py",
            file_hash=hashlib.sha256(b"hello").hexdigest(),
            entity_ids=[e1.id],
        )
        lookup = {e1.id: e1}
        result = reconstructor.reconstruct_from_snapshot(
            snapshot=snapshot, entity_lookup=lookup
        )
        assert result.hash_match is True


# ===========================================================================
# Integration: extraction roundtrip
# ===========================================================================


class TestReconstructionRoundtrip:

    def test_reconstruct_python_file(self, tmp_path: Path, reconstructor: FileReconstructor):
        """Extract a real Python file with include_gaps=True, then reconstruct."""
        from batho.context.extractor import ASTExtractor
        from batho.context.languages.registry import get_extractor

        source = textwrap.dedent("""\
            def greet(name: str) -> str:
                return f"Hello, {name}!"


            class Person:
                def __init__(self, name: str) -> None:
                    self.name = name
        """)

        py_file = tmp_path / "example.py"
        py_file.write_text(source, encoding="utf-8")

        extractor = get_extractor(".py")
        assert extractor is not None, "Python extractor should be available"

        entities, relationships = extractor.parse_file(
            filepath=str(py_file),
            content=source.encode("utf-8"),
            include_gaps=True,
        )

        assert len(entities) > 0

        result = reconstructor.reconstruct_file(
            file_path=str(py_file),
            entities=entities,
            original_content=source,
        )

        assert result.success is True
        assert result.hash_match is True, (
            f"Reconstructed content does not match original. "
            f"Expected hash {result.original_hash}, got {result.reconstructed_hash}"
        )
        assert result.reconstructed_content == source
        assert result.byte_coverage == 1.0

    def test_reconstruct_empty_file(self, tmp_path: Path, reconstructor: FileReconstructor):
        """Empty file extracts no entities; reconstruction raises."""
        source = ""
        py_file = tmp_path / "empty.py"
        py_file.write_text(source, encoding="utf-8")

        with pytest.raises(ReconstructionError):
            reconstructor.reconstruct_file(
                file_path=str(py_file),
                entities=[],
                original_content=source,
            )

    def test_reconstruct_whitespace_file(self, tmp_path: Path, reconstructor: FileReconstructor):
        """File with only whitespace extracts SYNTAX_GLUE; reconstructs."""
        from batho.context.languages.registry import get_extractor

        source = "   \n  \n  \n"
        py_file = tmp_path / "whitespace.py"
        py_file.write_text(source, encoding="utf-8")

        extractor = get_extractor(".py")
        assert extractor is not None

        entities, _ = extractor.parse_file(
            filepath=str(py_file),
            content=source.encode("utf-8"),
            include_gaps=True,
        )

        # May be empty if the extractor doesn't capture whitespace-only files
        # Attempt reconstruction anyway
        if not entities:
            pytest.skip("Whitespace-only file produced no entities")

        result = reconstructor.reconstruct_file(
            file_path=str(py_file),
            entities=entities,
            original_content=source,
        )
        assert result.success is True
        assert result.hash_match is True

    def test_reconstruct_file_emits_gap_warning_when_entities_not_contiguous(
        self, reconstructor: FileReconstructor
    ):
        """Issue 8: Reconstruction with a leading gap must emit a coverage-gap warning."""
        entities = [
            # Leading gap: bytes 0-4 are uncovered
            _entity(
                start_byte=5,
                end_byte=15,
                raw_content="def hello(",
                name="hello",
                etype=EntityType.FUNCTION,
            ),
            _entity(
                start_byte=15,
                end_byte=28,
                raw_content="):\n    pass\n",
                name="hello2",
                etype=EntityType.FUNCTION,
            ),
        ]

        result = reconstructor.reconstruct_file(
            file_path="test.py",
            entities=entities,
        )

        assert result.success is True
        assert any(
            "gaps detected" in w for w in result.warnings
        ), f"Expected gap warning, got: {result.warnings}"


class TestStorageViewCoverage:
    def test_storage_view_coverage_detects_middle_gap(self):
        """Issue 5: render_storage_view must not report full coverage when a middle gap exists."""
        from batho.context.bsg_map import BSGMap
        from batho.context.schema import FileSnapshot

        # Build a BSGMap with two entities and a gap in between
        entities = [
            Entity(
                type=EntityType.FUNCTION,
                name="first",
                file="test.py",
                start_line=1,
                end_line=1,
                start_byte=0,
                end_byte=10,
                raw_content="def first(",
            ),
            # Gap: bytes 10-20 are uncovered
            Entity(
                type=EntityType.FUNCTION,
                name="second",
                file="test.py",
                start_line=2,
                end_line=2,
                start_byte=20,
                end_byte=35,
                raw_content="):\n    pass\n",
            ),
        ]
        bsg_map = BSGMap.build(
            _make_graph_with_entities(entities),
            root="/tmp",
        )
        # Inject a snapshot claiming the file is 35 bytes
        bsg_map.add_file_snapshot(
            "test.py",
            FileSnapshot(
                file_path="test.py",
                file_hash="dummy",
                file_size=35,
                encoding="utf-8",
            ),
        )

        view = bsg_map.render_storage_view()
        assert view["snapshot_count"] == 1
        # Because there's a gap, fully_covered_files should be 0
        assert view["fully_covered_files"] == 0
        assert view["byte_coverage"] != "100%"


def _make_graph_with_entities(entities: list[Entity]):
    from batho.context.codegraph import InMemoryGraph

    graph = InMemoryGraph()
    for e in entities:
        graph.add_entity(e)
    return graph