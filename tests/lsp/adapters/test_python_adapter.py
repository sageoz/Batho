"""
Tests for Python Adapter.
"""

import pytest
from pathlib import Path
from batho_core.context.lsp.adapters.python import PythonAdapter

def test_get_file_patterns():
    adapter = PythonAdapter()
    patterns = adapter.get_file_patterns()
    assert "*.py" in patterns

def test_adapt_hover_response_strips_markdown():
    adapter = PythonAdapter()
    hover_content = "```python\n(variable) foo: int\n```\nSome docstring."
    res = adapter.extract_type_info(hover_content)
    assert res == "(variable) foo: int"

def test_initialize_options_venv_detection(tmp_path):
    # Create dummy venv
    venv_dir = tmp_path / ".venv"
    venv_dir.mkdir()
    
    adapter = PythonAdapter()
    opts = adapter.get_initialize_options(str(tmp_path))
    assert opts["venvPath"] == str(tmp_path)
    assert opts["venv"] == ".venv"

def test_parse_project_config_pyproject_toml(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[tool.pyright]\nexclude = ["typestubs"]\n')
    
    adapter = PythonAdapter()
    config = adapter.parse_project_config(str(tmp_path))
    assert "pyproject.toml" in config.files

def test_extract_call_chain_info():
    adapter = PythonAdapter()
    refs = [{"uri": "file://a.py"}, {"uri": "file://b.py"}, {"uri": "file://a.py"}]
    res = adapter.extract_call_chain_info(refs)
    assert len(res) == 2
    assert "file://a.py" in res
