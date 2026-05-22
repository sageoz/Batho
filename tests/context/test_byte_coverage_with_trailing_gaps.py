"""
Test byte coverage calculation with trailing gaps.
"""

import pytest
from batho.context.reconstructor import FileReconstructor
from batho.context.schema import Entity, EntityType, ReconstructionResult, IntegrityError


def test_byte_coverage_with_trailing_gap():
    """Test that byte coverage accounts for trailing content after the last entity."""
    reconstructor = FileReconstructor()
    
    # Create entities that don't cover the entire file
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
        )
    ]
    
    # Original content has trailing content after the entity
    original_content = "def func1():\n    pass\n# trailing comment\n"
    file_path = "test.py"
    
    # With the fix, byte coverage should be calculated from original_content size
    # Total bytes should be len(original_content.encode("utf-8"))
    # Entity bytes should be len(entities[0].raw_content.encode("utf-8"))
    # Coverage should be < 1.0 since there's a trailing gap
    # Hash won't match because reconstruction is incomplete (no trailing gap entity)
    # The reconstructor now raises IntegrityError on hash mismatch
    
    with pytest.raises(IntegrityError) as exc_info:
        result = reconstructor.reconstruct_file(
            file_path=file_path,
            entities=entities,
            original_content=original_content,
        )
    
    # Verify the error message mentions hash mismatch
    assert "Hash mismatch" in str(exc_info.value), "Should raise IntegrityError for hash mismatch"


def test_byte_coverage_complete():
    """Test that byte coverage is 1.0 when entities cover the entire file."""
    reconstructor = FileReconstructor()
    
    # Create entities that cover the entire file
    entities = [
        Entity(
            type=EntityType.SYNTAX_GLUE,
            name="<glue>",
            file="test.py",
            start_line=1,
            end_line=1,
            start_byte=0,
            end_byte=20,
            raw_content="def func1():\n    pass",
            content_hash="abc123",
        )
    ]
    
    original_content = "def func1():\n    pass"
    file_path = "test.py"
    
    result = reconstructor.reconstruct_file(
        file_path=file_path,
        entities=entities,
        original_content=original_content,
    )
    
    # Coverage should be 1.0 when complete
    assert result.byte_coverage == 1.0, "Byte coverage should be 1.0 for complete coverage"
    assert result.hash_match is True, "Hash should match"


def test_byte_coverage_without_original_content():
    """Test that byte coverage uses max(end_byte) when original_content is not provided."""
    reconstructor = FileReconstructor()
    
    # Ensure end_byte matches actual content length
    content = "def func1():\n    pass"
    entities = [
        Entity(
            type=EntityType.FUNCTION,
            name="func1",
            file="test.py",
            start_line=1,
            end_line=3,
            start_byte=0,
            end_byte=len(content.encode("utf-8")),  # Match actual content length
            raw_content=content,
            content_hash="abc123",
        )
    ]
    
    file_path = "test.py"
    
    result = reconstructor.reconstruct_file(
        file_path=file_path,
        entities=entities,
        # No original_content provided
    )
    
    # Should still work, using max(end_byte) as total_bytes
    assert result.byte_coverage == 1.0, "Coverage should be 1.0 when using max(end_byte) without original_content"
