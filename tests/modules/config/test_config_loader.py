"""Tests for batho.core.config.loader module."""

from __future__ import annotations

from pathlib import Path

from batho.core.config import set_active_root
from batho.core.config.loader import _get_config_cached_for_root


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
