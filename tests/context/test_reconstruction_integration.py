"""
Integration tests for BSG bidirectional reconstruction pipeline.

Tests cover:
- Reconstruction with various file types (Python, JSON, YAML, Markdown)
- Reconstruction with UTF-8 encoding errors
- Reconstruction with zero-length files
- Reconstruction with files containing only gaps (no semantic entities)
- Hash verification with verify_integrity enabled/disabled
- Reconstruction from cached entities with/without raw_bytes
- Coverage calculation accuracy
- SYNTAX_GLUE entity classification
"""

from pathlib import Path

import pytest

from batho.context.extractor import ASTExtractor
from batho.context.reconstructor import FileReconstructor, IntegrityError, ReconstructionError
from batho.context.schema import Entity, EntityType
from batho.utils.hash import compute_bytes_hash


class TestReconstructionIntegration:
    """Integration tests for the reconstruction pipeline."""

    def test_reconstruct_python_file(self, tmp_path: Path) -> None:
        """Test reconstruction of a Python file with semantic entities and gaps."""
        # Create a test Python file
        test_file = tmp_path / "test.py"
        content = b'# Comment\n\ndef foo():\n    pass\n\n# Another comment\n'
        test_file.write_bytes(content)
        content_hash = compute_bytes_hash(content)

        # Create entities (simulating extraction) with correct byte ranges
        entities = [
            Entity(
                type=EntityType.SYNTAX_GLUE,
                name="<glue>",
                file=str(test_file),
                start_line=1,
                end_line=2,
                start_byte=0,
                end_byte=11,  # "# Comment\n\n" is 11 bytes
                raw_content="# Comment\n\n",
                content_hash=compute_bytes_hash("# Comment\n\n".encode("utf-8")),
            ),
            Entity(
                type=EntityType.FUNCTION,
                name="foo",
                file=str(test_file),
                start_line=3,
                end_line=4,
                start_byte=11,
                end_byte=30,  # "def foo():\n    pass" is 19 bytes
                raw_content="def foo():\n    pass",
                content_hash=compute_bytes_hash("def foo():\n    pass".encode("utf-8")),
            ),
            Entity(
                type=EntityType.SYNTAX_GLUE,
                name="<glue>",
                file=str(test_file),
                start_line=5,
                end_line=7,
                start_byte=30,
                end_byte=42,  # "\n\n# Another comment\n" is 12 bytes
                raw_content="\n\n# Another comment\n",
                content_hash=compute_bytes_hash("\n\n# Another comment\n".encode("utf-8")),
            ),
        ]
        entities.sort(key=lambda e: e.start_byte)

        # Reconstruct with original_content for accurate coverage calculation
        reconstructor = FileReconstructor()
        result = reconstructor.reconstruct_file(
            str(test_file), entities, original_hash=content_hash, original_content=content.decode("utf-8")
        )

        assert result.success
        assert result.hash_match
        assert result.reconstructed_content.encode("utf-8") == content
        assert result.byte_coverage == 1.0
        assert result.gap_count == 2

    def test_reconstruct_json_file(self, tmp_path: Path) -> None:
        """Test reconstruction of a JSON file."""
        test_file = tmp_path / "test.json"
        content = b'{"key": "value"}\n'
        test_file.write_bytes(content)
        content_hash = compute_bytes_hash(content)

        entities = [
            Entity(
                type=EntityType.SETTING,
                name="key",
                file=str(test_file),
                start_line=1,
                end_line=1,
                start_byte=0,
                end_byte=17,
                raw_content='{"key": "value"}',
                content_hash=compute_bytes_hash('{"key": "value"}'.encode("utf-8")),
            ),
            Entity(
                type=EntityType.SYNTAX_GLUE,
                name="<glue>",
                file=str(test_file),
                start_line=1,
                end_line=2,
                start_byte=17,
                end_byte=18,
                raw_content="\n",
                content_hash=compute_bytes_hash("\n".encode("utf-8")),
            ),
        ]
        entities.sort(key=lambda e: e.start_byte)

        reconstructor = FileReconstructor()
        result = reconstructor.reconstruct_file(str(test_file), entities, original_hash=content_hash)

        assert result.success
        assert result.hash_match

    def test_reconstruct_with_utf8_errors(self, tmp_path: Path) -> None:
        """Test reconstruction when UTF-8 decode errors occur."""
        test_file = tmp_path / "test.txt"
        # Create content with invalid UTF-8 sequence
        content = b"valid text\xff\xfe invalid"
        test_file.write_bytes(content)
        content_hash = compute_bytes_hash(content)

        # Entity with raw_bytes preserved for lossless reconstruction
        entities = [
            Entity(
                type=EntityType.SYNTAX_GLUE,
                name="<glue>",
                file=str(test_file),
                start_line=1,
                end_line=1,
                start_byte=0,
                end_byte=len(content),
                raw_content="valid text\ufffd\ufffd invalid",  # Decoded with replacement chars
                content_hash=content_hash,
                raw_bytes=content,  # Preserve original bytes
            ),
        ]

        reconstructor = FileReconstructor()
        result = reconstructor.reconstruct_file(str(test_file), entities, original_hash=content_hash)

        assert result.success
        assert result.hash_match
        # Hash match confirms lossless reconstruction at byte level
        # The string representation may have replacement characters, but raw_bytes preserves exact bytes

    def test_reconstruct_zero_length_file(self, tmp_path: Path) -> None:
        """Test reconstruction of an empty file raises error (no entities to reconstruct)."""
        test_file = tmp_path / "empty.txt"
        content = b""
        test_file.write_bytes(content)
        content_hash = compute_bytes_hash(content)

        reconstructor = FileReconstructor()
        # Empty files have no entities to reconstruct, should raise error
        with pytest.raises(ReconstructionError, match="No entities provided"):
            reconstructor.reconstruct_file(str(test_file), [], original_hash=content_hash)

    def test_reconstruct_file_with_only_gaps(self, tmp_path: Path) -> None:
        """Test reconstruction when file has no semantic entities, only gaps."""
        test_file = tmp_path / "comments_only.txt"
        content = b"# Just comments\n# More comments\n"
        test_file.write_bytes(content)
        content_hash = compute_bytes_hash(content)

        entities = [
            Entity(
                type=EntityType.SYNTAX_GLUE,
                name="<glue>",
                file=str(test_file),
                start_line=1,
                end_line=2,
                start_byte=0,
                end_byte=len(content),
                raw_content=content.decode("utf-8"),
                content_hash=content_hash,
            ),
        ]

        reconstructor = FileReconstructor()
        result = reconstructor.reconstruct_file(str(test_file), entities, original_hash=content_hash)

        assert result.success
        assert result.hash_match
        assert result.gap_count == 1

    def test_hash_verification_enabled(self, tmp_path: Path) -> None:
        """Test hash verification when verify_integrity is enabled."""
        test_file = tmp_path / "test.py"
        content = b"def foo(): pass\n"
        test_file.write_bytes(content)
        correct_hash = compute_bytes_hash(content)
        wrong_hash = "0" * 64

        entities = [
            Entity(
                type=EntityType.FUNCTION,
                name="foo",
                file=str(test_file),
                start_line=1,
                end_line=1,
                start_byte=0,
                end_byte=len(content),
                raw_content=content.decode("utf-8"),
                content_hash=correct_hash,
            ),
        ]

        reconstructor = FileReconstructor()

        # Should succeed with correct hash
        result = reconstructor.reconstruct_file(str(test_file), entities, original_hash=correct_hash)
        assert result.success
        assert result.hash_match

        # Should fail with wrong hash
        with pytest.raises(IntegrityError):
            reconstructor.reconstruct_file(str(test_file), entities, original_hash=wrong_hash)

    def test_hash_verification_disabled(self, tmp_path: Path) -> None:
        """Test reconstruction without hash verification."""
        test_file = tmp_path / "test.py"
        content = b"def foo(): pass\n"
        test_file.write_bytes(content)

        entities = [
            Entity(
                type=EntityType.FUNCTION,
                name="foo",
                file=str(test_file),
                start_line=1,
                end_line=1,
                start_byte=0,
                end_byte=len(content),
                raw_content=content.decode("utf-8"),
                content_hash=compute_bytes_hash(content),
            ),
        ]

        reconstructor = FileReconstructor()
        # No original_hash provided - should still succeed
        result = reconstructor.reconstruct_file(str(test_file), entities)
        assert result.success
        assert not result.hash_match  # No hash to compare against

    def test_coverage_calculation_with_gaps(self, tmp_path: Path) -> None:
        """Test accurate coverage calculation when gaps are present."""
        test_file = tmp_path / "test.py"
        content = b"# Comment\n\ndef foo(): pass\n"
        test_file.write_bytes(content)

        entities = [
            Entity(
                type=EntityType.SYNTAX_GLUE,
                name="<glue>",
                file=str(test_file),
                start_line=1,
                end_line=2,
                start_byte=0,
                end_byte=11,  # "# Comment\n\n" is 11 bytes
                raw_content="# Comment\n\n",
                content_hash=compute_bytes_hash("# Comment\n\n".encode("utf-8")),
            ),
            Entity(
                type=EntityType.FUNCTION,
                name="foo",
                file=str(test_file),
                start_line=3,
                end_line=3,
                start_byte=11,
                end_byte=26,  # "def foo(): pass\n" is 15 bytes
                raw_content="def foo(): pass\n",
                content_hash=compute_bytes_hash("def foo(): pass\n".encode("utf-8")),
            ),
        ]
        entities.sort(key=lambda e: e.start_byte)

        reconstructor = FileReconstructor()
        result = reconstructor.reconstruct_file(str(test_file), entities, original_content=content.decode("utf-8"))

        assert result.success
        assert result.byte_coverage == 1.0

    def test_coverage_calculation_partial(self, tmp_path: Path) -> None:
        """Test coverage calculation when trailing content is missing."""
        test_file = tmp_path / "test.py"
        content = b"# Comment\n\ndef foo(): pass\n# Trailing\n"
        test_file.write_bytes(content)

        # Entities don't cover the trailing comment
        entities = [
            Entity(
                type=EntityType.SYNTAX_GLUE,
                name="<glue>",
                file=str(test_file),
                start_line=1,
                end_line=2,
                start_byte=0,
                end_byte=11,  # "# Comment\n\n" is 11 bytes
                raw_content="# Comment\n\n",
                content_hash=compute_bytes_hash("# Comment\n\n".encode("utf-8")),
            ),
            Entity(
                type=EntityType.FUNCTION,
                name="foo",
                file=str(test_file),
                start_line=3,
                end_line=3,
                start_byte=11,
                end_byte=26,  # "def foo(): pass\n" is 15 bytes
                raw_content="def foo(): pass\n",
                content_hash=compute_bytes_hash("def foo(): pass\n".encode("utf-8")),
            ),
        ]
        entities.sort(key=lambda e: e.start_byte)

        reconstructor = FileReconstructor()
        # The reconstructor now raises IntegrityError on hash mismatch
        # when original_content is provided and reconstruction is incomplete
        with pytest.raises(IntegrityError) as exc_info:
            result = reconstructor.reconstruct_file(str(test_file), entities, original_content=content.decode("utf-8"))
        
        # Verify the error is about hash mismatch
        assert "Hash mismatch" in str(exc_info.value)

    def test_reconstruct_with_raw_bytes_priority(self, tmp_path: Path) -> None:
        """Test that raw_bytes is used over raw_content when both are present."""
        test_file = tmp_path / "test.txt"
        content = b"original bytes"
        test_file.write_bytes(content)
        content_hash = compute_bytes_hash(content)

        entities = [
            Entity(
                type=EntityType.SYNTAX_GLUE,
                name="<glue>",
                file=str(test_file),
                start_line=1,
                end_line=1,
                start_byte=0,
                end_byte=len(content),
                raw_content="different string",  # Different from raw_bytes
                content_hash=content_hash,
                raw_bytes=content,  # Should be used for reconstruction
            ),
        ]

        reconstructor = FileReconstructor()
        result = reconstructor.reconstruct_file(str(test_file), entities, original_hash=content_hash)

        assert result.success
        assert result.hash_match
        # Should use raw_bytes, not raw_content
        assert result.reconstructed_content.encode("utf-8") == content

    def test_reconstruct_no_entities_raises_error(self, tmp_path: Path) -> None:
        """Test that reconstruction raises error when no entities are provided."""
        test_file = tmp_path / "test.py"
        test_file.write_bytes(b"content")

        reconstructor = FileReconstructor()
        with pytest.raises(ReconstructionError, match="No entities provided"):
            reconstructor.reconstruct_file(str(test_file), [])

    def test_gap_entity_missing_raw_content_raises_error(self, tmp_path: Path) -> None:
        """Test that gap entities without raw_content raise error."""
        test_file = tmp_path / "test.py"
        test_file.write_bytes(b"content")

        entities = [
            Entity(
                type=EntityType.SYNTAX_GLUE,
                name="<glue>",
                file=str(test_file),
                start_line=1,
                end_line=1,
                start_byte=0,
                end_byte=7,
                raw_content=None,  # Missing required field
                content_hash="",
            ),
        ]

        reconstructor = FileReconstructor()
        # Entities without raw_content are now skipped during selection,
        # resulting in "No covering entities" error instead of "missing raw_content"
        with pytest.raises(ReconstructionError, match="No covering entities"):
            reconstructor.reconstruct_file(str(test_file), entities)
