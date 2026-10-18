"""
tests/modules/compression/test_custom_rules_dir.py

Unit tests for rules.custom_rules_dir (T01 — batho-calibrate):
  - Directory scan loads every *.yaml/*.yml plugin with per-file attribution
  - Per-file source hashing + fingerprint invalidation
  - Coexistence with custom_rules_path
  - Missing/empty dir no-op, not-a-directory error path, invalid file handling
"""

from __future__ import annotations

from pathlib import Path

import pytest

from batho_plugin.rule_engine import (
    _compute_source_hashes,
    _rules_config_fingerprint,
    load_effective_rules,
)


def _write_plugin(directory: Path, filename: str, rule_suffix: str) -> Path:
    """Write a minimal valid bsg-plugin.v2 file; returns its path."""
    path = directory / filename
    path.write_text(
        f"""schema_version: bsg-plugin.v2
plugin_id: test_{rule_suffix}
name: Test {rule_suffix}
version: 1.0.0
enabled: true
rules:
  - rule_id: test-{rule_suffix}-rule
    name: test-{rule_suffix}-rule
    description: Fixture rule {rule_suffix}
    severity: warning
    matchers:
      file_patterns:
        - "**/{rule_suffix}.txt"
    actions:
      metadata:
        bsg.test.{rule_suffix}: true
      add_usn_tags:
        - TestTag{rule_suffix}
""",
        encoding="utf-8",
    )
    return path


def _cfg(plugin_dir: str | None = None, **extra) -> dict:
    cfg = {
        "enabled": True,
        "auto_load_all_plugins": False,
        "builtin_plugins": [],
    }
    if plugin_dir is not None:
        cfg["custom_rules_dir"] = plugin_dir
    cfg.update(extra)
    return cfg


