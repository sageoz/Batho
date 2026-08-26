"""Tests for batho.core.config.loader module."""

from __future__ import annotations

import os
from pathlib import Path
import pytest

from batho.core.config import set_active_root
from batho.core.config.loader import _get_config_cached_for_root, get_config_with_root
from batho.core.config.models import Config
from batho.utils.path_sanitizer import PathSecurityError


class TestSetActiveRoot:
    """BUG-01: Verify cache is busted when active root changes."""

    def test_set_active_root_clears_config_cache(self, tmp_path: Path):
        """Verify that calling set_active_root clears the configuration lru_cache.

        Scenario:
            An active root is set, populating the config cache. Then, the active root is changed.

        Execution Flow:
            1. Clear the config cache and populate it with initial tmp_path.
            2. Verify the cache size is at least 1.
            3. Switch active root by calling set_active_root(new_root).
            4. Verify the cache size is cleared (currsize == 0).
            5. Access cache with new root and verify it is re-populated.

        Expectations:
            - The lru_cache for _get_config_cached_for_root is cleared on active root changes.
            - Cache size goes down to 0 after set_active_root, and increases on subsequent reads.
        """
        # Populate the cache first
        _get_config_cached_for_root.cache_clear()
        initial = _get_config_cached_for_root(tmp_path)
        info_before = _get_config_cached_for_root.cache_info()
        assert info_before.currsize >= 1

        # Switch root — this must clear the cache
        new_root = tmp_path / "subdir"
        new_root.mkdir()
        set_active_root(new_root)

        info_after = _get_config_cached_for_root.cache_info()
        assert info_after.currsize == 0, (
            "set_active_root did not clear the config cache"
        )

        # Side-effect: next call re-populates the cache
        _ = _get_config_cached_for_root(new_root)
        assert _get_config_cached_for_root.cache_info().currsize >= 1


class TestSafeNestedHelpers:
    """BUG-10: _safe_get_nested and _safe_set_nested guard against invalid keys."""

    def test_safe_get_nested_missing_key_returns_default(self):
        """Verify _safe_get_nested returns the default value when a nested key is missing.

        Scenario:
            A dictionary with path `["a", "b"]` is queried for missing path `["a", "c"]` or non-existent path `["x", "y"]`.

        Execution Flow:
            1. Initialize dictionary d = {"a": {"b": 1}}.
            2. Call _safe_get_nested for ["a", "c"] with default "default".
            3. Call _safe_get_nested for ["x", "y"] with default None.

        Expectations:
            - Querying ["a", "c"] returns "default".
            - Querying ["x", "y"] returns None.
        """
        from batho.core.config.loader import _safe_get_nested
        d = {"a": {"b": 1}}
        assert _safe_get_nested(d, ["a", "c"], "default") == "default"
        assert _safe_get_nested(d, ["x", "y"], None) is None

    def test_safe_get_nested_non_dict_path_returns_default(self):
        """Verify _safe_get_nested returns default if resolving hits a non-dictionary intermediate value.

        Scenario:
            A dictionary d has a non-dict value under key "a", but path query is `["a", "b"]`.

        Execution Flow:
            1. Initialize dictionary d = {"a": 42}.
            2. Query path ["a", "b"] with default "default".

        Expectations:
            - Resolving intermediate non-dict "42" gracefully returns the default value "default".
        """
        from batho.core.config.loader import _safe_get_nested
        d = {"a": 42}
        assert _safe_get_nested(d, ["a", "b"], "default") == "default"

    def test_safe_set_nested_creates_missing_intermediates(self):
        """Verify _safe_set_nested dynamically creates dicts for missing intermediate keys.

        Scenario:
            An empty dictionary is updated at a deeply nested path `["a", "b", "c"]`.

        Execution Flow:
            1. Initialize empty dictionary.
            2. Call _safe_set_nested for ["a", "b", "c"] with value 42.

        Expectations:
            - The final dictionary matches {"a": {"b": {"c": 42}}}.
        """
        from batho.core.config.loader import _safe_set_nested
        d: dict = {}
        _safe_set_nested(d, ["a", "b", "c"], 42)
        assert d == {"a": {"b": {"c": 42}}}

    def test_safe_set_nested_overwrites_non_dict_intermediate(self):
        """Verify _safe_set_nested overwrites non-dictionary values when creating intermediate keys.

        Scenario:
            A dictionary has key "a" pointing to integer 42, but a nested path `["a", "b"]` is written.

        Execution Flow:
            1. Initialize dictionary {"a": 42}.
            2. Call _safe_set_nested with path ["a", "b"] and value 99.

        Expectations:
            - The intermediate non-dict "42" is replaced with a dictionary, resulting in {"a": {"b": 99}}.
        """
        from batho.core.config.loader import _safe_set_nested
        d = {"a": 42}
        _safe_set_nested(d, ["a", "b"], 99)
        assert d == {"a": {"b": 99}}


