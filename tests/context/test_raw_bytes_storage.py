"""
Test raw_bytes storage and retrieval in Entity model.
"""

import pytest
from batho.context.schema import Entity, EntityType


def test_raw_bytes_storage_and_retrieval():
    """Test that raw_bytes can be stored and retrieved from Entity."""
    original_bytes = b"def func1():\n    pass\n"
    
    entity = Entity(
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
    
    # Verify storage
    assert entity.raw_bytes == original_bytes
    
    # Verify serialization
    storage_dict = entity.to_dict(view="storage")
    assert "raw_bytes" in storage_dict
    assert storage_dict["raw_bytes"] == original_bytes.hex()
    
    # Verify deserialization
    restored_entity = Entity.from_dict(storage_dict)
    assert restored_entity.raw_bytes == original_bytes


def test_raw_bytes_none_by_default():
    """Test that raw_bytes defaults to None when not provided."""
    entity = Entity(
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
    
    assert entity.raw_bytes is None


def test_raw_bytes_with_invalid_utf8():
    """Test that raw_bytes can store invalid UTF-8 sequences."""
    # Create bytes with invalid UTF-8 sequence
    invalid_utf8 = b"def func1():\n\x80\x81\x82\n    pass"
    
    entity = Entity(
        type=EntityType.FUNCTION,
        name="func1",
        file="test.py",
        start_line=1,
        end_line=3,
        start_byte=0,
        end_byte=len(invalid_utf8),
        raw_content=invalid_utf8.decode("utf-8", errors="replace"),  # Decoded with replacement
        content_hash="abc123",
        raw_bytes=invalid_utf8,  # Store original bytes
    )
    
    # Verify raw_bytes preserves the original invalid bytes
    assert entity.raw_bytes == invalid_utf8
    
    # Verify raw_content has replacement characters
    assert "\ufffd" in entity.raw_content  # Unicode replacement character
    
    # Verify round-trip through serialization preserves raw_bytes
    storage_dict = entity.to_dict(view="storage")
    restored_entity = Entity.from_dict(storage_dict)
    assert restored_entity.raw_bytes == invalid_utf8


def test_raw_bytes_hex_serialization():
    """Test that raw_bytes is serialized as hex string for JSON compatibility."""
    entity = Entity(
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
    
    storage_dict = entity.to_dict(view="storage")
    
    # Verify it's a hex string (not bytes)
    assert isinstance(storage_dict["raw_bytes"], str)
    
    # Verify it's valid hex
    try:
        bytes.fromhex(storage_dict["raw_bytes"])
    except ValueError:
        pytest.fail("raw_bytes should be a valid hex string")
