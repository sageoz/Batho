"""Tests for graph backend configuration (GraphBackendConfig)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from batho.core.config.loader import get_config_with_root
from batho.core.config.models import Config, GraphBackendConfig

_GRAPH_BACKEND_ENV_VARS = (
    "BATHO_GRAPH_BACKEND",
    "BATHO_GRAPH_AUTO_THRESHOLD_FILES",
    "BATHO_GRAPH_AUTO_THRESHOLD_ENTITIES",
    "BATHO_GRAPH_ARROW_STAGING_DIR",
    "BATHO_GRAPH_ARROW_FLUSH_ROWS",
    "BATHO_GRAPH_ARROW_FLUSH_BYTES_MB",
    "BATHO_GRAPH_ARROW_RECOMPACT_DELTA_RATIO",
)


@pytest.fixture(autouse=True)
def _clean_graph_backend_env(monkeypatch: pytest.MonkeyPatch):
    """Ensure a hermetic environment for every test in this module."""
    for var in _GRAPH_BACKEND_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


class TestGraphBackendConfigModel:
    def test_defaults(self):
        cfg = GraphBackendConfig()
        assert cfg.backend == "auto"
        assert cfg.auto_threshold_files == 500
        assert cfg.auto_threshold_entities == 30_000
        assert cfg.arrow_staging_dir == ".batho/graph_staging"
        assert cfg.arrow_flush_rows == 5000
        assert cfg.arrow_flush_bytes_mb == 1.0
        assert cfg.arrow_recompact_delta_ratio == 0.10

    def test_valid_backends_accepted(self):
        for backend in ("auto", "in-memory", "arrow"):
            assert GraphBackendConfig(backend=backend).backend == backend

    def test_invalid_backend_rejected(self):
        with pytest.raises(ValueError, match="graph.backend.backend"):
            GraphBackendConfig(backend="sqlite")

    def test_graph_config_includes_backend(self):
        cfg = Config()
        assert isinstance(cfg.graph.backend, GraphBackendConfig)
        assert cfg.graph.backend.backend == "auto"

    def test_constraint_validation(self):
        with pytest.raises(ValueError):
            GraphBackendConfig(auto_threshold_files=0)
        with pytest.raises(ValueError):
            GraphBackendConfig(arrow_flush_rows=50)
        with pytest.raises(ValueError):
            GraphBackendConfig(arrow_flush_bytes_mb=0.0)
        with pytest.raises(ValueError):
            GraphBackendConfig(arrow_recompact_delta_ratio=2.0)


class TestGraphBackendEnvOverrides:
    def test_backend_env_override(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("BATHO_GRAPH_BACKEND", "arrow")
        cfg = get_config_with_root(tmp_path)
        assert cfg["graph"]["backend"]["backend"] == "arrow"

    def test_auto_threshold_files_env_override(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("BATHO_GRAPH_AUTO_THRESHOLD_FILES", "1234")
        cfg = get_config_with_root(tmp_path)
        assert cfg["graph"]["backend"]["auto_threshold_files"] == 1234

    def test_auto_threshold_entities_env_override(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("BATHO_GRAPH_AUTO_THRESHOLD_ENTITIES", "99999")
        cfg = get_config_with_root(tmp_path)
        assert cfg["graph"]["backend"]["auto_threshold_entities"] == 99999

    def test_arrow_staging_dir_env_override(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("BATHO_GRAPH_ARROW_STAGING_DIR", ".batho/custom_staging")
        cfg = get_config_with_root(tmp_path)
        assert cfg["graph"]["backend"]["arrow_staging_dir"] == ".batho/custom_staging"

    def test_arrow_flush_rows_env_override(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("BATHO_GRAPH_ARROW_FLUSH_ROWS", "777")
        cfg = get_config_with_root(tmp_path)
        assert cfg["graph"]["backend"]["arrow_flush_rows"] == 777

    def test_arrow_flush_bytes_mb_env_override(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("BATHO_GRAPH_ARROW_FLUSH_BYTES_MB", "2.5")
        cfg = get_config_with_root(tmp_path)
        assert cfg["graph"]["backend"]["arrow_flush_bytes_mb"] == 2.5

    def test_arrow_recompact_delta_ratio_env_override(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("BATHO_GRAPH_ARROW_RECOMPACT_DELTA_RATIO", "0.25")
        cfg = get_config_with_root(tmp_path)
        assert cfg["graph"]["backend"]["arrow_recompact_delta_ratio"] == 0.25

    def test_invalid_backend_env_falls_back_to_defaults(self, tmp_path: Path, monkeypatch):
        # An invalid env value is ignored by the loader (not passed to Pydantic
        # validation); config falls back to YAML/default value.
        monkeypatch.setenv("BATHO_GRAPH_BACKEND", "bogus")
        cfg = get_config_with_root(tmp_path)
        assert cfg["graph"]["backend"]["backend"] == "auto"


class TestGraphBackendYaml:
    def test_yaml_roundtrip(self, tmp_path: Path):
        yaml_cfg = {
            "graph": {
                "backend": {
                    "backend": "arrow",
                    "auto_threshold_files": 100,
                    "auto_threshold_entities": 5000,
                    "arrow_staging_dir": ".batho/staging",
                    "arrow_flush_rows": 1000,
                    "arrow_flush_bytes_mb": 4.0,
                    "arrow_recompact_delta_ratio": 0.5,
                }
            }
        }
        (tmp_path / "batho.yaml").write_text(yaml.safe_dump(yaml_cfg), encoding="utf-8")
        cfg = get_config_with_root(tmp_path)
        backend = cfg["graph"]["backend"]
        assert backend == {
            "backend": "arrow",
            "auto_threshold_files": 100,
            "auto_threshold_entities": 5000,
            "arrow_staging_dir": ".batho/staging",
            "arrow_flush_rows": 1000,
            "arrow_flush_bytes_mb": 4.0,
            "arrow_recompact_delta_ratio": 0.5,
        }

    def test_defaults_present_without_yaml(self, tmp_path: Path):
        cfg = get_config_with_root(tmp_path)
        assert cfg["graph"]["backend"]["backend"] == "auto"
        assert cfg["graph"]["backend"]["auto_threshold_files"] == 500

    def test_auto_created_config_contains_backend_section(self, tmp_path: Path):
        cfg = get_config_with_root(tmp_path, auto_create=True)
        assert (tmp_path / "batho.yaml").exists()
        on_disk = yaml.safe_load((tmp_path / "batho.yaml").read_text(encoding="utf-8"))
        assert "backend" in on_disk["graph"]
        assert on_disk["graph"]["backend"]["backend"] == "auto"
        assert cfg["graph"]["backend"]["backend"] == "auto"