class TestConfigSecurityAndRecovery:
    """Tests for validating path security and recovery mechanisms during config loading."""

    def test_config_path_traversal_rejection(self, tmp_path: Path):
        """Verify that configuration paths attempting to escape the project root are rejected.

        Scenario:
            An attacker (or bad config file) configures Batho paths to escape the project repository
            root using relative (`../outside_dir`) or absolute (`/tmp/outside_dir`) references.
            This must trigger a `PathSecurityError` to prevent arbitrary file read/write.

        Execution Flow:
            1. Write a safe config and verify that `get_config_with_root` resolves paths within root.
            2. Write an absolute path-escaping config and verify that `get_config_with_root` raises `PathSecurityError`.
            3. Write a relative path-escaping config and verify that `get_config_with_root` raises `PathSecurityError`.

        Expectations:
            - Any path attempting to escape the workspace root triggers a security exception.
            - Prevents directory traversal attacks via configurations.
        """
        # Safe config
        safe_yaml = tmp_path / "batho.yaml"
        safe_yaml.write_text("paths:\n  artifact_dir: .batho/artifact\n  cache_dir: .batho/cache\n  bsg_dir: .batho/bsg\n")
        cfg = get_config_with_root(tmp_path)
        assert Path(cfg["paths"]["artifact_dir"]).resolve() == (tmp_path / ".batho/artifact").resolve()

        # Unsafe config (absolute path traversal)
        unsafe_yaml_abs = tmp_path / "batho.yaml"
        unsafe_yaml_abs.write_text("paths:\n  artifact_dir: /tmp/outside_dir\n")
        with pytest.raises(PathSecurityError) as exc_info:
            get_config_with_root(tmp_path)
        assert "Unsafe config path artifact_dir escaping repository root" in str(exc_info.value)

        # Unsafe config (relative path traversal)
        unsafe_yaml_rel = tmp_path / "batho.yaml"
        unsafe_yaml_rel.write_text("paths:\n  artifact_dir: ../outside_dir\n")
        with pytest.raises(PathSecurityError) as exc_info:
            get_config_with_root(tmp_path)
        assert "Unsafe config path artifact_dir escaping repository root" in str(exc_info.value)

    def test_config_invalid_fails_explicitly(self, tmp_path: Path):
        """Verify that an invalid config file fails explicitly with a clear error.

        Scenario:
            A `batho.yaml` file exists but contains invalid values (e.g. integer where string logging level
            is expected). The loader must fail with a clear RuntimeError detailing the validation failure
            rather than silently overwriting user config.
        """
        cfg_path = tmp_path / "batho.yaml"
        # Write invalid config (e.g. invalid type for logging level)
        cfg_path.write_text("logging:\n  level: 12345\n", encoding="utf-8")
        
        with pytest.raises(RuntimeError) as exc_info:
            get_config_with_root(tmp_path)
        
        assert "Invalid Batho configuration in 'batho.yaml'" in str(exc_info.value)

    def test_community_detection_config_parsed(self, tmp_path: Path):
        """Verify that community_detection config is parsed and not stripped by Pydantic validation."""
        cfg_yaml = tmp_path / "batho.yaml"
        cfg_yaml.write_text("community_detection:\n  enabled: false\n", encoding="utf-8")
        
        cfg = get_config_with_root(tmp_path)
        
        assert "community_detection" in cfg
        assert cfg["community_detection"]["enabled"] is False