class TestCustomRulesDir:
    def test_loads_multiple_plugin_files(self, tmp_path: Path):
        """Two plugin files in the dir both load, each attributed to its file."""
        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()
        _write_plugin(plugin_dir, "alpha.yaml", "alpha")
        _write_plugin(plugin_dir, "beta.yml", "beta")

        rules, stats = load_effective_rules(
            rules_config=_cfg(str(plugin_dir)), root_path=tmp_path
        )

        rule_ids = {r.rule_id for r in rules}
        assert {"test-alpha-rule", "test-beta-rule"} <= rule_ids
        plugins = {r.plugin for r in rules}
        assert {"custom_dir:alpha.yaml", "custom_dir:beta.yml"} <= plugins
        assert stats["custom_dir_files"] == 2
        assert stats["custom_dir_rule_count"] == 2
        assert stats["custom_file_count"] == 2
        assert stats["errors"] == []

    def test_missing_dir_is_noop(self, tmp_path: Path):
        """A nonexistent custom_rules_dir produces no error and no rules."""
        rules, stats = load_effective_rules(
            rules_config=_cfg(str(tmp_path / "does_not_exist")),
            root_path=tmp_path,
        )
        assert rules == []
        assert stats["custom_dir_files"] == 0
        assert stats["errors"] == []

    def test_empty_dir_is_noop(self, tmp_path: Path):
        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()
        rules, stats = load_effective_rules(
            rules_config=_cfg(str(plugin_dir)), root_path=tmp_path
        )
        assert rules == []
        assert stats["custom_dir_files"] == 0
        assert stats["errors"] == []

    def test_not_a_directory_reports_error(self, tmp_path: Path):
        """custom_rules_dir pointing at a regular file records an error."""
        f = tmp_path / "not_a_dir.yaml"
        f.write_text("x: 1", encoding="utf-8")
        _, stats = load_effective_rules(
            rules_config=_cfg(str(f)), root_path=tmp_path
        )
        assert stats["custom_dir_files"] == 0
        assert any("not a directory" in e for e in stats["errors"])

    def test_invalid_file_skipped_in_non_strict(self, tmp_path: Path):
        """One bad YAML doesn't block the good file (non-strict warn path)."""
        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()
        _write_plugin(plugin_dir, "good.yaml", "good")
        (plugin_dir / "bad.yaml").write_text("{{{ not yaml", encoding="utf-8")

        rules, stats = load_effective_rules(
            rules_config=_cfg(str(plugin_dir)), root_path=tmp_path
        )
        assert {r.rule_id for r in rules} == {"test-good-rule"}
        assert stats["custom_dir_files"] == 2
        assert stats["errors"] != []

    def test_coexists_with_custom_rules_path(self, tmp_path: Path):
        """Both single-file and dir-based custom rules load together."""
        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()
        _write_plugin(plugin_dir, "dirrule.yaml", "dirrule")
        single = _write_plugin(tmp_path, "single.yaml", "single")

        rules, stats = load_effective_rules(
            rules_config=_cfg(str(plugin_dir), custom_rules_path=str(single)),
            root_path=tmp_path,
        )
        rule_ids = {r.rule_id for r in rules}
        assert {"test-single-rule", "test-dirrule-rule"} <= rule_ids
        plugins = {r.plugin for r in rules}
        assert "custom_file" in plugins
        assert "custom_dir:dirrule.yaml" in plugins

    def test_per_file_fingerprint_invalidation(self, tmp_path: Path):
        """Adding one file to the dir changes the fingerprint but preserves
        other files' source hashes (per-file invalidation)."""
        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()
        a = _write_plugin(plugin_dir, "a.yaml", "a")
        cfg = _cfg(str(plugin_dir))

        _, stats1 = load_effective_rules(rules_config=cfg, root_path=tmp_path)
        _, stats2 = load_effective_rules(rules_config=cfg, root_path=tmp_path)
        assert stats2["cache_hit"] is True

        _write_plugin(plugin_dir, "b.yaml", "b")
        _, stats3 = load_effective_rules(rules_config=cfg, root_path=tmp_path)
        assert stats3["cache_hit"] is False
        assert {r.rule_id for r in load_effective_rules(cfg, tmp_path)[0]} >= {
            "test-a-rule",
            "test-b-rule",
        }

        # Per-file granularity: a.yaml's hash entry exists and is stable
        # (verify via the source-hash helper directly)
        hashes = _compute_source_hashes([], None, [a])
        assert a.as_posix() in hashes

    def test_fingerprint_includes_dir_key(self, tmp_path: Path):
        """_rules_config_fingerprint reflects the custom_rules_dir config key."""
        fp_no_dir = _rules_config_fingerprint(_cfg(None), {})
        fp_dir = _rules_config_fingerprint(_cfg("some/dir"), {})
        assert fp_no_dir != fp_dir

    def test_dir_rules_are_effective_and_sorted(self, tmp_path: Path):
        """Rules from dir files end up in the effective (sorted) rule list."""
        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()
        _write_plugin(plugin_dir, "zzz.yaml", "zzz")
        _write_plugin(plugin_dir, "aaa.yaml", "aaa")
        rules, _ = load_effective_rules(
            rules_config=_cfg(str(plugin_dir)), root_path=tmp_path
        )
        # effective list is sorted by (priority, name)
        names = [r.name for r in rules]
        assert names == sorted(names, key=str.lower)
        assert {r.plugin for r in rules} == {"custom_dir:aaa.yaml", "custom_dir:zzz.yaml"}


    def test_same_stem_yaml_yml_both_attributed(self, tmp_path: Path):
        """RUL-07: retry.yaml + retry.yml share a stem — plugin identity now
        keys on the full filename so both load and both map in plugin_files."""
        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()
        _write_plugin(plugin_dir, "retry.yaml", "retrya")
        _write_plugin(plugin_dir, "retry.yml", "retryb")

        rules, stats = load_effective_rules(
            rules_config=_cfg(str(plugin_dir)), root_path=tmp_path
        )
        plugins = {r.plugin for r in rules}
        assert {"custom_dir:retry.yaml", "custom_dir:retry.yml"} <= plugins
        plugin_files = stats.get("plugin_files") or {}
        assert "custom_dir:retry.yaml" in plugin_files
        assert "custom_dir:retry.yml" in plugin_files

    def test_custom_rules_path_inside_dir_not_double_loaded(
        self, tmp_path: Path
    ):
        """RUL-08: pointing custom_rules_path at a file inside
        custom_rules_dir must not register the same YAML twice (double
        stats + spurious shadowed_rules)."""
        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()
        shared = _write_plugin(plugin_dir, "shared.yaml", "shared")
        _write_plugin(plugin_dir, "other.yaml", "other")

        rules, stats = load_effective_rules(
            rules_config=_cfg(
                str(plugin_dir), custom_rules_path=str(shared)
            ),
            root_path=tmp_path,
        )
        # shared.yaml loads once as custom_file; dir scan skips it
        shared_rules = [r for r in rules if r.rule_id == "test-shared-rule"]
        assert len(shared_rules) == 1
        assert {r.plugin for r in shared_rules} == {"custom_file"}
        assert stats.get("shadowed_rules") in (None, [], ())
        other_rules = [r for r in rules if r.rule_id == "test-other-rule"]
        assert len(other_rules) == 1
        assert other_rules[0].plugin == "custom_dir:other.yaml"
