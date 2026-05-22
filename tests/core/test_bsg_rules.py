"""Tests for BSG plugin rule loading and application."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from batho.bsg import apply_rule_plugins, load_effective_rules
from batho.config import get_config_cached
from batho.context.codegraph import InMemoryGraph
from batho.context.schema import Entity, EntityType, Relationship, RelationshipType


def _find_entity_by_name(graph, name: str):
    for entity in graph.entities.values():
        if entity.name == name:
            return entity
    return None


class TestBSGRules:
    def test_apply_inline_custom_rule_updates_metadata(self, mock_graph):
        rules_cfg = {
            "enabled": True,
            "auto_load_all_plugins": False,
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
            "auto_load_all_plugins": False,
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
            "auto_load_all_plugins": False,
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
            "auto_load_all_plugins": False,
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
            "auto_load_all_plugins": False,
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

        cache_path = tmp_path / ".ctn" / "local" / "cache" / "rules_cache.bin"
        assert cache_path.exists()
        payload_one = json.loads(cache_path.read_text(encoding="utf-8"))
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
        payload_two = json.loads(cache_path.read_text(encoding="utf-8"))

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
            "auto_load_all_plugins": False,
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

        interception_file = tmp_path / ".ctn" / "local" / "metrics" / "interception_stats.json"
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
            "auto_load_all_plugins": False,
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
            "auto_load_all_plugins": False,
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
                "auto_load_all_plugins": False,
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

    def test_bidirectional_matchers_gap_entity_types(self, tmp_path: Path):
        """Test that bidirectional gap_entity_types matcher works."""
        graph = InMemoryGraph()

        # Create a SYNTAX_GLUE entity (gap)
        gap_entity = Entity(
            type=EntityType.SYNTAX_GLUE,
            name="<glue>",
            file="test.py",
            start_line=1,
            end_line=1,
            start_byte=0,
            end_byte=5,
            raw_content="    ",
            metadata={"gap_type": "whitespace"},
        )
        
        # Create a regular function entity
        func_entity = Entity(
            type=EntityType.FUNCTION,
            name="my_func",
            file="test.py",
            start_line=2,
            end_line=5,
            start_byte=5,
            end_byte=20,
            raw_content="def my_func(): pass",
        )
        
        graph.add_entity(gap_entity)
        graph.add_entity(func_entity)

        rules_cfg = {
            "enabled": True,
            "auto_load_all_plugins": False,
            "builtin_plugins": [],
            "custom_rules_inline": [
                {
                    "name": "gap-marker",
                    "matchers": {
                        "gap_entity_types": ["SYNTAX_GLUE"],
                    },
                    "actions": {"metadata": {"bsg.is_gap": True}},
                }
            ],
        }

        stats = apply_rule_plugins(graph=graph, root_path=tmp_path, rules_config=rules_cfg)
        
        # Only the gap entity should be marked
        assert graph.get_entity(gap_entity.id).metadata.get("bsg.is_gap") is True
        assert graph.get_entity(func_entity.id).metadata.get("bsg.is_gap") is None

    def test_bidirectional_matchers_has_raw_content(self, tmp_path: Path):
        """Test that bidirectional has_raw_content matcher works."""
        graph = InMemoryGraph()

        # Entity with raw_content
        entity_with_content = Entity(
            type=EntityType.FUNCTION,
            name="has_content",
            file="test.py",
            start_line=1,
            end_line=1,
            start_byte=0,
            end_byte=10,
            raw_content="def foo(): pass",
        )
        
        # Entity without raw_content (unresolved)
        entity_without_content = Entity(
            type=EntityType.FUNCTION,
            name="no_content",
            file="test.py",
            start_line=2,
            end_line=2,
            start_byte=10,
            end_byte=20,
        )
        
        graph.add_entity(entity_with_content)
        graph.add_entity(entity_without_content)

        rules_cfg = {
            "enabled": True,
            "auto_load_all_plugins": False,
            "builtin_plugins": [],
            "custom_rules_inline": [
                {
                    "name": "content-check",
                    "matchers": {
                        "has_raw_content": True,
                    },
                    "actions": {"metadata": {"bsg.has_raw": True}},
                }
            ],
        }

        stats = apply_rule_plugins(graph=graph, root_path=tmp_path, rules_config=rules_cfg)
        
        # Only the entity with raw_content should be marked
        assert graph.get_entity(entity_with_content.id).metadata.get("bsg.has_raw") is True
        assert graph.get_entity(entity_without_content.id).metadata.get("bsg.has_raw") is None

    def test_bidirectional_actions_verify_coverage(self, tmp_path: Path):
        """Test that bidirectional verify_coverage action works."""
        graph = InMemoryGraph()

        entity = Entity(
            type=EntityType.FUNCTION,
            name="my_func",
            file="test.py",
            start_line=1,
            end_line=1,
            start_byte=0,
            end_byte=10,
            raw_content="def foo(): pass",
        )
        
        graph.add_entity(entity)

        rules_cfg = {
            "enabled": True,
            "auto_load_all_plugins": False,
            "builtin_plugins": [],
            "custom_rules_inline": [
                {
                    "name": "coverage-flag",
                    "matchers": {
                        "entity_types": ["function"],
                    },
                    "actions": {
                        "verify_coverage": True,
                    },
                }
            ],
        }

        stats = apply_rule_plugins(graph=graph, root_path=tmp_path, rules_config=rules_cfg)
        
        # Entity should have verify_coverage metadata
        assert graph.get_entity(entity.id).metadata.get("bsg.verify_coverage") is True

    def test_bidirectional_actions_add_reconstruction_metadata(self, tmp_path: Path):
        """Test that bidirectional add_reconstruction_metadata action works."""
        graph = InMemoryGraph()

        entity = Entity(
            type=EntityType.FUNCTION,
            name="my_func",
            file="test.py",
            start_line=1,
            end_line=1,
            start_byte=0,
            end_byte=10,
            raw_content="def foo(): pass",
        )
        
        graph.add_entity(entity)

        rules_cfg = {
            "enabled": True,
            "auto_load_all_plugins": False,
            "builtin_plugins": [],
            "custom_rules_inline": [
                {
                    "name": "reconstruction-meta",
                    "matchers": {
                        "entity_types": ["function"],
                    },
                    "actions": {
                        "add_reconstruction_metadata": {
                            "priority": "high",
                            "requires_snapshot": True,
                        },
                    },
                }
            ],
        }

        stats = apply_rule_plugins(graph=graph, root_path=tmp_path, rules_config=rules_cfg)
        
        # Entity should have reconstruction metadata with nested keys
        meta = graph.get_entity(entity.id).metadata
        assert meta.get("bsg.reconstruction.priority") == "high"
        assert meta.get("bsg.reconstruction.requires_snapshot") is True

    def test_invalid_content_hash_pattern_logged_at_load(self, tmp_path: Path):
        """Issue 3: Invalid regex in content_hash_pattern must be logged as an error."""
        rules_cfg = {
            "enabled": True,
            "auto_load_all_plugins": False,
            "builtin_plugins": [],
            "custom_rules_inline": [
                {
                    "name": "bad-regex",
                    "entity_types": ["function"],
                    "matchers": {
                        "content_hash_pattern": "[unclosed",
                    },
                    "metadata": {"bsg.bad": True},
                }
            ],
        }

        rules, stats = load_effective_rules(rules_cfg, root_path=tmp_path)
        # Should not load the invalid rule, but should record an error
        assert not any(rule.name == "bad-regex" for rule in rules)
        assert any(
            "Invalid content_hash_pattern regex" in err for err in stats["errors"]
        )

    def test_valid_content_hash_pattern_matches(self, tmp_path: Path, mock_graph):
        """Issue 3: Valid content_hash_pattern should match entity hashes."""
        # Set a known hash on one entity
        e = _find_entity_by_name(mock_graph, "add")
        assert e is not None
        mock_graph.entities[e.id] = e.model_copy(update={"content_hash": "abc123def456"})

        rules_cfg = {
            "enabled": True,
            "auto_load_all_plugins": False,
            "builtin_plugins": [],
            "custom_rules_inline": [
                {
                    "name": "hash-match",
                    "entity_types": ["function"],
                    "content_hash_pattern": r"abc.*456",
                    "metadata": {"bsg.hash_matched": True},
                }
            ],
        }

        stats = apply_rule_plugins(
            graph=mock_graph,
            root_path=tmp_path,
            rules_config=rules_cfg,
        )

        updated = _find_entity_by_name(mock_graph, "add")
        assert updated.metadata.get("bsg.hash_matched") is True

    def test_content_patterns_use_repo_root_not_cwd(
        self, tmp_path: Path, monkeypatch, mock_graph
    ):
        """Issue 4: content_patterns must resolve files relative to repo root."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        src_dir = repo_root / "src"
        src_dir.mkdir()
        (src_dir / "calc.py").write_text("# hello world\n", encoding="utf-8")

        # Change cwd to a different directory so Path.cwd() != repo_root
        monkeypatch.chdir(tmp_path)

        # Update mock_graph entity file to be relative to repo_root
        e = _find_entity_by_name(mock_graph, "add")
        assert e is not None
        mock_graph.entities[e.id] = e.model_copy(update={"file": "src/calc.py"})

        rules_cfg = {
            "enabled": True,
            "auto_load_all_plugins": False,
            "builtin_plugins": [],
            "custom_rules_inline": [
                {
                    "name": "content-find",
                    "entity_types": ["function"],
                    "content_patterns": ["hello world"],
                    "metadata": {"bsg.found": True},
                }
            ],
        }

        stats = apply_rule_plugins(
            graph=mock_graph,
            root_path=repo_root,
            rules_config=rules_cfg,
        )

        updated = _find_entity_by_name(mock_graph, "add")
        # Should match because content_patterns reads from repo_root/src/calc.py
        assert updated.metadata.get("bsg.found") is True

    def test_cache_schema_version_bump_invalidates_old_cache(
        self, tmp_path: Path, monkeypatch
    ):
        """Issue 6: Old v1 cache must be rejected after schema bump."""
        from batho.bsg.rules import _CACHE_FILENAME, _CACHE_SCHEMA_VERSION

        config_file = tmp_path / "batho.yaml"
        config_file.write_text(
            """
rules:
  enabled: true
  builtin_plugins: []
  custom_rules_inline:
    - name: marker
      entity_types: [function]
      metadata:
        bsg.marker: old
""".strip()
            + "\n",
            encoding="utf-8",
        )

        monkeypatch.chdir(tmp_path)
        get_config_cached.cache_clear()

        # Manually write a v1 cache file
        ctn_dir = tmp_path / ".ctn" / "local" / "cache"
        ctn_dir.mkdir(parents=True)
        cache_path = ctn_dir / _CACHE_FILENAME
        old_cache = {
            "schema_version": "bsg-rules-cache.v1",
            "config_fingerprint": "old-fingerprint",
            "source_hashes": {},
            "rules": [],
            "load_stats": {
                "enabled": True,
                "builtin_plugins_requested": 0,
                "builtin_plugins_loaded": 0,
                "rules_loaded": 0,
                "rules_disabled": 0,
                "custom_inline_count": 0,
                "custom_file_count": 0,
                "overrides_applied": 0,
                "shadowed_rules": [],
                "errors": [],
                "plugin_versions": {},
                "plugin_schema_versions": {},
                "dependency_issues": [],
                "conflict_warnings": [],
            },
        }
        cache_path.write_text(json.dumps(old_cache), encoding="utf-8")

        cfg = get_config_cached()
        rules, stats = load_effective_rules(cfg["rules"], root_path=tmp_path)

        # The old cache should be ignored because schema_version is v1
        assert stats.get("cache_hit") is not True
        # Should load the actual rule from config
        assert any(rule.name == "marker" for rule in rules)

    def test_bidirectional_flag_cache_roundtrip(self):
        """Test that bidirectional flag is preserved in rule caching."""
        from batho.bsg.rules import RuleDefinition, RuleMatch, RuleActions
        rule = RuleDefinition(
            rule_id="test-bidirectional-cache",
            name="test-bidirectional-cache",
            description="test",
            severity="warning",
            priority=100,
            enabled=True,
            plugin="test",
            bidirectional=True,
            match=RuleMatch(),
            actions=RuleActions(),
        )
        cache_dict = rule.to_cache_dict()
        assert cache_dict["bidirectional"] is True
        
        rebuilt = RuleDefinition.from_cache_dict(cache_dict)
        assert rebuilt.bidirectional is True

    def test_bidirectional_propagation_and_filtering(self, tmp_path: Path, mock_graph):
        """Test that bidirectional flag propagates from plugin and rule levels and is filtered correctly."""
        plugin_yaml = tmp_path / "test-plugin.yaml"
        plugin_yaml.write_text(
            """
schema_version: bsg-plugin.v2
plugin_id: test_bidirectional_prop
name: Test Bidirectional Prop
version: 1.0.0
enabled: true
bidirectional: true
rules:
  - rule_id: rule-inherits-true
    name: rule-inherits-true
    description: Should inherit bidirectional=true from plugin
    severity: warning
    priority: 100
    enabled: true
    matchers:
      entity_types: ["function"]
    actions:
      metadata:
        bsg.test: true
  - rule_id: rule-overrides-false
    name: rule-overrides-false
    description: Should override plugin default to false
    severity: warning
    priority: 100
    enabled: true
    bidirectional: false
    matchers:
      entity_types: ["function"]
    actions:
      metadata:
        bsg.test: true
""".strip() + "\\n",
            encoding="utf-8",
        )

        rules_cfg = {
            "enabled": True,
            "auto_load_all_plugins": False,
            "builtin_plugins": [],
            "custom_rules_path": str(plugin_yaml),
        }

        # 1. Test compilation
        rules, stats = load_effective_rules(rules_cfg, root_path=tmp_path)
        assert len(rules) == 2
        inherits_rule = next(r for r in rules if r.rule_id == "rule-inherits-true")
        overrides_rule = next(r for r in rules if r.rule_id == "rule-overrides-false")
        assert inherits_rule.bidirectional is True
        assert overrides_rule.bidirectional is False

        # 2. Test apply_rule_plugins with bidirectional_only=True
        # It should only apply inherits_rule (bidirectional=True)
        stats = apply_rule_plugins(
            graph=mock_graph,
            root_path=tmp_path,
            rules_config=rules_cfg,
            bidirectional_only=True,
        )
        # Note: both rules matched the function, but since bidirectional_only=True,
        # only the inherits-true rule was applied.
        add_entity = _find_entity_by_name(mock_graph, "add")
        assert add_entity is not None
        assert "rule-inherits-true" in add_entity.metadata.get("bsg.rules", [])
        assert "rule-overrides-false" not in add_entity.metadata.get("bsg.rules", [])

    def test_has_coverage_gap_byte_order_validation(self, mock_graph):
        """Test that has_coverage_gap handles start_byte > end_byte gracefully."""
        e = _find_entity_by_name(mock_graph, "add")
        assert e is not None
        # Corrupt the byte bounds so start > end
        corrupted = e.model_copy(update={
            "start_byte": 100,
            "end_byte": 50,
            "raw_content": "def add(): pass",
            "raw_bytes": b"def add(): pass",
        })
        mock_graph.entities[corrupted.id] = corrupted

        rules_cfg = {
            "enabled": True,
            "auto_load_all_plugins": False,
            "builtin_plugins": [],
            "custom_rules_inline": [
                {
                    "name": "coverage-gap-check",
                    "matchers": {
                        "has_coverage_gap": True,
                    },
                    "actions": {
                        "metadata": {"bsg.bad_gap": True}
                    }
                }
            ]
        }

        apply_rule_plugins(graph=mock_graph, root_path=Path("."), rules_config=rules_cfg)
        updated = mock_graph.get_entity(corrupted.id)
        assert updated.metadata.get("bsg.bad_gap") is None

    def test_impossible_none_check_for_content_hash(self, mock_graph):
        """Test that empty content_hash string behaves correctly with regex pattern matcher."""
        e = _find_entity_by_name(mock_graph, "add")
        assert e is not None
        # Set content_hash to empty string
        hashed = e.model_copy(update={"content_hash": ""})
        mock_graph.entities[hashed.id] = hashed

        rules_cfg = {
            "enabled": True,
            "auto_load_all_plugins": False,
            "builtin_plugins": [],
            "custom_rules_inline": [
                {
                    "name": "hash-check",
                    "content_hash_pattern": "^[a-f0-9]+$",
                    "actions": {
                        "metadata": {"bsg.hash_match": True}
                    }
                }
            ]
        }

        apply_rule_plugins(graph=mock_graph, root_path=Path("."), rules_config=rules_cfg)
        updated = mock_graph.get_entity(hashed.id)
        assert updated.metadata.get("bsg.hash_match") is None
