"""Tests for BSG plugin rule loading and application."""

from __future__ import annotations

from pathlib import Path

from batho_core.bsg import apply_rule_plugins


def _find_entity_by_name(graph, name: str):
    for entity in graph.entities.values():
        if entity.name == name:
            return entity
    return None


class TestBSGRules:
    def test_apply_inline_custom_rule_updates_metadata(self, mock_graph):
        rules_cfg = {
            "enabled": True,
            "builtin_plugins": [],
            "custom_rules_inline": [
                {
                    "name": "cluster-math",
                    "entity_types": ["function"],
                    "name_patterns": ["add"],
                    "metadata": {"bsg.cluster_hint": "math"},
                }
            ],
        }

        stats = apply_rule_plugins(
            graph=mock_graph,
            root_path=Path("."),
            rules_config=rules_cfg,
        )

        add_entity = _find_entity_by_name(mock_graph, "add")
        assert add_entity is not None
        assert add_entity.metadata.get("bsg.cluster_hint") == "math"
        assert "cluster-math" in add_entity.metadata.get("bsg.rules", [])
        assert stats["rules_applied"] == 1
        assert stats["entities_updated"] >= 1

    def test_apply_custom_rules_from_yaml_file(self, tmp_path: Path, mock_graph):
        custom_rules = tmp_path / "custom-rules.yaml"
        custom_rules.write_text(
            """
rules:
  - name: from-yaml
    file_patterns: ["src/*.py"]
    metadata:
      bsg.category: SOURCE
""".strip()
            + "\n",
            encoding="utf-8",
        )

        rules_cfg = {
            "enabled": True,
            "builtin_plugins": [],
            "custom_rules_path": str(custom_rules),
        }

        stats = apply_rule_plugins(
            graph=mock_graph,
            root_path=Path("."),
            rules_config=rules_cfg,
        )

        add_entity = _find_entity_by_name(mock_graph, "add")
        assert add_entity is not None
        assert add_entity.metadata.get("bsg.category") == "SOURCE"
        assert stats["custom_file_count"] == 1

    def test_disabled_rule_is_not_applied(self, mock_graph):
        rules_cfg = {
            "enabled": True,
            "builtin_plugins": [],
            "disabled_rules": ["do-not-apply"],
            "custom_rules_inline": [
                {
                    "name": "do-not-apply",
                    "entity_types": ["function"],
                    "metadata": {"bsg.cluster_hint": "blocked"},
                }
            ],
        }

        stats = apply_rule_plugins(
            graph=mock_graph,
            root_path=Path("."),
            rules_config=rules_cfg,
        )

        add_entity = _find_entity_by_name(mock_graph, "add")
        assert add_entity is not None
        assert add_entity.metadata.get("bsg.cluster_hint") != "blocked"
        assert stats["rules_applied"] == 0

    def test_builtin_plugin_applies_scope_metadata(self, mock_graph):
        rules_cfg = {
            "enabled": True,
            "builtin_plugins": ["bsg_core"],
        }

        stats = apply_rule_plugins(
            graph=mock_graph,
            root_path=Path("."),
            rules_config=rules_cfg,
        )

        assert stats["rules_loaded"] >= 1
        assert any(
            entity.metadata.get("bsg.scope_tier")
            for entity in mock_graph.entities.values()
        )
