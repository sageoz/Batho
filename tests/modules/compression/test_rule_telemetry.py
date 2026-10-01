"""
tests/modules/compression/test_rule_telemetry.py

Unit tests for T05 rule telemetry (batho-calibrate):
  - build_rule_telemetry aggregates bsg.rules metadata per rule
  - entities_matched / files_touched / plugin / severity / tags_emitted
  - deterministic ordering; unknown rules tolerated
"""

from __future__ import annotations

from batho.modules.compression.rules import (
    RuleActions,
    RuleDefinition,
    RuleMatch,
    build_rule_telemetry,
)


class _Ent:
    def __init__(self, file: str, rules: list[str] | None):
        self.file = file
        self.metadata = {"bsg.rules": rules} if rules is not None else {}


def _rule(name: str, plugin: str = "custom_dir:test", severity: str = "warning",
          tags: tuple[str, ...] = ("TagA",)) -> RuleDefinition:
    return RuleDefinition(
        rule_id=f"rid-{name}",
        name=name,
        description="",
        severity=severity,
        priority=0,
        enabled=True,
        plugin=plugin,
        score=0,
        tags=(),
        schema_version="bsg-plugin.v2",
        bidirectional=False,
        match=RuleMatch(),
        actions=RuleActions(add_usn_tags=tags),
    )


class TestBuildRuleTelemetry:
    def test_aggregates_per_rule_counts(self):
        entities = [
            _Ent("a.py", ["r1", "r2"]),
            _Ent("a.py", ["r1"]),
            _Ent("b.py", ["r1"]),
            _Ent("c.py", None),
            _Ent("d.py", []),
        ]
        rules = [_rule("r1", tags=("T1", "T2")), _rule("r2", plugin="custom_file")]
        telemetry = build_rule_telemetry(entities, rules)
        by_name = {t["rule"]: t for t in telemetry}
        assert by_name["r1"]["entities_matched"] == 3
        assert by_name["r1"]["files_touched"] == 2
        assert by_name["r1"]["plugin"] == "custom_dir:test"
        assert by_name["r1"]["severity"] == "warning"
        assert by_name["r1"]["rule_id"] == "rid-r1"
        assert by_name["r1"]["tags_emitted"] == ["T1", "T2"]
        assert by_name["r2"]["entities_matched"] == 1
        assert by_name["r2"]["plugin"] == "custom_file"

    def test_sorted_deterministic(self):
        entities = [_Ent("a.py", ["z_rule", "a_rule"])]
        telemetry = build_rule_telemetry(entities, [])
        assert [t["rule"] for t in telemetry] == ["a_rule", "z_rule"]

    def test_unknown_rule_name_tolerated(self):
        """bsg.rules entry without a loaded RuleDefinition still reports."""
        entities = [_Ent("a.py", ["ghost_rule"])]
        telemetry = build_rule_telemetry(entities, [])
        assert telemetry[0]["rule"] == "ghost_rule"
        assert telemetry[0]["rule_id"] == "ghost_rule"
        assert telemetry[0]["plugin"] == ""
        assert telemetry[0]["entities_matched"] == 1

    def test_empty_inputs(self):
        assert build_rule_telemetry([], []) == []
        assert build_rule_telemetry([_Ent("a.py", None)], []) == []


class TestRuleStatsPersistence:
    """run_artifacts.rule_stats_json round-trip + config gate (T05)."""

    def _payload(self) -> dict:
        return {
            "schema_version": "rule-stats.v1",
            "run_kind": "build",
            "rules_fingerprint": "abc123",
            "rules_loaded": 5,
            "entities_updated": 42,
            "rule_hits": {"r1": 3, "r2": 1},
            "plugin_hits": {"custom_dir:p": 4},
            "rule_perf": {},
            "interception_totals": {},
            "plugin_files": {"custom_dir:p": ".batho/plugins/p.yaml"},
            "per_rule": [{"rule": "r1", "entities_matched": 3}],
        }

    def test_finalize_get_roundtrip(self, tmp_path):
        from batho.modules.storage.arrow_bundle.bundle import BathoBundle

        db = BathoBundle(tmp_path)
        run_id = db.create_run("r1")
        payload = self._payload()
        db.finalize_run_artifacts(run_id, artifacts={"rule_stats": payload})
        got = db.get_run_artifacts(run_id)
        assert got is not None
        assert got["rule_stats"] == payload

    def test_config_gate_nulls_column(self, tmp_path):
        from batho.modules.storage.arrow_bundle.bundle import BathoBundle

        db = BathoBundle(tmp_path)
        run_id = db.create_run("r1")
        db.finalize_run_artifacts(
            run_id,
            artifacts={"rule_stats": self._payload()},
            blob_config={"run_artifacts": {"rule_stats": False}},
        )
        got = db.get_run_artifacts(run_id)
        assert got is not None
        assert got["rule_stats"] is None

    def test_missing_payload_nulls_column(self, tmp_path):
        """Rules disabled → artifacts omit rule_stats → column reads null."""
        from batho.modules.storage.arrow_bundle.bundle import BathoBundle

        db = BathoBundle(tmp_path)
        run_id = db.create_run("r1")
        db.finalize_run_artifacts(run_id, artifacts={})
        got = db.get_run_artifacts(run_id)
        assert got is not None
        assert got["rule_stats"] is None


class TestPluginFilesAttribution:
    """load_effective_rules stats expose plugin_id -> YAML path (T05)."""

    def test_plugin_files_populated(self, tmp_path):
        from pathlib import Path as P
        from batho.modules.compression.rules import load_effective_rules

        plugin_dir = P(tmp_path) / "plugins"
        plugin_dir.mkdir()
        (plugin_dir / "p.yaml").write_text(
            """schema_version: bsg-plugin.v2
plugin_id: test_p
name: Test P
version: 1.0.0
enabled: true
rules:
  - rule_id: r-p
    name: r-p
    severity: warning
    matchers:
      file_patterns: ["**/x.txt"]
    actions:
      add_usn_tags: [T]
""",
            encoding="utf-8",
        )
        cfg = {
            "enabled": True,
            "auto_load_all_plugins": False,
            "builtin_plugins": [],
            "custom_rules_dir": str(plugin_dir),
        }
        _, stats1 = load_effective_rules(cfg, P(tmp_path))
        pf1 = stats1.get("plugin_files") or {}
        assert pf1.get("custom_dir:p.yaml") == (plugin_dir / "p.yaml").as_posix()

        # cache-hit path carries it too
        _, stats2 = load_effective_rules(cfg, P(tmp_path))
        assert stats2["cache_hit"] is True
        assert stats2.get("plugin_files") == pf1
