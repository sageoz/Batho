"""Tests for _serialize_extraction_result SYNTAX_GLUE filtering in the agent view.

Verifies that SYNTAX_GLUE entities are excluded from the agent_blob (matching
the BSGViewType.AGENT spec) while remaining present in the storage_blob and
being excluded from hollow_topology.
"""

from __future__ import annotations

import msgpack
import pytest

from batho.core.schemas import Entity, EntityType, Relationship, RelationshipType
from batho.modules.extraction.pipeline import _serialize_extraction_result


def _make_entity(
    name: str,
    entity_type: EntityType,
    filepath: str = "test.py",
    start_line: int = 1,
    end_line: int = 10,
    start_byte: int = 0,
    end_byte: int = 100,
) -> Entity:
    return Entity(
        type=entity_type,
        name=name,
        file=filepath,
        start_line=start_line,
        end_line=end_line,
        start_byte=start_byte,
        end_byte=end_byte,
    )


class TestSyntaxGlueFiltering:
    """Verify SYNTAX_GLUE is excluded from agent view but preserved in storage view."""

    @pytest.fixture
    def zstd_compressor(self):
        import zstandard as zstd
        return zstd.ZstdCompressor(level=3)

    @pytest.fixture
    def zstd_decompressor(self):
        import zstandard as zstd
        return zstd.ZstdDecompressor()

    @pytest.fixture
    def mixed_entities(self):
        return [
            _make_entity("my_func", EntityType.FUNCTION, start_line=1, end_line=5, start_byte=0, end_byte=50),
            _make_entity("MyClass", EntityType.CLASS, start_line=6, end_line=10, start_byte=51, end_byte=100),
            _make_entity("gap_0", EntityType.SYNTAX_GLUE, start_line=5, end_line=6, start_byte=50, end_byte=51),
        ]

    def test_agent_blob_excludes_syntax_glue(
        self, zstd_compressor, zstd_decompressor, mixed_entities
    ) -> None:
        hollow, rels, agent_blob, storage_blob, _, _ = _serialize_extraction_result(
            entities=mixed_entities,
            relationships=[],
            filepath="test.py",
            content_hash="abc123",
            zstd_compressor=zstd_compressor,
        )

        agent_data = msgpack.unpackb(zstd_decompressor.decompress(agent_blob))
        agent_types = [e.get("ty") for e in agent_data.get("e", [])]

        assert "SYNTAX_GLUE" not in agent_types, (
            f"SYNTAX_GLUE leaked into agent view: {agent_types}"
        )
        assert "FUNCTION" in agent_types
        assert "CLASS" in agent_types

    def test_storage_blob_preserves_syntax_glue(
        self, zstd_compressor, zstd_decompressor, mixed_entities
    ) -> None:
        hollow, rels, agent_blob, storage_blob, _, _ = _serialize_extraction_result(
            entities=mixed_entities,
            relationships=[],
            filepath="test.py",
            content_hash="abc123",
            zstd_compressor=zstd_compressor,
        )

        storage_data = msgpack.unpackb(zstd_decompressor.decompress(storage_blob))
        storage_types = [e.get("ty") for e in storage_data.get("e", [])]

        assert "SYNTAX_GLUE" in storage_types, (
            f"SYNTAX_GLUE missing from storage view: {storage_types}"
        )

    def test_hollow_topology_excludes_syntax_glue(
        self, zstd_compressor, mixed_entities
    ) -> None:
        hollow, rels, agent_blob, storage_blob, _, _ = _serialize_extraction_result(
            entities=mixed_entities,
            relationships=[],
            filepath="test.py",
            content_hash="abc123",
            zstd_compressor=zstd_compressor,
        )

        hollow_data = msgpack.unpackb(hollow)
        hollow_types = [n.get("type") for n in hollow_data]

        assert "syntax_glue" not in hollow_types, (
            f"SYNTAX_GLUE leaked into hollow topology: {hollow_types}"
        )

    def test_only_syntax_glue_entities(self, zstd_compressor, zstd_decompressor) -> None:
        """Edge case: all entities are SYNTAX_GLUE — agent view should be empty."""
        glue_entities = [
            _make_entity("gap_0", EntityType.SYNTAX_GLUE, start_line=1, end_line=2, start_byte=0, end_byte=10),
            _make_entity("gap_1", EntityType.SYNTAX_GLUE, start_line=2, end_line=3, start_byte=10, end_byte=20),
        ]

        hollow, rels, agent_blob, storage_blob, _, _ = _serialize_extraction_result(
            entities=glue_entities,
            relationships=[],
            filepath="test.py",
            content_hash="abc123",
            zstd_compressor=zstd_compressor,
        )

        agent_data = msgpack.unpackb(zstd_decompressor.decompress(agent_blob))
        assert len(agent_data.get("e", [])) == 0, (
            f"Agent view should be empty for all-SYNTAX_GLUE input, got: {agent_data}"
        )

        storage_data = msgpack.unpackb(zstd_decompressor.decompress(storage_blob))
        assert len(storage_data.get("e", [])) == 2
