"""
Tests for C/C++ Adapter.
"""

import pytest
from batho_core.context.lsp.adapters.cpp import CppAdapter

def test_get_file_patterns():
    adapter = CppAdapter()
    assert "*.cpp" in adapter.get_file_patterns()

def test_initialize_options_compile_commands_path():
    adapter = CppAdapter()
    opts = adapter.get_initialize_options("/dummy")
    assert opts["clangd"]["compilationDatabasePath"] == "/dummy"

def test_parse_project_config_compile_cmds(tmp_path):
    cmds = tmp_path / "compile_commands.json"
    cmds.write_text('[]')
    
    adapter = CppAdapter()
    config = adapter.parse_project_config(str(tmp_path))
    assert "compile_commands.json" in config.files

def test_adapt_hover_template_params():
    adapter = CppAdapter()
    hover = "```cpp\ntemplate <typename T>\nvoid foo()\n```\nDoc"
    res = adapter.extract_type_info(hover)
    assert res == "template <typename T>\nvoid foo()"
