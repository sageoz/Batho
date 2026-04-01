"""
Tests for Go Adapter.
"""

import pytest
from batho_core.context.lsp.adapters.go import GoAdapter

def test_get_file_patterns():
    adapter = GoAdapter()
    assert "*.go" in adapter.get_file_patterns()

def test_initialize_options_gopls_settings():
    adapter = GoAdapter()
    opts = adapter.get_initialize_options("/dummy")
    assert opts["staticcheck"] is True

def test_parse_project_config_go_mod(tmp_path):
    go_mod = tmp_path / "go.mod"
    go_mod.write_text("module github.com/test/mod\n\ngo 1.22\n")
    
    adapter = GoAdapter()
    config = adapter.parse_project_config(str(tmp_path))
    assert "go.mod" in config.files
    
    opts = adapter.get_initialize_options(str(tmp_path))
    assert opts["local"] == "github.com/test/mod"

def test_adapt_hover_extracts_signature():
    adapter = GoAdapter()
    hover = "```go\nfunc SomeFunc() int\n```\nDocstring"
    res = adapter.extract_type_info(hover)
    assert res == "func SomeFunc() int"
