"""
tests/modules/storage/test_cache_variant_rules.py

Unit tests for rules-fingerprint in the AST cache variant (T02 — batho-calibrate):
  - build_ast_cache_variant keys on rules_fingerprint
  - rules_fingerprint_for_config returns "" for disabled/missing rules
  - Effective fingerprint changes when plugin sources change
"""

from __future__ import annotations

from pathlib import Path

from batho_plugin.rule_engine import (
    load_effective_rules,
    rules_fingerprint_for_config,
)
from batho.modules.storage.cache.unified_cache import build_ast_cache_variant


def _plugin(path: Path, rule_suffix: str) -> None:
    path.write_text(
        f"""schema_version: bsg-plugin.v2
plugin_id: test_{rule_suffix}
name: Test {rule_suffix}
version: 1.0.0
enabled: true
rules:
  - rule_id: test-{rule_suffix}
    name: test-{rule_suffix}
    severity: warning
    matchers:
      file_patterns:
        - "**/{rule_suffix}.txt"
    actions:
      add_usn_tags:
        - Tag{rule_suffix}
""",
        encoding="utf-8",
    )


class TestVariantRulesDimension:
    def test_variant_changes_with_rules_fingerprint(self):
        v1 = build_ast_cache_variant(
            include_gaps=False, parsing_config={}, rules_fingerprint="aaa"
        )
        v2 = build_ast_cache_variant(
            include_gaps=False, parsing_config={}, rules_fingerprint="bbb"
        )
        v3 = build_ast_cache_variant(
            include_gaps=False, parsing_config={}, rules_fingerprint="aaa"
        )
        assert v1 != v2
        assert v1 == v3

    def test_default_rules_fingerprint_is_empty_compatible(self):
        """Callers without the param behave identically to rules='' (B/C)."""
        a = build_ast_cache_variant(include_gaps=False, parsing_config={})
        b = build_ast_cache_variant(
            include_gaps=False, parsing_config={}, rules_fingerprint=""
        )
        assert a == b

    def test_variant_stable_across_key_ordering(self):
        v1 = build_ast_cache_variant(
            include_gaps=True,
            parsing_config={"b": 1, "a": 2},
            identity_fingerprint="x",
            rules_fingerprint="r",
        )
        v2 = build_ast_cache_variant(
            include_gaps=True,
            parsing_config={"a": 2, "b": 1},
            identity_fingerprint="x",
            rules_fingerprint="r",
        )
        assert v1 == v2


class TestRulesFingerprintForConfig:
    def test_empty_when_rules_disabled(self, tmp_path: Path):
        fp = rules_fingerprint_for_config({"enabled": False}, tmp_path)
        assert fp == ""

    def test_empty_when_no_config(self, tmp_path: Path):
        assert rules_fingerprint_for_config(None, tmp_path) == ""
        assert rules_fingerprint_for_config({}, tmp_path) == ""

    def test_nonempty_and_stable_when_enabled(self, tmp_path: Path):
        cfg = {
            "enabled": True,
            "auto_load_all_plugins": False,
            "builtin_plugins": [],
        }
        fp1 = rules_fingerprint_for_config(cfg, tmp_path)
        fp2 = rules_fingerprint_for_config(cfg, tmp_path)
        assert fp1 != ""
        assert fp1 == fp2

    def test_fingerprint_changes_on_plugin_content_edit(self, tmp_path: Path):
        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()
        p = plugin_dir / "p.yaml"
        _plugin(p, "one")
        cfg = {
            "enabled": True,
            "auto_load_all_plugins": False,
            "builtin_plugins": [],
            "custom_rules_dir": str(plugin_dir),
        }
        fp1 = rules_fingerprint_for_config(cfg, tmp_path)
        _plugin(p, "two")
        fp2 = rules_fingerprint_for_config(cfg, tmp_path)
        assert fp1 != fp2

    def test_fingerprint_changes_on_config_keys(self, tmp_path: Path):
        base = {"enabled": True, "auto_load_all_plugins": False, "builtin_plugins": []}
        fp1 = rules_fingerprint_for_config(base, tmp_path)
        fp2 = rules_fingerprint_for_config(
            {**base, "disabled_rules": ["something"]}, tmp_path
        )
        assert fp1 != fp2

    def test_stats_carry_fingerprint(self, tmp_path: Path):
        """load_effective_rules exposes rules_fingerprint in stats on both
        fresh-load and cache-hit paths."""
        cfg = {
            "enabled": True,
            "auto_load_all_plugins": False,
            "builtin_plugins": [],
        }
        _, stats1 = load_effective_rules(cfg, tmp_path)
        _, stats2 = load_effective_rules(cfg, tmp_path)
        assert stats1.get("rules_fingerprint")
        assert stats2["cache_hit"] is True
        assert stats1["rules_fingerprint"] == stats2["rules_fingerprint"]


class TestEffectiveRulesConfigMerge:
    """CFG-02: plugins.overrides must fold into the rules payload so the
    parallel-extraction worker load + rules_fingerprint see the same
    effective config as the serial path."""

    def test_overrides_fold_into_plugins_overrides(self):
        from batho_plugin.rule_engine import effective_rules_config

        cfg = {
            "rules": {"enabled": True, "builtin_plugins": ["python"]},
            "plugins": {"overrides": {"python": {"r1": {"severity": "error"}}}},
        }
        merged = effective_rules_config(cfg)
        assert merged["plugins_overrides"] == {
            "python": {"r1": {"severity": "error"}}
        }
        # rules dict untouched otherwise
        assert merged["enabled"] is True
        assert merged["builtin_plugins"] == ["python"]

    def test_overrides_change_fingerprint(self, tmp_path: Path):
        from batho_plugin.rule_engine import effective_rules_config

        base = {
            "rules": {
                "enabled": True,
                "auto_load_all_plugins": False,
                "builtin_plugins": [],
            },
            "plugins": {"overrides": {"p": {"r": {"severity": "warning"}}}},
        }
        altered = {
            "rules": dict(base["rules"]),
            "plugins": {"overrides": {"p": {"r": {"severity": "error"}}}},
        }
        fp1 = rules_fingerprint_for_config(
            effective_rules_config(base), tmp_path
        )
        fp2 = rules_fingerprint_for_config(
            effective_rules_config(altered), tmp_path
        )
        assert fp1 != "" and fp2 != ""
        assert fp1 != fp2, "plugins.overrides must reach the fingerprint"

    def test_no_overrides_leaves_config_unchanged(self):
        from batho_plugin.rule_engine import effective_rules_config

        cfg = {"rules": {"enabled": True}}
        merged = effective_rules_config(cfg)
        assert "plugins_overrides" not in merged
        assert effective_rules_config({}) == {}
