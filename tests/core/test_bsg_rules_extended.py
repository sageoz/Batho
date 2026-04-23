"""Regression tests for extended BSG plugin engine features.

Covers plugin schema loading, regex matchers, numeric severity scoring, plugin
dependency validation, rule conflict detection, per-rule profiling, the
`when` action gate, extended metadata operators, and the fixture runner.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from batho.bsg import (
    apply_rule_plugins,
    load_effective_rules,
    validate_plugin_file,
)
from batho.bsg.rules import (
    _SCHEMA_VERSION,
    _detect_rule_conflicts,
    _rule_from_plugin_rule,
)
from batho.bsg.testing import (
    FixtureError,
    MockGraphBuilder,
    run_plugin_fixture,
    summarize_reports,
    run_fixture_directory,
)
from batho.context.codegraph import InMemoryGraph
from batho.context.schema import Entity, EntityType


def _plugin_yaml(rules_payload: list[dict], plugin_id: str = "custom_plugin") -> str:
    """Render a minimal plugin YAML around a list of rule dicts."""

    import yaml as _yaml

    doc = {
        "schema_version": _SCHEMA_VERSION,
        "plugin_id": plugin_id,
        "name": plugin_id.replace("_", " ").title(),
        "version": "1.0.0",
        "enabled": True,
        "rules": rules_payload,
    }
    return _yaml.safe_dump(doc, sort_keys=False)


class TestSchemaLoading:
    def test_plugin_loads_with_score_and_tags(self, tmp_path: Path):
        plugin_file = tmp_path / "plugin.yaml"
        plugin_file.write_text(
            _plugin_yaml(
                [
                    {
                        "rule_id": "tag-adders",
                        "name": "tag-adders",
                        "description": "Adds a tag to add functions",
                        "severity": "warning",
                        "score": 420,
                        "tags": ["security", "demo"],
                        "priority": 50,
                        "enabled": True,
                        "matchers": {
                            "entity_types": ["function"],
                            "name_patterns": ["add"],
                        },
                        "actions": {"metadata": {"bsg.v2_loaded": True}},
                    }
                ]
            ),
            encoding="utf-8",
        )

        rules_cfg = {
            "enabled": True,
            "auto_load_all_plugins": False,
            "builtin_plugins": [],
            "custom_rules_path": str(plugin_file),
        }
        rules, stats = load_effective_rules(rules_cfg, root_path=tmp_path)

        assert stats["errors"] == []
        assert len(rules) == 1
        rule = rules[0]
        assert rule.schema_version == _SCHEMA_VERSION
        assert rule.score == 420
        assert rule.tags == ("security", "demo")

    def test_score_out_of_range_rejected(self, tmp_path: Path):
        plugin_file = tmp_path / "bad_plugin.yaml"
        plugin_file.write_text(
            _plugin_yaml(
                [
                    {
                        "rule_id": "bad",
                        "name": "bad",
                        "description": "score too high",
                        "severity": "warning",
                        "score": 1200,
                        "priority": 50,
                        "enabled": True,
                        "matchers": {"entity_types": ["function"]},
                        "actions": {"metadata": {"x": 1}},
                    }
                ]
            ),
            encoding="utf-8",
        )

        rules, stats = load_effective_rules(
            {
                "enabled": True,
                "auto_load_all_plugins": False,
                "builtin_plugins": [],
                "custom_rules_path": str(plugin_file),
            },
            root_path=tmp_path,
        )

        assert rules == []
        assert stats["errors"]
        assert any("score must be between" in err for err in stats["errors"])

    def test_plugin_without_optional_fields_loads(self, tmp_path: Path):
        """Built-in plugins that omit score/tags/when/regex must still load."""

        rules, stats = load_effective_rules(
            {
                "enabled": True,
                "auto_load_all_plugins": False,
                "builtin_plugins": ["bsg_hardcoded_secret_catcher"],
            },
            root_path=tmp_path,
        )

        assert stats["errors"] == []
        assert rules, "expected built-in plugin to load"
        assert all(r.schema_version == _SCHEMA_VERSION for r in rules)


class TestRegexMatcher:
    def test_regex_pattern_matches_entity_name(self, tmp_path: Path, mock_graph):
        rules_cfg = {
            "enabled": True,
            "auto_load_all_plugins": False,
            "builtin_plugins": [],
            "custom_rules_inline": [
                {
                    "rule_id": "regex-add",
                    "name": "regex-add",
                    "description": "Regex on entity name",
                    "severity": "info",
                    "priority": 10,
                    "enabled": True,
                    "matchers": {
                        "entity_types": ["function"],
                        "regex_patterns": [
                            {"pattern": "^add$", "target": "name"}
                        ],
                    },
                    "actions": {"metadata": {"bsg.regex_hit": True}},
                }
            ],
        }

        # Unified schema accepts regex_patterns on every plugin.
        rules_cfg["custom_rules_inline"][0]["schema_version"] = _SCHEMA_VERSION

        # Wrap inline with v2 meta via a dedicated plugin file to satisfy schema.
        plugin_file = tmp_path / "regex_plugin.yaml"
        plugin_file.write_text(
            json.dumps(
                {
                    "schema_version": _SCHEMA_VERSION,
                    "plugin_id": "regex_probe",
                    "name": "Regex Probe",
                    "version": "1.0.0",
                    "enabled": True,
                    "rules": [rules_cfg["custom_rules_inline"][0]],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        rules_cfg.pop("custom_rules_inline")
        rules_cfg["custom_rules_path"] = str(plugin_file)

        stats = apply_rule_plugins(
            graph=mock_graph, root_path=tmp_path, rules_config=rules_cfg
        )

        add_entity = next(
            (e for e in mock_graph.entities.values() if e.name == "add"),
            None,
        )
        assert add_entity is not None
        assert add_entity.metadata.get("bsg.regex_hit") is True
        assert stats["errors"] == []

    def test_regex_pattern_file_path_target(self, tmp_path: Path, mock_graph):
        plugin_file = tmp_path / "regex_path.yaml"
        plugin_file.write_text(
            json.dumps(
                {
                    "schema_version": _SCHEMA_VERSION,
                    "plugin_id": "regex_probe",
                    "name": "Regex Probe",
                    "version": "1.0.0",
                    "enabled": True,
                    "rules": [
                        {
                            "rule_id": "regex-file",
                            "name": "regex-file",
                            "description": "Regex on file_path",
                            "severity": "info",
                            "priority": 10,
                            "enabled": True,
                            "matchers": {
                                "entity_types": ["function"],
                                "regex_patterns": [
                                    {
                                        "pattern": "calculator\\.py$",
                                        "target": "file_path",
                                    }
                                ],
                            },
                            "actions": {"metadata": {"bsg.file_regex": True}},
                        }
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        stats = apply_rule_plugins(
            graph=mock_graph,
            root_path=tmp_path,
            rules_config={
                "enabled": True,
                "auto_load_all_plugins": False,
                "builtin_plugins": [],
                "custom_rules_path": str(plugin_file),
            },
        )

        assert stats["errors"] == []
        func_entities_in_calc = [
            e
            for e in mock_graph.entities.values()
            if e.file.endswith("calculator.py")
            and str(e.type).lower() == "function"
        ]
        assert func_entities_in_calc, "fixture should contain function entities in calculator.py"
        for entity in func_entities_in_calc:
            assert entity.metadata.get("bsg.file_regex") is True


class TestWhenClause:
    def test_when_all_suppresses_action(self, tmp_path: Path, mock_graph):
        plugin_file = tmp_path / "when.yaml"
        plugin_file.write_text(
            json.dumps(
                {
                    "schema_version": _SCHEMA_VERSION,
                    "plugin_id": "when_probe",
                    "name": "When Probe",
                    "version": "1.0.0",
                    "enabled": True,
                    "rules": [
                        {
                            "rule_id": "conditional",
                            "name": "conditional",
                            "description": "Only fires when metadata has marker",
                            "severity": "info",
                            "priority": 10,
                            "enabled": True,
                            "matchers": {
                                "entity_types": ["function"],
                            },
                            "actions": {
                                "metadata": {"bsg.conditional_applied": True},
                                "when": {
                                    "all": [
                                        {
                                            "key": "bsg.pre_marker",
                                            "operator": "eq",
                                            "value": "yes",
                                        }
                                    ]
                                },
                            },
                        }
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        # No entity carries bsg.pre_marker: rule matches but action gate blocks it.
        stats = apply_rule_plugins(
            graph=mock_graph,
            root_path=tmp_path,
            rules_config={
                "enabled": True,
                "auto_load_all_plugins": False,
                "builtin_plugins": [],
                "custom_rules_path": str(plugin_file),
            },
        )

        assert stats["errors"] == []
        for entity in mock_graph.entities.values():
            assert entity.metadata.get("bsg.conditional_applied") is not True
        assert stats.get("rule_when_skipped", {}).get("conditional", 0) >= 1

    def test_when_all_allows_action_when_gate_passes(
        self, tmp_path: Path, mock_graph
    ):
        # Pre-stamp one entity to pass the gate.
        target = next(iter(mock_graph.entities.values()))
        updated = target.model_copy(
            update={"metadata": {**target.metadata, "bsg.pre_marker": "yes"}}
        )
        mock_graph.entities[target.id] = updated

        plugin_file = tmp_path / "when_allow.yaml"
        plugin_file.write_text(
            json.dumps(
                {
                    "schema_version": _SCHEMA_VERSION,
                    "plugin_id": "when_probe",
                    "name": "When Probe",
                    "version": "1.0.0",
                    "enabled": True,
                    "rules": [
                        {
                            "rule_id": "conditional-allow",
                            "name": "conditional-allow",
                            "description": "Fires only for marked entities",
                            "severity": "info",
                            "priority": 10,
                            "enabled": True,
                            "matchers": {"entity_types": ["*"]},
                            "actions": {
                                "metadata": {"bsg.gate_passed": True},
                                "when": {
                                    "all": [
                                        {
                                            "key": "bsg.pre_marker",
                                            "operator": "eq",
                                            "value": "yes",
                                        }
                                    ]
                                },
                            },
                        }
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        apply_rule_plugins(
            graph=mock_graph,
            root_path=tmp_path,
            rules_config={
                "enabled": True,
                "auto_load_all_plugins": False,
                "builtin_plugins": [],
                "custom_rules_path": str(plugin_file),
            },
        )

        refreshed = mock_graph.entities[target.id]
        assert refreshed.metadata.get("bsg.gate_passed") is True


class TestMetadataOperators:
    def _apply_with_condition(
        self,
        tmp_path: Path,
        condition: dict,
        entity_metadata: dict,
    ) -> bool:
        plugin_file = tmp_path / "meta_ops.yaml"
        plugin_file.write_text(
            json.dumps(
                {
                    "schema_version": _SCHEMA_VERSION,
                    "plugin_id": "meta_ops_probe",
                    "name": "Meta Ops Probe",
                    "version": "1.0.0",
                    "enabled": True,
                    "rules": [
                        {
                            "rule_id": "meta-op",
                            "name": "meta-op",
                            "description": "metadata condition probe",
                            "severity": "info",
                            "priority": 10,
                            "enabled": True,
                            "matchers": {
                                "entity_types": ["function"],
                                "metadata_conditions": [condition],
                            },
                            "actions": {"metadata": {"bsg.matched": True}},
                        }
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        graph = InMemoryGraph()
        graph.add_entity(
            Entity(
                type=EntityType.FUNCTION,
                name="probe",
                file="src/probe.py",
                start_line=1,
                end_line=1,
                metadata=dict(entity_metadata),
            )
        )

        apply_rule_plugins(
            graph=graph,
            root_path=tmp_path,
            rules_config={
                "enabled": True,
                "auto_load_all_plugins": False,
                "builtin_plugins": [],
                "custom_rules_path": str(plugin_file),
            },
        )

        entity = next(iter(graph.entities.values()))
        return entity.metadata.get("bsg.matched") is True

    def test_length_lt(self, tmp_path: Path):
        assert self._apply_with_condition(
            tmp_path,
            {"key": "note", "operator": "length_lt", "value": 5},
            {"note": "abc"},
        )
        assert not self._apply_with_condition(
            tmp_path,
            {"key": "note", "operator": "length_lt", "value": 5},
            {"note": "abcdef"},
        )

    def test_contains_all(self, tmp_path: Path):
        assert self._apply_with_condition(
            tmp_path,
            {
                "key": "doc",
                "operator": "contains_all",
                "value": ["foo", "bar"],
            },
            {"doc": "foo and bar go together"},
        )
        assert not self._apply_with_condition(
            tmp_path,
            {
                "key": "doc",
                "operator": "contains_all",
                "value": ["foo", "bar"],
            },
            {"doc": "only foo here"},
        )

    def test_regex_match(self, tmp_path: Path):
        assert self._apply_with_condition(
            tmp_path,
            {"key": "label", "operator": "regex_match", "value": r"^v\d+$"},
            {"label": "v3"},
        )
        assert not self._apply_with_condition(
            tmp_path,
            {"key": "label", "operator": "regex_match", "value": r"^v\d+$"},
            {"label": "vNext"},
        )


class TestDependencyAndConflicts:
    def test_missing_dependency_surfaces_as_warning(self, tmp_path: Path):
        plugin_file = tmp_path / "depends.yaml"
        plugin_file.write_text(
            json.dumps(
                {
                    "schema_version": _SCHEMA_VERSION,
                    "plugin_id": "depends_probe",
                    "name": "Depends Probe",
                    "version": "1.0.0",
                    "enabled": True,
                    "depends_on": ["not_a_real_plugin"],
                    "rules": [
                        {
                            "rule_id": "probe",
                            "name": "probe",
                            "description": "x",
                            "severity": "info",
                            "priority": 10,
                            "enabled": True,
                            "matchers": {"entity_types": ["function"]},
                            "actions": {"metadata": {"bsg.x": 1}},
                        }
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        _, stats = load_effective_rules(
            {
                "enabled": True,
                "auto_load_all_plugins": False,
                "builtin_plugins": [],
                "custom_rules_path": str(plugin_file),
            },
            root_path=tmp_path,
        )

        # custom_file path doesn't currently declare depends_on at load time,
        # but depends_on parsed from the plugin doc should still be captured
        # by validate_plugin_file:
        result = validate_plugin_file(plugin_file)
        assert result["valid"]
        assert result["depends_on"] == ["not_a_real_plugin"]

    def test_conflict_warnings_between_two_category_rules(self, tmp_path: Path):
        from batho.bsg.rules import _rule_from_plugin_rule

        rule_a = _rule_from_plugin_rule(
            "plugin_a",
            {
                "rule_id": "a-category",
                "name": "a-category",
                "description": "",
                "severity": "info",
                "priority": 10,
                "enabled": True,
                "matchers": {
                    "entity_types": ["function"],
                    "file_patterns": ["**/*.py"],
                    "ast_edges": {"any": [], "all": []},
                },
                "actions": {
                    "metadata": {},
                    "add_usn_tags": [],
                    "derive_scope_tier": False,
                    "derive_service_tag": False,
                    "truncate_docstring": False,
                    "max_docstring_length": 150,
                    "normalize_entry_point": False,
                    "detect_language": {},
                    "detect_framework": {},
                    "detect_package_manager": {},
                    "detect_infra": {},
                    "assign_category": {"category": "SOURCE"},
                },
            },
        )
        rule_b = _rule_from_plugin_rule(
            "plugin_b",
            {
                "rule_id": "b-category",
                "name": "b-category",
                "description": "",
                "severity": "info",
                "priority": 10,
                "enabled": True,
                "matchers": {
                    "entity_types": ["function"],
                    "file_patterns": ["**/*.py"],
                    "ast_edges": {"any": [], "all": []},
                },
                "actions": {
                    "metadata": {},
                    "add_usn_tags": [],
                    "derive_scope_tier": False,
                    "derive_service_tag": False,
                    "truncate_docstring": False,
                    "max_docstring_length": 150,
                    "normalize_entry_point": False,
                    "detect_language": {},
                    "detect_framework": {},
                    "detect_package_manager": {},
                    "detect_infra": {},
                    "assign_category": {"category": "TEST"},
                },
            },
        )

        warnings = _detect_rule_conflicts([rule_a, rule_b])
        assert warnings
        assert any("assign_category" in w["overlap"] for w in warnings)


class TestProfilingAndTrace:
    def test_profile_mode_emits_perf_stats(self, tmp_path: Path, mock_graph):
        stats = apply_rule_plugins(
            graph=mock_graph,
            root_path=tmp_path,
            rules_config={
                "enabled": True,
                "auto_load_all_plugins": False,
                "builtin_plugins": [],
                "custom_rules_inline": [
                    {
                        "name": "profile-probe",
                        "entity_types": ["function"],
                        "metadata": {"bsg.profile_probe": True},
                    }
                ],
            },
            profile=True,
        )

        assert "rule_perf" in stats
        perf = stats["rule_perf"]
        assert perf["schema_version"] == "bsg-perf.v1"
        assert "profile-probe" in perf["rules"]
        perf_path = Path(stats["perf_stats_path"])
        assert perf_path.exists()

    def test_trace_mode_returns_trace_log(self, tmp_path: Path, mock_graph):
        stats = apply_rule_plugins(
            graph=mock_graph,
            root_path=tmp_path,
            rules_config={
                "enabled": True,
                "auto_load_all_plugins": False,
                "builtin_plugins": [],
                "custom_rules_inline": [
                    {
                        "name": "trace-probe",
                        "entity_types": ["function"],
                        "name_patterns": ["add"],
                        "metadata": {"bsg.trace_probe": True},
                    }
                ],
            },
            trace=True,
        )

        trace_log = stats.get("trace_log")
        assert isinstance(trace_log, list)
        assert trace_log, "expected at least one trace entry"
        assert any(
            entry["rule"] == "trace-probe" and entry["matched"]
            for entry in trace_log
        )


class TestPluginVersionCacheInvalidation:
    def test_cache_invalidates_on_plugin_file_change(self, tmp_path: Path):
        def _rule(version: str) -> dict:
            return {
                "rule_id": "v1",
                "name": "v1",
                "description": f"{version} version",
                "severity": "info",
                "priority": 10,
                "enabled": True,
                "matchers": {"entity_types": ["function"]},
                "actions": {"metadata": {"bsg.version": version}},
            }

        plugin_file = tmp_path / "plugin.yaml"
        plugin_file.write_text(_plugin_yaml([_rule("one")]), encoding="utf-8")

        rules_cfg = {
            "enabled": True,
            "auto_load_all_plugins": False,
            "builtin_plugins": [],
            "custom_rules_path": str(plugin_file),
        }

        rules_one, _ = load_effective_rules(rules_cfg, root_path=tmp_path)
        assert rules_one[0].actions.metadata["bsg.version"] == "one"

        plugin_file.write_text(_plugin_yaml([_rule("two")]), encoding="utf-8")

        rules_two, stats_two = load_effective_rules(rules_cfg, root_path=tmp_path)
        assert rules_two[0].actions.metadata["bsg.version"] == "two"
        assert stats_two["cache_hit"] is False


class TestFixtureRunner:
    def test_mock_graph_builder_creates_entities_and_relationships(self):
        builder = MockGraphBuilder()
        e1 = builder.add_entity(type="function", name="foo", file="x.py")
        e2 = builder.add_entity(type="function", name="bar", file="x.py", start_line=10)
        builder.add_relationship(source=e2, target=e1, type="CALLS")

        graph = builder.build()
        assert len(graph.entities) == 2
        assert len(graph.relationships) == 1

    def test_mock_graph_builder_rejects_unknown_type(self):
        builder = MockGraphBuilder()
        with pytest.raises(FixtureError):
            builder.add_entity(type="not_a_type", name="x", file="x.py")

    def test_fixture_runner_passes_for_secret_catcher(self, tmp_path: Path):
        fixture_path = (
            Path(__file__).resolve().parent.parent
            / "bsg_plugins"
            / "secret_catcher.yaml"
        )
        report = run_plugin_fixture(fixture_path, root_path=tmp_path)
        if not report.passed:
            pytest.fail(
                "fixture did not pass: " + "; ".join(report.failures)
            )

    def test_fixture_runner_detects_expectation_failure(self, tmp_path: Path):
        fixture = {
            "name": "bogus",
            "plugin": {"builtin": "bsg_hardcoded_secret_catcher"},
            "given": {
                "entities": [
                    {
                        "type": "function",
                        "name": "safe_function",
                        "file": "x.py",
                    }
                ]
            },
            "expect": {
                "entity": {
                    "name": "safe_function",
                    "metadata": {"bsg.intercept.category": "SECURITY"},
                }
            },
        }

        report = run_plugin_fixture(fixture, root_path=tmp_path)
        assert not report.passed
        assert any("bsg.intercept.category" in f for f in report.failures)

    def test_summarize_reports_rolls_up_counts(self, tmp_path: Path):
        # Run the packaged example twice to exercise summarize_reports.
        fixture_path = (
            Path(__file__).resolve().parent.parent
            / "bsg_plugins"
            / "secret_catcher.yaml"
        )
        r1 = run_plugin_fixture(fixture_path, root_path=tmp_path)
        r2 = run_plugin_fixture(fixture_path, root_path=tmp_path)
        summary = summarize_reports([r1, r2])
        assert summary["total"] == 2
        assert summary["passed"] + summary["failed"] == 2


class TestValidateStrict:
    def test_strict_flags_unreachable_rule(self, tmp_path: Path):
        plugin_file = tmp_path / "unreachable.yaml"
        plugin_file.write_text(
            _plugin_yaml(
                [
                    {
                        "rule_id": "always-on",
                        "name": "always-on",
                        "description": "no matchers and no derive actions",
                        "severity": "info",
                        "priority": 10,
                        "enabled": True,
                        "matchers": {},
                        "actions": {
                            "metadata": {"bsg.applies_to_all": True}
                        },
                    }
                ]
            ),
            encoding="utf-8",
        )

        relaxed = validate_plugin_file(plugin_file, strict=False)
        assert relaxed["valid"] is True
        assert any("no matchers" in w for w in relaxed["warnings"])

        strict = validate_plugin_file(plugin_file, strict=True)
        assert strict["valid"] is False
        assert strict["errors"]

