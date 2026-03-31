"""
LSP Protocol data structure and Pydantic models.

Ensures no raw dicts escape the LSP integration layer.
"""

from __future__ import annotations

from datetime import datetime
from enum import IntEnum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Base Protocol Types
# ---------------------------------------------------------------------------


class Position(BaseModel):
    """0-based position in a text document."""
    line: int
    character: int

    def __lt__(self, other: Position) -> bool:
        return (self.line, self.character) < (other.line, other.character)
        
    def __le__(self, other: Position) -> bool:
        return (self.line, self.character) <= (other.line, other.character)


class Range(BaseModel):
    """Range of positions in a document."""
    start: Position
    end: Position

    def contains(self, position: Position) -> bool:
        """Check if position is contained within range."""
        return self.start <= position and position < self.end


class Location(BaseModel):
    """Location of a symbol across files."""
    uri: str
    range: Range


class TextDocumentIdentifier(BaseModel):
    """Identifies a document via URI."""
    uri: str

    @field_validator('uri')
    @classmethod
    def validate_uri(cls, v: str) -> str:
        if not v.startswith(('file://', 'untitled://', 'inmemory://')):
            raise ValueError(f"Invalid URI scheme: {v}")
        return v


class SymbolKind(IntEnum):
    """LSP Symbol Kinds."""
    FILE = 1
    MODULE = 2
    NAMESPACE = 3
    PACKAGE = 4
    CLASS = 5
    METHOD = 6
    PROPERTY = 7
    FIELD = 8
    CONSTRUCTOR = 9
    ENUM = 10
    INTERFACE = 11
    FUNCTION = 12
    VARIABLE = 13
    CONSTANT = 14
    STRING = 15
    NUMBER = 16
    BOOLEAN = 17
    ARRAY = 18
    OBJECT = 19
    KEY = 20
    NULL = 21
    ENUMMEMBER = 22
    STRUCT = 23
    EVENT = 24
    OPERATOR = 25
    TYPEPARAMETER = 26


class DocumentSymbol(BaseModel):
    """Hierarchical symbol information."""
    name: str
    detail: Optional[str] = None
    kind: SymbolKind
    range: Range
    selectionRange: Range
    children: List[DocumentSymbol] = Field(default_factory=list)
    # Batho extension for deterministic auditing
    hash: Optional[str] = None


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


class LSPResponse(BaseModel):
    """Base internal tracking representation for responses."""
    raw_json: str
    hash: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    duration_ms: int


class DefinitionResponse(LSPResponse):
    """Definition / declaration response."""
    locations: List[Location]


class ReferencesResponse(LSPResponse):
    """References response."""
    locations: List[Location]
    count: int = 0


class HoverResponse(LSPResponse):
    """Hover documentation response."""
    contents: Union[str, Dict[str, Any]]
    range: Optional[Range] = None


class DocumentSymbolResponse(LSPResponse):
    """Document symbols response."""
    symbols: List[DocumentSymbol]


class BatchResponse(BaseModel):
    """Wrapper for multiple concurrent resolves."""
    results: Dict[str, LSPResponse]
    combined_hash: str
    completed: int
    failed: int
    total_duration_ms: int


# ---------------------------------------------------------------------------
# Config Models
# ---------------------------------------------------------------------------


class ClientCapabilities(BaseModel):
    """Reported Client Capabilities given to Server."""
    textDocument: Dict[str, Any] = Field(default_factory=dict)
    workspace: Dict[str, Any] = Field(default_factory=dict)
    experimental: Dict[str, Any] = Field(default_factory=dict)
    
    # Batho extensions
    batho_deterministic_mode: bool = True
    batho_include_raw_responses: bool = False

    @classmethod
    def default(cls) -> "ClientCapabilities":
        return cls(
            textDocument={
                "synchronization": {"dynamicRegistration": False, "willSave": False, "willSaveWaitUntil": False, "didSave": True},
                "completion": {"dynamicRegistration": False},
                "hover": {"dynamicRegistration": False},
                "definition": {"dynamicRegistration": False, "linkSupport": True},
                "references": {"dynamicRegistration": False},
                "documentSymbol": {"dynamicRegistration": False, "hierarchicalDocumentSymbolSupport": True},
            },
            workspace={
                "applyEdit": False,
                "workspaceEdit": {"documentChanges": False},
                "symbol": {"dynamicRegistration": False},
            }
        )
