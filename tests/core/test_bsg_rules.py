"""Tests for BSG plugin rule loading and application."""

from __future__ import annotations

import json
import pickle
from pathlib import Path

from batho_core.bsg import apply_rule_plugins, load_effective_rules
from batho_core.config import get_config_cached
from batho_core.context.codegraph import InMemoryGraph
from batho_core.context.schema import Entity, EntityType, Relationship, RelationshipType


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

    def test_malformed_custom_yaml_reports_line_hint(self, tmp_path: Path):
        bad_rules = tmp_path / "bad-rules.yaml"
        bad_rules.write_text(
            """
rules:
  - name: broken-rule
    severity: critical
    matchers:
      entity_types: [function]
    actions:
      metadata:
        bsg.category: TEST
""".strip()
            + "\n",
            encoding="utf-8",
        )

        rules_cfg = {
            "enabled": True,
            "builtin_plugins": [],
            "custom_rules_path": str(bad_rules),
        }

        rules, stats = load_effective_rules(rules_cfg, root_path=tmp_path)

        assert rules == []
        assert stats["errors"]
        assert "line " in stats["errors"][0]

    def test_rule_shadowing_override_updates_custom_rule(self, mock_graph):
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
            "plugins_overrides": {
                "custom_inline": {
                    "cluster-math": {
                        "actions": {
                            "metadata": {"bsg.cluster_hint": "overridden"}
                        }
                    }
                }
            },
        }

        stats = apply_rule_plugins(
            graph=mock_graph,
            root_path=Path("."),
            rules_config=rules_cfg,
        )

        add_entity = _find_entity_by_name(mock_graph, "add")
        assert add_entity is not None
        assert add_entity.metadata.get("bsg.cluster_hint") == "overridden"
        assert stats["overrides_applied"] == 1

    def test_green_cache_invalidates_after_batho_yaml_change(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        config_file = tmp_path / "batho.yaml"
        config_file.write_text(
            """
rules:
  enabled: true
  builtin_plugins: []
  custom_rules_inline:
    - name: cfg-marker
      entity_types: [function]
      metadata:
        bsg.marker: one
""".strip()
            + "\n",
            encoding="utf-8",
        )

        monkeypatch.chdir(tmp_path)
        get_config_cached.cache_clear()

        cfg_one = get_config_cached()
        rules_one, _ = load_effective_rules(cfg_one["rules"], root_path=tmp_path)

        cache_path = tmp_path / ".ctn" / "rules_cache.bin"
        assert cache_path.exists()
        payload_one = pickle.loads(cache_path.read_bytes())
        assert any(
            rule.actions.metadata.get("bsg.marker") == "one" for rule in rules_one
        )

        config_file.write_text(
            """
rules:
  enabled: true
  builtin_plugins: []
  custom_rules_inline:
    - name: cfg-marker
      entity_types: [function]
      metadata:
        bsg.marker: two
""".strip()
            + "\n",
            encoding="utf-8",
        )

        get_config_cached.cache_clear()
        cfg_two = get_config_cached()
        rules_two, _ = load_effective_rules(cfg_two["rules"], root_path=tmp_path)
        payload_two = pickle.loads(cache_path.read_bytes())

        assert payload_one["config_fingerprint"] != payload_two["config_fingerprint"]
        assert any(
            rule.actions.metadata.get("bsg.marker") == "two" for rule in rules_two
        )

    def test_interception_stats_written_for_plugin_hits(
        self,
        tmp_path: Path,
        mock_graph,
    ):
        rules_cfg = {
            "enabled": True,
            "builtin_plugins": [],
            "custom_rules_inline": [
                {
                    "name": "hit-counter-rule",
                    "entity_types": ["function"],
                    "name_patterns": ["add"],
                    "metadata": {"bsg.marker": "hit"},
                }
            ],
        }

        stats = apply_rule_plugins(
            graph=mock_graph,
            root_path=tmp_path,
            rules_config=rules_cfg,
        )

        interception_file = tmp_path / ".ctn" / "interception_stats.json"
        assert interception_file.exists()

        payload = json.loads(interception_file.read_text(encoding="utf-8"))
        plugin_payload = payload.get("plugins", {}).get("custom_inline", {})
        assert plugin_payload.get("interceptions", 0) >= 1
        assert stats.get("plugin_hits", {}).get("custom_inline", 0) >= 1

    def test_semantic_edges_enable_ast_edge_matchers(self, tmp_path: Path):
        graph = InMemoryGraph()

        api = Entity(
            type=EntityType.FUNCTION,
            name="get_user_endpoint",
            file="services/api/routes.py",
            start_line=1,
            end_line=10,
            metadata={"language": "python"},
        )
        auth = Entity(
            type=EntityType.FUNCTION,
            name="jwt_auth_middleware",
            file="services/api/middleware.py",
            start_line=12,
            end_line=22,
            metadata={"language": "python"},
        )
        client = Entity(
            type=EntityType.FUNCTION,
            name="render_dashboard",
            file="services/web/client.py",
            start_line=1,
            end_line=8,
            metadata={"language": "python"},
        )

        for entity in (api, auth, client):
            graph.add_entity(entity)

        graph.add_relationship(
            Relationship(
                source_id=api.id,
                target_id=auth.id,
                type=RelationshipType.CALLS,
                metadata={"line_number": 5},
            )
        )
        graph.add_relationship(
            Relationship(
                source_id=client.id,
                target_id=api.id,
                type=RelationshipType.CALLS,
                metadata={"line_number": 3},
            )
        )

        rules_cfg = {
            "enabled": True,
            "builtin_plugins": [],
            "custom_rules_inline": [
                {
                    "name": "semantic-edge-hit",
                    "matchers": {
                        "usn_tags_any": ["apiboundary"],
                        "ast_edges": {
                            "all": [
                                {
                                    "edge": "WRAPPED_BY",
                                    "direction": "outbound",
                                    "target_usn_tags_any": ["authmiddleware"],
                                    "min_count": 1,
                                },
                                {
                                    "edge": "DEPENDS_ON_API",
                                    "direction": "inbound",
                                    "min_count": 1,
                                },
                            ]
                        },
                    },
                    "actions": {"metadata": {"bsg.semantic_hit": True}},
                }
            ],
        }

        stats = apply_rule_plugins(graph=graph, root_path=tmp_path, rules_config=rules_cfg)
        api_entity = graph.get_entity(api.id)

        assert api_entity is not None
        assert api_entity.metadata.get("bsg.semantic_hit") is True
        assert stats.get("semantic_edges_added", 0) >= 2
        assert any(rel.type == RelationshipType.WRAPPED_BY for rel in graph.relationships)
        assert any(rel.type == RelationshipType.DEPENDS_ON_API for rel in graph.relationships)

    def test_semantic_referenced_in_edge_from_name_overlap(self, tmp_path: Path):
        graph = InMemoryGraph()

        env_value = Entity(
            type=EntityType.CONSTANT,
            name="PAYMENTS_DB_URL",
            file="src/settings.py",
            start_line=1,
            end_line=1,
            metadata={"language": "python"},
        )
        infra_setting = Entity(
            type=EntityType.SETTING,
            name="payments_db_url",
            file="infra/main.tf",
            start_line=8,
            end_line=8,
            metadata={"language": "hcl"},
        )

        graph.add_entity(env_value)
        graph.add_entity(infra_setting)

        rules_cfg = {
            "enabled": True,
            "builtin_plugins": [],
            "custom_rules_inline": [
                {
                    "name": "semantic-env-infra-hit",
                    "matchers": {
                        "usn_tags_any": ["environmentvariable"],
                        "ast_edges": {
                            "all": [
                                {
                                    "edge": "REFERENCED_IN",
                                    "direction": "outbound",
                                    "target_usn_tags_any": ["infrastructureconfig"],
                                    "min_count": 1,
                                }
                            ]
                        },
                    },
                    "actions": {"metadata": {"bsg.drift_checked": True}},
                }
            ],
        }

        stats = apply_rule_plugins(graph=graph, root_path=tmp_path, rules_config=rules_cfg)
        env_entity = graph.get_entity(env_value.id)

        assert env_entity is not None
        assert env_entity.metadata.get("bsg.drift_checked") is True
        assert stats.get("semantic_edges_added", 0) >= 1
        assert any(rel.type == RelationshipType.REFERENCED_IN for rel in graph.relationships)

    def test_semantic_referenced_in_name_overlap_limits_fanout(self, tmp_path: Path):
        graph = InMemoryGraph()

        env_value = Entity(
            type=EntityType.CONSTANT,
            name="SERVICE_URL",
            file="src/settings.py",
            start_line=1,
            end_line=1,
            metadata={"language": "python"},
        )
        graph.add_entity(env_value)

        for idx, name in enumerate(
            [
                "service_url",
                "service_host",
                "service_port",
                "service_path",
                "service_name",
            ],
            start=1,
        ):
            graph.add_entity(
                Entity(
                    type=EntityType.SETTING,
                    name=name,
                    file=f"infra/item_{idx}.tf",
                    start_line=idx,
                    end_line=idx,
                    metadata={"language": "hcl"},
                )
            )

        stats = apply_rule_plugins(
            graph=graph,
            root_path=tmp_path,
            rules_config={
                "enabled": True,
                "builtin_plugins": [],
                "custom_rules_inline": [],
            },
        )

        referenced_edges = [
            rel
            for rel in graph.relationships
            if rel.type == RelationshipType.REFERENCED_IN
            and rel.source_id == env_value.id
        ]

        assert stats.get("semantic_edges_added", 0) >= 1
        assert len(referenced_edges) == 1
