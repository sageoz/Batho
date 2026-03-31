"""
Universal Headless LSP Client package.
"""

from .types import (
    Position, Range, Location, TextDocumentIdentifier, SymbolKind,
    DocumentSymbol, LSPResponse, DefinitionResponse, ReferencesResponse,
    HoverResponse, DocumentSymbolResponse, BatchResponse,
    ClientCapabilities
)
from batho_core.lsp.registry import ContainerSpec
from .errors import (
    LSPError, LSPConnectionError, LSPTimeoutError,
    LSPResponseError, LSPNotInitializedError, LSPProcessError,
    LSPCapabilityError
)
from .client import LSPClient
from .capabilities import CapabilityNegotiator
from .cache import LSPResponseCache
from .hasher import LSPResponseHasher
from .process_manager import LSPProcessManager, LSPProcessState

__all__ = [
    "Position", "Range", "Location", "TextDocumentIdentifier", "SymbolKind",
    "DocumentSymbol", "LSPResponse", "DefinitionResponse", "ReferencesResponse",
    "HoverResponse", "DocumentSymbolResponse", "BatchResponse",
    "ClientCapabilities", "ContainerSpec",
    
    "LSPError", "LSPConnectionError", "LSPTimeoutError",
    "LSPResponseError", "LSPNotInitializedError", "LSPProcessError",
    "LSPCapabilityError",
    
    "LSPClient",
    "CapabilityNegotiator",
    "LSPResponseCache",
    "LSPResponseHasher",
    "LSPProcessManager", "LSPProcessState"
]
