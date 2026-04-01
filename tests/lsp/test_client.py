"""
Tests for the Universal Headless LSP client.
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock

from batho_core.lsp.registry import LSPRegistry
from batho_core.context.lsp.client import LSPClient
from batho_core.context.lsp.types import ClientCapabilities, Position, TextDocumentIdentifier, DefinitionResponse
from batho_core.context.lsp.errors import LSPTimeoutError, LSPResponseError


@pytest.fixture
def mock_container_spec():
    registry = LSPRegistry()
    return registry.get_version_spec("python", "1.1.350").container


@pytest.mark.asyncio
async def test_client_init(mock_container_spec):
    with patch('batho_core.context.lsp.client.LSPProcessManager') as mock_pm:
        client = LSPClient("python", mock_container_spec)
        assert client.language == "python"
        assert not client._initialized


@pytest.mark.asyncio
async def test_client_timeout(mock_container_spec):
    with patch('batho_core.context.lsp.process_manager.LSPProcessManager.send_message', new_callable=AsyncMock) as mock_send:
        client = LSPClient("python", mock_container_spec, timeout_ms=10)
        
        # We don't run the read loop so the future never resolves
        with pytest.raises(LSPTimeoutError):
            await client._send_request("test_method", {})


@pytest.mark.asyncio
async def test_client_error_response(mock_container_spec):
    with patch('batho_core.context.lsp.process_manager.LSPProcessManager.send_message', new_callable=AsyncMock) as mock_send:
        client = LSPClient("python", mock_container_spec)
        
        def resolve_future():
            for f in client._pending_requests.values():
                if not f.done():
                    f.set_result({
                        "jsonrpc": "2.0",
                        "id": client._request_id - 1,
                        "error": {"code": -32601, "message": "Method not found"}
                    })
                
        asyncio.get_event_loop().call_soon(resolve_future)
        
        with pytest.raises(LSPResponseError) as exc:
            # We mock sending a new request and resolving the pre-set future
            await client._send_request("method", {}, _timeout_ms=100)
            
        assert exc.value.code == -32601
        assert "Method not found" in str(exc.value)


@pytest.mark.asyncio
async def test_definition_caching(mock_container_spec):
    # Test that requesting the same definition hits the cache
    from batho_core.context.lsp.cache import LSPResponseCache
    
    mock_cache = Mock(spec=LSPResponseCache)
    
    # Mock cache get to return a valid cached DefinitionResponse
    mock_cache.get = AsyncMock(return_value=DefinitionResponse(
        raw_json='{}',
        hash='testhash',
        duration_ms=5,
        locations=[]
    ))
    mock_cache.compute_request_hash = Mock(return_value="testhash")
    
    client = LSPClient("python", mock_container_spec, cache=mock_cache)
    
    # Mock capability check
    client.negotiator.has_capability = Mock(return_value=True)
    
    doc = TextDocumentIdentifier(uri="file:///test.py")
    pos = Position(line=1, character=1)
    
    result = await client.textDocument_definition(doc, pos)
    
    # Ensures a cache hit
    mock_cache.get.assert_called_once()
    assert result.hash == "testhash"
