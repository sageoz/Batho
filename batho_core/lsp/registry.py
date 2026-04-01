"""
LSP Container Registry.

Manages the specification of pinned LSP versions and hermetic container configurations.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field

from batho_core.utils.logging import get_logger


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class LSPBinarySpec(BaseModel):
    """Specification for an LSP binary."""
    source: str
    package: str
    version: str
    sha256: str
    nix_package: Optional[str] = None


class ResourceLimits(BaseModel):
    """Resource limits for container."""
    memory_mb: int = 2048
    cpu_cores: float = 2.0


class ConfigSpec(BaseModel):
    """Configuration mapping for language server."""
    type: str
    files: List[str] = Field(default_factory=list)


class DependencySpec(BaseModel):
    """Dependencies for the LSP container."""
    name: str
    version: str
    sha256: str


class ContainerSpec(BaseModel):
    """Specification for hermetic container."""
    base_image: str
    lsp_binary: LSPBinarySpec
    command: List[str]
    patterns: List[str] = Field(default_factory=list)
    resources: ResourceLimits = Field(default_factory=ResourceLimits)
    env: Dict[str, str] = Field(default_factory=dict)
    config: Optional[ConfigSpec] = None
    dependencies: List[DependencySpec] = Field(default_factory=list)
    image_digest: Optional[str] = None


class VerificationSpec(BaseModel):
    """Verification rules for a container."""
    type: str
    timeout_ms: Optional[int] = None
    test_file: Optional[str] = None
    expected_result: Optional[str] = None


class VersionSpec(BaseModel):
    """A specific version of an LSP."""
    container: ContainerSpec
    verification: List[VerificationSpec] = Field(default_factory=list)


class LanguageSpec(BaseModel):
    """Specification for a language supported by Batho."""
    name: str
    lsp_name: str
    versions: Dict[str, VersionSpec] = Field(default_factory=dict)


class RegistryModel(BaseModel):
    """Root model for registry.yaml."""
    version: str
    registry_url: str
    languages: Dict[str, LanguageSpec] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Registry Manager
# ---------------------------------------------------------------------------


class LSPRegistry:
    """
    Manages the loading and validation of the LSP version registry.
    """

    def __init__(self, registry_path: str | Path | None = None) -> None:
        self.logger = get_logger(__name__, component="registry")
        
        if registry_path is None:
            # Default to bundled registry.yaml
            self.registry_path = Path(__file__).parent / "containers" / "registry.yaml"
        else:
            self.registry_path = Path(registry_path)
            
        self._model: Optional[RegistryModel] = None

    def load(self) -> RegistryModel:
        """Load and validate the registry."""
        if self._model is not None:
            return self._model
            
        if not self.registry_path.exists():
            raise FileNotFoundError(f"LSP registry not found at {self.registry_path}")
            
        try:
            with open(self.registry_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                
            self._model = RegistryModel.model_validate(data)
            self.logger.debug("registry_loaded", languages=list(self._model.languages.keys()))
            return self._model
            
        except Exception as e:
            self.logger.error("registry_load_failed", path=str(self.registry_path), error=str(e))
            raise ValueError(f"Failed to load registry: {e}") from e

    def get_language_spec(self, language_id: str) -> LanguageSpec:
        """Get the specification for a language."""
        model = self.load()
        if language_id not in model.languages:
            raise KeyError(f"Language '{language_id}' not found in registry")
        return model.languages[language_id]

    def get_version_spec(self, language_id: str, version: str) -> VersionSpec:
        """Get the specification for a specific language version."""
        lang_spec = self.get_language_spec(language_id)
        if version not in lang_spec.versions:
            raise KeyError(f"Version '{version}' not found for language '{language_id}'")
        return lang_spec.versions[version]

    def get_latest_version(self, language_id: str) -> str:
        """Get the latest version configured for a language based on string sorting."""
        lang_spec = self.get_language_spec(language_id)
        if not lang_spec.versions:
            raise ValueError(f"No versions defined for language '{language_id}'")
        # In a real implementation this would parse semver properly
        return sorted(lang_spec.versions.keys(), reverse=True)[0]
