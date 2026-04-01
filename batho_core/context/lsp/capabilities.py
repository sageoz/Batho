"""
LSP Capability negotiation and management.
"""

from typing import Any, Dict

from batho_core.utils.logging import get_logger
from .types import ClientCapabilities
from .errors import LSPCapabilityError


class CapabilityNegotiator:
    """
    Manages LSP capability negotiation.
    Maps server-advertised capabilities to Batho feature requirements.
    """

    def __init__(self, server_capabilities: Dict[str, Any] | None = None):
        self.server_capabilities: Dict[str, Any] = server_capabilities or {}
        self.logger = get_logger(__name__, component="capability_negotiator")

    def update_server_capabilities(self, capabilities: Dict[str, Any]) -> None:
        """Update capabilities after initialization."""
        self.server_capabilities = capabilities

    def has_capability(self, path: str) -> bool:
        """
        Check if the server declared a specific capability.
        
        Args:
            path: Dot-separated path to the capability (e.g., 'textDocumentSync.openClose')
            
        Returns:
            True if the server supports the capability.
        """
        keys = path.split('.')
        current = self.server_capabilities
        
        for key in keys:
            if not isinstance(current, dict) or key not in current:
                return False
            current = current[key]
            
        # Treat false or null as lack of capability
        if current is False or current is None:
            return False
            
        return True

    def require_capability(self, path: str, feature_name: str) -> None:
        """
        Require a capability, raising an error if it's missing.
        
        Args:
            path: Dot-separated capability path
            feature_name: Human-readable name of the feature requiring this capability
            
        Raises:
            LSPCapabilityError: If the server lacks the required capability
        """
        if not self.has_capability(path):
            self.logger.warning(
                "missing_required_capability", 
                capability=path, 
                feature=feature_name
            )
            raise LSPCapabilityError(f"Server lacks '{path}' required for '{feature_name}'")

    def get_client_capabilities(self, debug_mode: bool = False) -> ClientCapabilities:
        """
        Get the capabilities that this client supports to advertise to the server.
        """
        caps = ClientCapabilities.default()
        if debug_mode:
            caps.batho_include_raw_responses = True
        return caps

    def supports_definition(self) -> bool:
        """Check if server supports textDocument/definition."""
        return self.has_capability("definitionProvider")

    def supports_references(self) -> bool:
        """Check if server supports textDocument/references."""
        return self.has_capability("referencesProvider")

    def supports_hover(self) -> bool:
        """Check if server supports textDocument/hover."""
        return self.has_capability("hoverProvider")

    def supports_document_symbol(self) -> bool:
        """Check if server supports textDocument/documentSymbol."""
        return self.has_capability("documentSymbolProvider")
        
    def supports_workspace_symbol(self) -> bool:
        """Check if server supports workspace/symbol."""
        return self.has_capability("workspaceSymbolProvider")
