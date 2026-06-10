"""Tests for batho.core.config.loader module."""

from __future__ import annotations

from pathlib import Path
import pytest

from batho.core.config import set_active_root
from batho.core.config.loader import _get_config_cached_for_root, get_config_with_root
from batho.utils.path_sanitizer import PathSecurityError


class TestSetActiveRoot:
    """BUG-01: Verify cache is busted when active root changes."""

    def test_set_active_root_clears_config_cache(self, tmp_path: Path):
        """Calling set_active_root must clear the lru_cache so config is reloaded."""
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
        from batho.core.config.loader import _safe_get_nested
        d = {"a": {"b": 1}}
        assert _safe_get_nested(d, ["a", "c"], "default") == "default"
        assert _safe_get_nested(d, ["x", "y"], None) is None

    def test_safe_get_nested_non_dict_path_returns_default(self):
        from batho.core.config.loader import _safe_get_nested
        d = {"a": 42}
        assert _safe_get_nested(d, ["a", "b"], "default") == "default"

    def test_safe_set_nested_creates_missing_intermediates(self):
        from batho.core.config.loader import _safe_set_nested
        d: dict = {}
        _safe_set_nested(d, ["a", "b", "c"], 42)
        assert d == {"a": {"b": {"c": 42}}}

    def test_safe_set_nested_overwrites_non_dict_intermediate(self):
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

    def test_config_backup_recovery(self, tmp_path: Path):
        """Verify that an invalid config file is backed up to .yaml.bak and replaced with default config.

        Scenario:
            A `batho.yaml` file exists but contains invalid values (e.g. integer where string logging level
            is expected). The loader must backup the corrupt config to `batho.yaml.bak` and cleanly
            recreate a correct, default `batho.yaml`.

        Execution Flow:
            1. Write invalid config content ("level: 12345") to `batho.yaml`.
            2. Invoke `get_config_with_root(tmp_path)`.
            3. Assert that backup file `batho.yaml.bak` is created and contains the original corrupt value.
            4. Assert that `batho.yaml` is regenerated with default values and is readable.

        Expectations:
            - Automatic recovery from invalid configurations.
            - Keeps the backup of user's custom (even if broken) configuration to prevent data loss.
        """
        cfg_path = tmp_path / "batho.yaml"
        # Write invalid config (e.g. invalid type for logging level)
        cfg_path.write_text("logging:\n  level: 12345\n", encoding="utf-8")
        
        cfg = get_config_with_root(tmp_path)
        
        # Assert that backup file was created
        backup_path = tmp_path / "batho.yaml.bak"
        assert backup_path.exists()
        assert "level: 12345" in backup_path.read_text(encoding="utf-8")
        
        # Assert that config was regenerated with valid default values
        assert cfg["logging"]["level"] in {10, 20, 30, 40, 50}
        assert cfg_path.exists()
        assert "level: 12345" not in cfg_path.read_text(encoding="utf-8")

