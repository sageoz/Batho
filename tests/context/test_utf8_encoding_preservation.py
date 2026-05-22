"""
Test UTF-8 encoding preservation with raw_bytes field.
"""

import pytest
from batho.context.schema import Entity, EntityType


def test_entity_raw_bytes_field():
    """Test that Entity model accepts raw_bytes field."""
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
    
    assert entity.raw_bytes is not None
    assert entity.raw_bytes == b"def func1():\n    pass"


def test_entity_raw_bytes_optional():
    """Test that raw_bytes field is optional."""
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


def test_entity_to_dict_includes_raw_bytes_in_storage_view():
    """Test that to_dict includes raw_bytes in storage view."""
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
    
    # Storage view should include raw_bytes as hex string
    storage_dict = entity.to_dict(view="storage")
    assert "raw_bytes" in storage_dict
    assert storage_dict["raw_bytes"] == entity.raw_bytes.hex()
    
    # Agent view should not include raw_bytes
    agent_dict = entity.to_dict(view="agent")
    assert "raw_bytes" not in agent_dict


def test_entity_from_dict_deserializes_raw_bytes():
    """Test that from_dict deserializes raw_bytes from hex string."""
    raw_bytes = b"def func1():\n    pass"
    data = {
        "type": "FUNCTION",
        "name": "func1",
        "file": "test.py",
        "start_line": 1,
        "end_line": 3,
        "start_byte": 0,
        "end_byte": 20,
        "raw_content": "def func1():\n    pass",
        "content_hash": "abc123",
        "raw_bytes": raw_bytes.hex(),
    }
    
    entity = Entity.from_dict(data)
    
    assert entity.raw_bytes is not None
    assert entity.raw_bytes == raw_bytes


def test_entity_from_dict_handles_missing_raw_bytes():
    """Test that from_dict handles missing raw_bytes gracefully."""
    data = {
        "type": "FUNCTION",
        "name": "func1",
        "file": "test.py",
        "start_line": 1,
        "end_line": 3,
        "start_byte": 0,
        "end_byte": 20,
        "raw_content": "def func1():\n    pass",
        "content_hash": "abc123",
    }
    
    entity = Entity.from_dict(data)
    
    assert entity.raw_bytes is None


def test_entity_from_dict_handles_empty_raw_bytes():
    """Test that from_dict handles empty raw_bytes string."""
    data = {
        "type": "FUNCTION",
        "name": "func1",
        "file": "test.py",
        "start_line": 1,
        "end_line": 3,
        "start_byte": 0,
        "end_byte": 20,
        "raw_content": "def func1():\n    pass",
        "content_hash": "abc123",
        "raw_bytes": "",
    }
    
    entity = Entity.from_dict(data)
    
    assert entity.raw_bytes == b""