class TestMemoryConfig:
    """Verify memory thresholds and worker caps load from config and env."""

    def test_memory_config_defaults(self):
        """Default memory config values match the expected safe defaults."""
        cfg = Config()
        assert cfg.memory.warning_threshold_mb == 800.0
        assert cfg.memory.critical_threshold_mb == 1500.0
        assert cfg.memory.rss_flush_threshold_mb == 1000.0
        assert cfg.memory.max_per_worker_mb == 150.0

    def test_memory_config_from_yaml(self, tmp_path: Path):
        """Memory thresholds are loaded from batho.yaml."""
        cfg_yaml = tmp_path / "batho.yaml"
        cfg_yaml.write_text(
            "memory:\n"
            "  warning_threshold_mb: 1000.0\n"
            "  critical_threshold_mb: 2000.0\n"
            "  rss_flush_threshold_mb: 1500.0\n"
            "  max_per_worker_mb: 300.0\n",
            encoding="utf-8",
        )

        cfg = get_config_with_root(tmp_path)

        assert cfg["memory"]["warning_threshold_mb"] == 1000.0
        assert cfg["memory"]["critical_threshold_mb"] == 2000.0
        assert cfg["memory"]["rss_flush_threshold_mb"] == 1500.0
        assert cfg["memory"]["max_per_worker_mb"] == 300.0

    def test_community_detection_thresholds_from_yaml(self, tmp_path: Path):
        """Community detection skip/sample thresholds are loaded from batho.yaml."""
        cfg_yaml = tmp_path / "batho.yaml"
        cfg_yaml.write_text(
            "community_detection:\n"
            "  enabled: true\n"
            "  skip_threshold: 50000\n"
            "  sample_threshold: 25000\n",
            encoding="utf-8",
        )

        cfg = get_config_with_root(tmp_path)

        assert cfg["community_detection"]["enabled"] is True
        assert cfg["community_detection"]["skip_threshold"] == 50000
        assert cfg["community_detection"]["sample_threshold"] == 25000

    def test_memory_env_overrides(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Environment variables override memory config values."""
        cfg_yaml = tmp_path / "batho.yaml"
        cfg_yaml.write_text("memory:\n  warning_threshold_mb: 100.0\n", encoding="utf-8")

        monkeypatch.setenv("BATHO_MEMORY_CRITICAL_THRESHOLD_MB", "900.5")
        monkeypatch.setenv("BATHO_MEMORY_RSS_FLUSH_THRESHOLD_MB", "700")
        monkeypatch.setenv("BATHO_MEMORY_MAX_PER_WORKER_MB", "250")

        cfg = get_config_with_root(tmp_path)

        assert cfg["memory"]["warning_threshold_mb"] == 100.0
        assert cfg["memory"]["critical_threshold_mb"] == 900.5
        assert cfg["memory"]["rss_flush_threshold_mb"] == 700.0
        assert cfg["memory"]["max_per_worker_mb"] == 250.0

    def test_community_detection_env_overrides(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Environment variables override community detection config values."""
        cfg_yaml = tmp_path / "batho.yaml"
        cfg_yaml.write_text("community_detection:\n  enabled: true\n", encoding="utf-8")

        monkeypatch.setenv("BATHO_COMMUNITY_DETECTION_ENABLED", "false")
        monkeypatch.setenv("BATHO_COMMUNITY_DETECTION_SKIP_THRESHOLD", "50000")
        monkeypatch.setenv("BATHO_COMMUNITY_DETECTION_SAMPLE_THRESHOLD", "25000")

        cfg = get_config_with_root(tmp_path)

        assert cfg["community_detection"]["enabled"] is False
        assert cfg["community_detection"]["skip_threshold"] == 50000
        assert cfg["community_detection"]["sample_threshold"] == 25000

    def test_legacy_batho_yaml_gets_new_defaults(self, tmp_path: Path):
        """An older batho.yaml without memory/community_detection still receives defaults."""
        cfg_yaml = tmp_path / "batho.yaml"
        cfg_yaml.write_text(
            "indexer:\n  max_workers: 4\n",
            encoding="utf-8",
        )

        cfg = get_config_with_root(tmp_path)

        assert "memory" in cfg
        assert cfg["memory"]["warning_threshold_mb"] == 800.0
        assert cfg["memory"]["critical_threshold_mb"] == 1500.0
        assert cfg["memory"]["rss_flush_threshold_mb"] == 1000.0
        assert cfg["memory"]["max_per_worker_mb"] == 150.0

        assert "community_detection" in cfg
        assert cfg["community_detection"]["enabled"] is True
        assert cfg["community_detection"]["skip_threshold"] == 200_000
        assert cfg["community_detection"]["sample_threshold"] == 100_000

    def test_get_config_with_root_auto_create_false_does_not_write(self, tmp_path: Path):
        """When auto_create is False, a missing batho.yaml is not created."""
        target_dir = tmp_path / "target_repo"
        target_dir.mkdir()

        cfg = get_config_with_root(target_dir, auto_create=False)

        assert cfg is not None
        assert not (target_dir / "batho.yaml").exists()

    def test_get_config_with_root_auto_create_true_writes_target_dir(self, tmp_path: Path):
        """When auto_create is True, a default batho.yaml is written in the target directory."""
        target_dir = tmp_path / "target_repo"
        target_dir.mkdir()
        invocation_dir = tmp_path / "invocation"
        invocation_dir.mkdir()

        with pytest.MonkeyPatch.context() as mp:
            mp.chdir(invocation_dir)
            cfg = get_config_with_root(target_dir, auto_create=True)

        assert cfg is not None
        assert (target_dir / "batho.yaml").exists()
        assert not (invocation_dir / "batho.yaml").exists()
