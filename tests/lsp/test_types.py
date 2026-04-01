"""
Tests for LSP types.
"""

from batho_core.context.lsp.types import (
    Position, Range, Location, TextDocumentIdentifier,
    DocumentSymbol, SymbolKind, ClientCapabilities
)


def test_position_comparison():
    p1 = Position(line=1, character=5)
    p2 = Position(line=1, character=10)
    p3 = Position(line=2, character=0)
    
    assert p1 < p2
    assert p2 < p3
    assert p1 <= p2
    assert p1 <= p1


def test_range_contains():
    r = Range(
        start=Position(line=5, character=0),
        end=Position(line=10, character=0)
    )
    
    # Inside
    assert r.contains(Position(line=5, character=5))
    assert r.contains(Position(line=7, character=0))
    
    # Boundary (inclusive start, exclusive end)
    assert r.contains(Position(line=5, character=0))
    assert not r.contains(Position(line=10, character=0))
    
    # Outside
    assert not r.contains(Position(line=4, character=99))
    assert not r.contains(Position(line=11, character=0))


def test_text_document_identifier_validation():
    import pytest
    from pydantic import ValidationError
    
    doc = TextDocumentIdentifier(uri="file:///path/to/file.py")
    assert doc.uri == "file:///path/to/file.py"
    
    with pytest.raises(ValidationError):
        # Invalid scheme
        TextDocumentIdentifier(uri="http://example.com/file.py")


def test_client_capabilities_default():
    caps = ClientCapabilities.default()
    
    assert caps.batho_deterministic_mode is True
    assert caps.textDocument["definition"]["linkSupport"] is True
    assert caps.textDocument["documentSymbol"]["hierarchicalDocumentSymbolSupport"] is True
