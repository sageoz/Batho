"""
Adapter factory to route languages to correct adapter instance.
"""

from typing import Dict, Type

from batho_core.context.lsp.adapters.base import LSPAdapter
from batho_core.context.lsp.adapters.python import PythonAdapter
from batho_core.context.lsp.adapters.typescript import TypeScriptAdapter
from batho_core.context.lsp.adapters.go import GoAdapter
from batho_core.context.lsp.adapters.rust import RustAdapter
from batho_core.context.lsp.adapters.java import JavaAdapter
from batho_core.context.lsp.adapters.cpp import CppAdapter

_ADAPTER_MAP: Dict[str, Type[LSPAdapter]] = {
    "python": PythonAdapter,
    "typescript": TypeScriptAdapter,
    "javascript": TypeScriptAdapter,
    "javascriptreact": TypeScriptAdapter,
    "typescriptreact": TypeScriptAdapter,
    "go": GoAdapter,
    "rust": RustAdapter,
    "java": JavaAdapter,
    "cpp": CppAdapter,
    "c": CppAdapter,
}

class UnsupportedLanguageError(Exception):
    pass

def get_adapter(language: str) -> LSPAdapter:
    """
    Get the appropriate LSP adapter for the given language.
    """
    cls = _ADAPTER_MAP.get(language.lower())
    if cls is None:
        raise UnsupportedLanguageError(f"Language '{language}' has no registered LSP adapter.")
    return cls()
