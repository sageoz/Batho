"""
Tests for TypeScript Adapter.
"""

import pytest
from batho_core.context.lsp.adapters.typescript import TypeScriptAdapter

def test_get_file_patterns():
    adapter = TypeScriptAdapter()
    patterns = adapter.get_file_patterns()
    assert "*.ts" in patterns

def test_initialize_options_reads_tsconfig():
    adapter = TypeScriptAdapter()
    opts = adapter.get_initialize_options("/dummy")
    assert opts["preferences"]["importModuleSpecifier"] == "non-relative"

def test_parse_project_config_path_aliases(tmp_path):
    tsconfig = tmp_path / "tsconfig.json"
    tsconfig.write_text('{"compilerOptions": {"paths": {"@/*": ["./src/*"]}}}')
    
    adapter = TypeScriptAdapter()
    config = adapter.parse_project_config(str(tmp_path))
    assert "tsconfig.json" in config.files

def test_adapt_definition_locationlink_normalization():
    adapter = TypeScriptAdapter()
    raw = [{"targetUri": "file://a.ts", "targetRange": {"start": {"line": 1, "character": 1}, "end": {"line": 1, "character": 5}}}]
    res = adapter.adapt_response("textDocument/definition", raw)
    assert "uri" in res[0]
    assert res[0]["uri"] == "file://a.ts"
