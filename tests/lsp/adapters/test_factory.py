import pytest
from batho_core.context.lsp.adapters.factory import get_adapter, UnsupportedLanguageError
from batho_core.context.lsp.adapters.python import PythonAdapter
from batho_core.context.lsp.adapters.typescript import TypeScriptAdapter
from batho_core.context.lsp.adapters.cpp import CppAdapter

def test_get_adapter_python():
    adapter = get_adapter("python")
    assert isinstance(adapter, PythonAdapter)

def test_get_adapter_javascript_uses_typescript_adapter():
    adapter = get_adapter("javascript")
    assert isinstance(adapter, TypeScriptAdapter)

def test_get_adapter_c_uses_cpp_adapter():
    adapter = get_adapter("c")
    assert isinstance(adapter, CppAdapter)

def test_get_adapter_unknown_raises():
    with pytest.raises(UnsupportedLanguageError):
        get_adapter("unknown")
