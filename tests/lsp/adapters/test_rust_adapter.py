"""
Tests for Rust Adapter.
"""

import pytest
from batho_core.context.lsp.adapters.rust import RustAdapter

def test_get_file_patterns():
    adapter = RustAdapter()
    assert "*.rs" in adapter.get_file_patterns()

def test_initialize_options_rust_analyzer_settings():
    adapter = RustAdapter()
    opts = adapter.get_initialize_options("/dummy")
    assert opts["cargo"]["features"] == "all"

def test_parse_project_config_cargo_toml(tmp_path):
    cargo_toml = tmp_path / "Cargo.toml"
    cargo_toml.write_text('[package]\nname = "test"\nversion = "0.1.0"\n')
    
    adapter = RustAdapter()
    config = adapter.parse_project_config(str(tmp_path))
    assert "Cargo.toml" in config.files

def test_adapt_hover_trait_bounds():
    adapter = RustAdapter()
    hover = "```rust\nfn foo<T: Debug>(t: T)\n```\nDoc"
    res = adapter.extract_type_info(hover)
    assert res == "fn foo<T: Debug>(t: T)"
