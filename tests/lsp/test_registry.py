"""
Tests for LSPRegistry.
"""

import pytest
from batho_core.lsp.registry import LSPRegistry, LanguageSpec, VersionSpec


def test_registry_load():
    # Uses default bundled registry.yaml
    registry = LSPRegistry()
    model = registry.load()
    
    assert "python" in model.languages
    assert "typescript" in model.languages
    

def test_get_language_spec():
    registry = LSPRegistry()
    spec = registry.get_language_spec("python")
    
    assert isinstance(spec, LanguageSpec)
    assert spec.name == "Python"
    assert "1.1.350" in spec.versions


def test_get_version_spec():
    registry = LSPRegistry()
    spec = registry.get_version_spec("python", "1.1.350")
    
    assert isinstance(spec, VersionSpec)
    assert spec.container.base_image == "batho-lsp/base:node20-alpine"
    assert spec.container.lsp_binary.package == "pyright"


def test_get_latest_version():
    registry = LSPRegistry()
    latest = registry.get_latest_version("python")
    # In the current simple mock, 1.1.350 is the only one
    assert latest == "1.1.350"


def test_invalid_language():
    registry = LSPRegistry()
    with pytest.raises(KeyError):
        registry.get_language_spec("nonexistent")


def test_invalid_version():
    registry = LSPRegistry()
    with pytest.raises(KeyError):
        registry.get_version_spec("python", "invalid-version")
