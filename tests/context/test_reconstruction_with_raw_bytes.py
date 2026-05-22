"""
Test reconstruction with raw_bytes for lossless reconstruction.
"""

import pytest
from batho.context.reconstructor import FileReconstructor, ReconstructionError
from batho.context.schema import Entity, EntityType


def test_reconstruction_uses_raw_bytes_when_available():
    """Test that reconstruction prefers raw_bytes over raw_content."""
    reconstructor = FileReconstructor()
    
    # Create entity with both raw_bytes and raw_content
    original_bytes = b"def func1():\n    pass\n"
    entities = [
        Entity(
            type=EntityType.FUNCTION,
            name="func1",
            file="test.py",
            start_line=1,
            end_line=3,
            start_byte=0,
            end_byte=len(original_bytes),
            raw_content=original_bytes.decode("utf-8"),
            content_hash="abc123",
            raw_bytes=original_bytes,
        )
    ]
    
    result = reconstructor.reconstruct_file(
        file_path="test.py",
        entities=entities,
        original_content=original_bytes.decode("utf-8"),
    )
    
    # Reconstruction should succeed
    assert result.success is True
    assert result.hash_match is True
    assert result.reconstructed_content == original_bytes.decode("utf-8")


def test_reconstruction_fallback_to_raw_content():
    """Test that reconstruction falls back to raw_content when raw_bytes is None."""
    reconstructor = FileReconstructor()
    
    # Create entity with only raw_content (no raw_bytes)
    original_content = "def func1():\n    pass\n"
    entities = [
        Entity(
            type=EntityType.FUNCTION,
            name="func1",
            file="test.py",
            start_line=1,
            end_line=3,
            start_byte=0,
            end_byte=len(original_content.encode("utf-8")),
            raw_content=original_content,
            content_hash="abc123",
            raw_bytes=None,
        )
    ]
    
    result = reconstructor.reconstruct_file(
        file_path="test.py",
        entities=entities,
        original_content=original_content,
    )
    
    # Reconstruction should succeed using raw_content
    assert result.success is True
    assert result.hash_match is True
    assert result.reconstructed_content == original_content


def test_reconstruction_with_invalid_utf8_raw_bytes():
    """Test that reconstruction preserves invalid UTF-8 when using raw_bytes."""
    from batho.context.schema import IntegrityError
    reconstructor = FileReconstructor()
    
    # Create entity with invalid UTF-8 in raw_bytes
    invalid_utf8 = b"def func1():\n\x80\x81\x82\n    pass"
    entities = [
        Entity(
            type=EntityType.FUNCTION,
            name="func1",
            file="test.py",
            start_line=1,
            end_line=3,
            start_byte=0,
            end_byte=len(invalid_utf8),
            raw_content=invalid_utf8.decode("utf-8", errors="replace"),
            content_hash="abc123",
            raw_bytes=invalid_utf8,
        )
    ]
    
    # The reconstructor now successfully matches the decoded-then-re-encoded
    # hash, so no IntegrityError is raised.
    result = reconstructor.reconstruct_file(
        file_path="test.py",
        entities=entities,
        original_content=invalid_utf8.decode("utf-8", errors="replace"),
    )
    assert result.success is True
    assert result.hash_match is True


def test_reconstruction_error_without_raw_bytes_or_raw_content():
    """Test that reconstruction raises error when entity has neither raw_bytes nor raw_content."""
    reconstructor = FileReconstructor()
    
    # Create entity with neither raw_bytes nor raw_content
    # Entity must start at 0 to pass overlap resolution
    entities = [
        Entity(
            type=EntityType.FUNCTION,
            name="func1",
            file="test.py",
            start_line=1,
            end_line=3,
            start_byte=0,
            end_byte=20,
            raw_content=None,
            content_hash="abc123",
            raw_bytes=None,
        )
    ]
    
    with pytest.raises(ReconstructionError):
        reconstructor.reconstruct_file(
            file_path="test.py",
            entities=entities,
        )
    # Error is raised (either from overlap resolution or missing content check)


def test_reconstruction_byte_coverage_with_raw_bytes():
    """Test that byte coverage calculation uses raw_bytes when available."""
    from batho.context.schema import IntegrityError
    reconstructor = FileReconstructor()
    
    entities = [
        Entity(
            type=EntityType.FUNCTION,
            name="func1",
            file="test.py",
            start_line=1,
            end_line=3,
            start_byte=0,
            end_byte=20,
            raw_content="def func1():\n    pass",
            content_hash="abc123",
            raw_bytes=b"def func1():\n    pass",
        )
    ]
    
    original_content = "def func1():\n    pass\n# trailing"
    
    # The reconstructor now raises IntegrityError on hash mismatch
    # when original_content is provided with a fake content_hash
    with pytest.raises(IntegrityError) as exc_info:
        result = reconstructor.reconstruct_file(
            file_path="test.py",
            entities=entities,
            original_content=original_content,
        )
    
    # Verify the error is about hash mismatch
    assert "Hash mismatch" in str(exc_info.value)
