"""
Tests for LSP cache and merger.
"""

import pytest
from unittest.mock import AsyncMock, Mock

from batho_core.context.codegraph import InMemoryGraph
from batho_core.context.schema import Entity, EntityType, Relationship, RelationshipType
from batho_core.context.lsp.client import LSPClient
from batho_core.context.lsp.merger import LSPASTMerger
from batho_core.context.lsp.resolver import CrossFileResolver
from batho_core.context.lsp.types import DefinitionResponse, Location, Range, Position


@pytest.mark.asyncio
async def test_resolver_cross_file():
    graph = InMemoryGraph()
    
    e1 = Entity(
        type=EntityType.FUNCTION,
        name="def_target",
        file="target.py",
        start_line=5,
        end_line=10,
        start_byte=100,
        end_byte=200
    )
    graph.add_entity(e1)
    
    rel = Relationship(
        source_id="file://source.py",
        target_id="unresolved:def_target",
        type=RelationshipType.IMPORTS,
        metadata={"line_number": 1}
    )
    graph.add_relationship(rel)
    
    mock_client = Mock(spec=LSPClient)
    mock_negotiator = Mock()
    mock_negotiator.supports_definition.return_value = True
    mock_client.negotiator = mock_negotiator
    
    # Mock textDocument/definition response
    resp = DefinitionResponse(
        raw_json='{}',
        hash='test',
        duration_ms=5,
        locations=[
            Location(
                uri="file://target.py",
                range=Range(start=Position(line=4, character=0), end=Position(line=9, character=0))
            )
        ]
    )
    mock_client.textDocument_definition = AsyncMock(return_value=resp)
    
    resolver = CrossFileResolver(mock_client)
    await resolver.resolve_async(graph)
    
    # The unresolved relationship should be replaced
    assert len(graph.relationships) == 1
    new_rel = graph.relationships[0]
    
    assert new_rel.target_id == e1.id
    assert new_rel.source_id == "file://source.py"


@pytest.mark.asyncio
async def test_merger_annotation():
    graph = InMemoryGraph()
    
    e1 = Entity(
        type=EntityType.FUNCTION,
        name="test_func",
        file="source.py",
        start_line=1,
        end_line=5,
        start_byte=0,
        end_byte=50
    )
    graph.add_entity(e1)
    
    mock_client = Mock(spec=LSPClient)
    mock_negotiator = Mock()
    mock_negotiator.supports_definition.return_value = True
    mock_negotiator.supports_hover.return_value = False
    mock_client.negotiator = mock_negotiator
    
    resp = DefinitionResponse(
        raw_json='{}',
        hash='hash123',
        duration_ms=5,
        locations=[]
    )
    mock_client.textDocument_definition = AsyncMock(return_value=resp)
    
    merger = LSPASTMerger(mock_client)
    await merger.merge_async(graph, "source.py")
    
    updated_e1 = graph.get_entity(e1.id)
    assert updated_e1.metadata.get("lsp_definition_hash") == "hash123"

@pytest.mark.asyncio
async def test_call_chain_analysis_creates_calls_relationships():
    graph = InMemoryGraph()
    e1 = Entity(
        type=EntityType.FUNCTION,
        name="target",
        file="file1.py",
        start_line=1,
        end_line=5,
        start_byte=0,
        end_byte=10
    )
    graph.add_entity(e1)
    
    mock_client = Mock(spec=LSPClient)
    mock_negotiator = Mock()
    mock_negotiator.supports_definition.return_value = False
    mock_negotiator.supports_hover.return_value = False
    mock_negotiator.supports_references.return_value = True
    mock_client.negotiator = mock_negotiator
    
    # Mock adapter
    mock_adapter = Mock()
    mock_adapter.extract_call_chain_info.return_value = ["file://caller.py"]
    mock_client.adapter = mock_adapter
    
    mock_client.textDocument_references = AsyncMock(return_value=[{"uri": "file://caller.py"}])
    
    merger = LSPASTMerger(mock_client)
    await merger.merge_async(graph, "file1.py")
    
    # Check that a CALLS relationship was created from caller.py to e1
    call_rels = [r for r in graph.relationships if r.type == RelationshipType.CALLS]
    assert len(call_rels) == 1
    assert call_rels[0].source_id == "file://caller.py"
    assert call_rels[0].target_id == e1.id
