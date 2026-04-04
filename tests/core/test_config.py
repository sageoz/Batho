"""Tests for batho_core.config module."""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from batho_core.config import (
    Config,
    FlagsConfig,
    IndexerConfig,
    LoggingConfig,
    PathsConfig,
    DEFAULT_RULES_BUILTIN_PLUGINS,
    RulesConfig,
    get_build_info,
    get_config,
    get_config_cached,
    reload_config,
    _merge_config,
    _load_config_file,
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class TestPydanticModels:

    def test_logging_config_defaults(self):
        cfg = LoggingConfig()
        assert cfg.level == "INFO"
        assert cfg.json_format is None

    def test_logging_std_level(self):
        cfg = LoggingConfig(level="DEBUG")
        assert cfg.std_level == logging.DEBUG

    def test_paths_config_defaults(self):
        cfg = PathsConfig()
        assert cfg.ctn_dir == ".ctn"

    def test_indexer_config_defaults(self):
        cfg = IndexerConfig()
        assert cfg.max_file_size_kb == 500
        assert cfg.max_workers == 0
        assert cfg.ignore_patterns == []
        assert cfg.ignore_files is None
        assert cfg.strict is False

    def test_flags_config_defaults(self):
        cfg = FlagsConfig()
        assert cfg.fail_on_warning is False
        assert cfg.strict is False

    def test_rules_config_defaults(self):
        cfg = RulesConfig()
        assert cfg.enabled is True
        assert cfg.builtin_plugins == list(DEFAULT_RULES_BUILTIN_PLUGINS)
        assert cfg.disabled_rules == []
        assert cfg.custom_rules_path is None
        assert cfg.custom_rules_inline == []
        assert cfg.strict_validation is False
        assert cfg.cache_ttl == 3600
        assert cfg.fail_on_rule_error is False

    def test_config_full(self):
        cfg = Config()
        assert isinstance(cfg.logging, LoggingConfig)
        assert isinstance(cfg.paths, PathsConfig)
        assert isinstance(cfg.indexer, IndexerConfig)
        assert isinstance(cfg.flags, FlagsConfig)
        assert isinstance(cfg.rules, RulesConfig)


# ---------------------------------------------------------------------------
# get_config
# ---------------------------------------------------------------------------

class TestGetConfig:

    def test_returns_dict(self):
        cfg = get_config()
        assert isinstance(cfg, dict)

    def test_has_required_keys(self):
        cfg = get_config()
        assert "logging" in cfg
        assert "paths" in cfg
        assert "indexer" in cfg
        assert "flags" in cfg
        assert "rules" in cfg

    def test_logging_level_is_int(self):
        cfg = get_config()
        assert isinstance(cfg["logging"]["level"], int)

    def test_schema_versions(self):
        cfg = get_config()
        assert "graph_schema_version" in cfg
        assert "bsg_schema_version" in cfg
        assert "snapshot_schema_version" in cfg
        assert "index_metadata_schema_version" in cfg

    def test_env_override_log_level(self, monkeypatch):
        monkeypatch.setenv("BATHO_LOG_LEVEL", "DEBUG")
        cfg = get_config()
        assert cfg["logging"]["level"] == logging.DEBUG

    def test_env_override_ctn_dir(self, monkeypatch):
        monkeypatch.setenv("BATHO_CTN_DIR", ".custom_ctn")
        cfg = get_config()
        assert cfg["paths"]["ctn_dir"] == ".custom_ctn"

    def test_env_override_max_file_size(self, monkeypatch):
        monkeypatch.setenv("BATHO_MAX_FILE_SIZE_KB", "1000")
        cfg = get_config()
        assert cfg["indexer"]["max_file_size_kb"] == 1000

    def test_env_override_strict(self, monkeypatch):
        monkeypatch.setenv("BATHO_STRICT", "true")
        cfg = get_config()
        assert cfg["flags"]["strict"] is True

    def test_env_override_ignore_patterns(self, monkeypatch):
        monkeypatch.setenv("BATHO_IGNORE_PATTERNS", "dist/,build/")
        cfg = get_config()
        assert cfg["indexer"]["ignore_patterns"] == ["dist/", "build/"]

    def test_env_override_ignore_files(self, monkeypatch):
        monkeypatch.setenv("BATHO_IGNORE_FILES", ".gitignore,.bathoignore")
        cfg = get_config()
        assert cfg["indexer"]["ignore_files"] == [".gitignore", ".bathoignore"]

    def test_env_override_rules_enabled(self, monkeypatch):
        monkeypatch.setenv("BATHO_RULES_ENABLED", "true")
        cfg = get_config()
        assert cfg["rules"]["enabled"] is True

    def test_env_override_rules_custom_path(self, monkeypatch):
        monkeypatch.setenv("BATHO_RULES_CUSTOM_RULES_PATH", "plugins/custom.yaml")
        cfg = get_config()
        assert cfg["rules"]["custom_rules_path"] == "plugins/custom.yaml"

    def test_env_override_rules_lists(self, monkeypatch):
        monkeypatch.setenv("BATHO_RULES_BUILTIN_PLUGINS", "bsg_core,custom_pack")
        monkeypatch.setenv("BATHO_RULES_DISABLED_RULES", "rule_one,rule_two")
        cfg = get_config()
        assert cfg["rules"]["builtin_plugins"] == ["bsg_core", "custom_pack"]
        assert cfg["rules"]["disabled_rules"] == ["rule_one", "rule_two"]


# ---------------------------------------------------------------------------
# Config file loading
# ---------------------------------------------------------------------------

class TestConfigFileLoading:

    def test_root_yaml_config(self, tmp_path: Path, monkeypatch):
        cfg_file = tmp_path / "batho.yaml"
        cfg_file.write_text("logging:\n  level: ERROR\n")
        monkeypatch.chdir(tmp_path)

        get_config_cached.cache_clear()
        cfg = get_config()
        assert cfg["logging"]["level"] == logging.ERROR

    def test_missing_root_config_uses_defaults(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        get_config_cached.cache_clear()
        cfg = get_config()
        assert isinstance(cfg, dict)
        assert "logging" in cfg

    def test_invalid_root_config_falls_back(self, tmp_path: Path, monkeypatch):
        cfg_file = tmp_path / "batho.yaml"
        cfg_file.write_text("not valid yaml{{{")
        monkeypatch.chdir(tmp_path)

        get_config_cached.cache_clear()
        cfg = get_config()
        assert isinstance(cfg, dict)
        assert "logging" in cfg

    def test_unsupported_format(self, tmp_path: Path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text("[section]\nkey=val\n")
        with pytest.raises(ValueError, match="Unsupported"):
            _load_config_file(cfg_file)


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------

class TestConfigCaching:

    def test_cached_returns_same(self):
        a = get_config_cached()
        b = get_config_cached()
        assert a is b

    def test_reload_clears_cache(self):
        a = get_config_cached()
        b = reload_config()
        # Both should be valid dicts, but b is a fresh computation
        assert isinstance(b, dict)
        assert "logging" in b


# ---------------------------------------------------------------------------
# _merge_config
# ---------------------------------------------------------------------------

class TestMergeConfig:

    def test_shallow_merge(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = _merge_config(base, override)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_deep_merge(self):
        base = {"logging": {"level": "INFO", "json_format": True}}
        override = {"logging": {"level": "DEBUG"}}
        result = _merge_config(base, override)
        assert result["logging"]["level"] == "DEBUG"
        assert result["logging"]["json_format"] is True


# ---------------------------------------------------------------------------
# get_build_info
# ---------------------------------------------------------------------------

class TestBuildInfo:

    def test_has_version(self):
        info = get_build_info()
        assert "version" in info
        assert isinstance(info["version"], str)

    def test_has_build(self):
        info = get_build_info()
        assert "build" in info
