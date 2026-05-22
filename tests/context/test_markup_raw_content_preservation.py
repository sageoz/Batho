"""
Test that MarkupConfigExtractor preserves raw_content and content_hash when stamping entities.
"""

import pytest
from batho.context.extractor import MarkupConfigExtractor
from batho.context.schema import Entity, EntityType


class MockMarkupExtractor(MarkupConfigExtractor):
    """Mock markup extractor for testing."""
    
    def _extract_elements(self, source: bytes, filepath: str) -> list[Entity]:
        """Mock implementation that creates entities with raw_content."""
        return [
            Entity(
                type=EntityType.ELEMENT,
                name="test_element",
                file=filepath,
                start_line=1,
                end_line=3,
                start_byte=0,
                end_byte=len(source),
                signature=None,
                metadata={"tag": "div"},
                raw_content=source.decode("utf-8"),
                content_hash="hash123",
            )
        ]
    
    def _extract_references(self, source: bytes, filepath: str, entities: list[Entity]) -> list:
        """Mock implementation."""
        return []


def test_markup_extractor_preserves_raw_content():
    """Test that MarkupConfigExtractor preserves raw_content when stamping with index_id."""
    extractor = MockMarkupExtractor(language="test")
    content = b'<div>test</div>'
    filepath = "test.html"
    index_id = "test_index_123"
    
    entities, relationships = extractor.parse_file(filepath, content, index_id=index_id)
    
    assert len(entities) == 1
    entity = entities[0]
    
    # Verify raw_content is preserved after stamping
    assert entity.raw_content is not None, "raw_content should be preserved"
    assert entity.raw_content == content.decode("utf-8"), "raw_content should match original"
    
    # Verify content_hash is preserved
    assert entity.content_hash == "hash123", "content_hash should be preserved"
    
    # Verify index_id was added to metadata
    assert "bsg.index_id" in entity.metadata, "index_id should be in metadata"
    assert entity.metadata["bsg.index_id"] == index_id, "index_id should match"


def test_markup_extractor_without_index_id():
    """Test that entities work correctly without index_id stamping."""
    extractor = MockMarkupExtractor(language="test")
    content = b'<div>test</div>'
    filepath = "test.html"
    
    entities, relationships = extractor.parse_file(filepath, content)
    
    assert len(entities) == 1
    entity = entities[0]
    
    # Verify raw_content is still present
    assert entity.raw_content is not None, "raw_content should be present"
    assert entity.content_hash == "hash123", "content_hash should be present"
    
    # Verify no index_id in metadata
    assert "bsg.index_id" not in entity.metadata, "index_id should not be in metadata when not provided"
