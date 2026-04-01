"""
Tests for LSP error hierarchy.
"""

from batho_core.context.lsp.errors import (
    LSPError, LSPConnectionError, LSPTimeoutError,
    LSPResponseError, LSPProcessError, LSPCapabilityError
)


def test_error_hierarchy():
    assert issubclass(LSPConnectionError, LSPError)
    assert issubclass(LSPTimeoutError, LSPError)
    assert issubclass(LSPResponseError, LSPError)
    assert issubclass(LSPProcessError, LSPError)
    assert issubclass(LSPCapabilityError, LSPError)


def test_response_error():
    err = LSPResponseError(-32601, "Method not found", {"method": "invalid"})
    assert err.code == -32601
    assert "Method not found" in str(err)
    assert err.data == {"method": "invalid"}


def test_timeout_error():
    err = LSPTimeoutError("textDocument/definition", 5000)
    assert err.method == "textDocument/definition"
    assert err.timeout_ms == 5000
    assert "timed out after 5000ms" in str(err)
