"""
Exception hierarchy for the Universal LSP Client.
"""

from typing import Any, Dict, Optional


class LSPError(Exception):
    """Base exception for all LSP-related errors."""
    pass


class LSPConnectionError(LSPError):
    """Failed to connect to LSP process."""
    def __init__(self, language: str, cause: str):
        self.language = language
        self.cause = cause
        super().__init__(f"LSP connection failed for {language}: {cause}")


class LSPTimeoutError(LSPError):
    """LSP request timed out."""
    def __init__(self, method: str, timeout_ms: int):
        self.method = method
        self.timeout_ms = timeout_ms
        super().__init__(f"LSP method {method} timed out after {timeout_ms}ms")


class LSPResponseError(LSPError):
    """LSP server returned error response via JSON-RPC."""
    def __init__(self, code: int, message: str, data: Optional[Dict[str, Any]] = None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"LSP error {code}: {message}")


class LSPNotInitializedError(LSPError):
    """Client used before being successfully initialized."""
    pass


class LSPProcessError(LSPError):
    """LSP process crashed or exited unexpectedly."""
    def __init__(self, return_code: int, stderr: str):
        self.return_code = return_code
        self.stderr = stderr
        super().__init__(f"LSP process exited with code {return_code}: {stderr}")


class LSPCapabilityError(LSPError):
    """LSP server lacks required capability."""
    def __init__(self, capability: str):
        self.capability = capability
        super().__init__(f"LSP server lacks required capability: {capability}")
