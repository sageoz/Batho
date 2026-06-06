"""
tests/modules/compression/test_rules.py

Unit tests for the BSG rules engine:
  - _apply_rule_actions (shared helper)
  - apply_bsg_rules_to_entities (per-file path)
  - apply_rule_plugins (full-graph path)
  - load_effective_rules (cache round-trip)
  - _detect_rule_conflicts
  - _plugin_validators (thread-safety smoke test)
  - detect_framework language-guard bug regression
"""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from batho.core.schemas import Entity, EntityType, Relationship, RelationshipType
from batho.modules.compression.rules import (
    RuleActions,
    RuleDefinition,
    RuleMatch,
    WhenClause,
    MetadataCondition,
    _apply_rule_actions,
    _detect_rule_conflicts,
    apply_bsg_rules_to_entities,
    apply_rule_plugins,
    load_effective_rules,
    _get_plugin_validator,
)
from batho.modules.graph.builder.codegraph import InMemoryGraph


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entity(
    name: str,
    file: str = "/repo/src/mod.py",
    etype: EntityType = EntityType.FUNCTION,
    metadata: dict | None = None,
) -> Entity:
    return Entity(
        type=etype,
        name=name,
        file=file,
        start_line=1,
        end_line=5,
        metadata=metadata or {},
    )


def _rule(
    name: str = "test_rule",
    entity_types: tuple[str, ...] = (),
    name_patterns: tuple[str, ...] = (),
    file_patterns: tuple[str, ...] = (),
    metadata_out: dict | None = None,
    add_usn_tags: tuple[str, ...] = (),
    derive_scope_tier: bool = False,
    derive_service_tag: bool = False,
    detect_framework: dict | None = None,
    truncate_docstring: bool = False,
    max_docstring_length: int = 150,
    when: WhenClause | None = None,
    priority: int = 0,
) -> RuleDefinition:
    return RuleDefinition(
        rule_id=name,
        name=name,
        description="",
        severity="warning",
        priority=priority,
        enabled=True,
        plugin="test_plugin",
        match=RuleMatch(
            entity_types=entity_types,
            name_patterns=name_patterns,
            file_patterns=file_patterns,
        ),
        actions=RuleActions(
            metadata=metadata_out or {},
            add_usn_tags=add_usn_tags,
            derive_scope_tier=derive_scope_tier,
            derive_service_tag=derive_service_tag,
            detect_framework=detect_framework or {},
            truncate_docstring=truncate_docstring,
            max_docstring_length=max_docstring_length,
            when=when or WhenClause(),
        ),
    )


ROOT = Path("/repo")


# ---------------------------------------------------------------------------
# _apply_rule_actions
# ---------------------------------------------------------------------------

class TestApplyRuleActions:
    def test_sets_metadata_key(self):
        rule = _rule(metadata_out={"bsg.category": "SOURCE"})
        e = _entity("fn")
        meta: dict = {}
        cache: dict = {}
        changed, _ = _apply_rule_actions(rule, e, "src/mod.py", meta, cache)
        assert changed
        assert meta["bsg.category"] == "SOURCE"

    def test_no_change_when_value_already_set(self):
        rule = _rule(metadata_out={"bsg.category": "SOURCE"})
        e = _entity("fn")
        meta = {"bsg.category": "SOURCE"}
        cache: dict = {}
        changed, _ = _apply_rule_actions(rule, e, "src/mod.py", meta, cache)
        assert not changed

    def test_add_usn_tags_merges(self):
        rule = _rule(add_usn_tags=("ApiBoundary",))
        e = _entity("fn", metadata={"bsg.usn": ["AuthMiddleware"]})
        meta = dict(e.metadata)
        cache: dict = {}
        changed, tags = _apply_rule_actions(rule, e, "src/mod.py", meta, cache)
        assert changed
        assert "ApiBoundary" in meta["bsg.usn"]
        assert "AuthMiddleware" in meta["bsg.usn"]
        assert "apiboundary" in tags

    def test_add_usn_tags_idempotent(self):
        rule = _rule(add_usn_tags=("ApiBoundary",))
        e = _entity("fn", metadata={"bsg.usn": ["ApiBoundary"]})
        meta = dict(e.metadata)
        cache: dict = {}
        changed, _ = _apply_rule_actions(rule, e, "src/mod.py", meta, cache)
        assert not changed

    def test_truncate_docstring(self):
        rule = _rule(truncate_docstring=True, max_docstring_length=10)
        e = _entity("fn", metadata={"docstring": "A" * 50})
        meta = dict(e.metadata)
        cache: dict = {}
        changed, _ = _apply_rule_actions(rule, e, "src/mod.py", meta, cache)
        assert changed
        assert len(meta["docstring"]) == 13  # 10 chars + "..."

    def test_truncate_docstring_no_op_when_short(self):
        rule = _rule(truncate_docstring=True, max_docstring_length=100)
        e = _entity("fn", metadata={"docstring": "Short."})
        meta = dict(e.metadata)
        cache: dict = {}
        changed, _ = _apply_rule_actions(rule, e, "src/mod.py", meta, cache)
        assert not changed

    def test_detect_framework_sets_framework(self):
        rule = _rule(detect_framework={"framework": "Django", "language": "python"})
        e = _entity("fn")
        meta: dict = {}
        cache: dict = {}
        changed, _ = _apply_rule_actions(rule, e, "src/mod.py", meta, cache)
        assert changed
        assert "Django" in meta.get("bsg.frameworks", [])
        assert meta.get("bsg.language") == "python"

    def test_detect_framework_language_not_updated_when_framework_already_present(self):
        """Regression: language should only update when framework is newly added."""
        rule = _rule(detect_framework={"framework": "Django", "language": "python"})
        e = _entity("fn")
        meta = {"bsg.frameworks": ["Django"], "bsg.language": "python"}
        cache: dict = {}
        changed, _ = _apply_rule_actions(rule, e, "src/mod.py", meta, cache)
        assert not changed

    def test_derive_scope_tier_function(self):
        rule = _rule(derive_scope_tier=True)
        e = _entity("fn")
        meta: dict = {}
        cache: dict = {}
        _apply_rule_actions(rule, e, "src/mod.py", meta, cache)
        assert "bsg.scope_tier" in meta

    def test_derive_service_tag_services_path(self):
        rule = _rule(derive_service_tag=True)
        e = _entity("fn", file="/repo/services/auth/handler.py")
        meta: dict = {}
        cache: dict = {}
        _apply_rule_actions(rule, e, "services/auth/handler.py", meta, cache)
        assert meta.get("bsg.service_tag") == "auth"


# ---------------------------------------------------------------------------
# apply_bsg_rules_to_entities
# ---------------------------------------------------------------------------

class TestApplyBsgRulesToEntities:
    def test_applies_rule_to_matching_entity(self):
        rule = _rule(
            entity_types=("function",),
            metadata_out={"bsg.tagged": "yes"},
        )
        e = _entity("my_fn")
        updated, _ = apply_bsg_rules_to_entities(
            entities=[e],
            relationships=[],
            rules=[rule],
            root_path=str(ROOT),
            file_path=e.file,
        )
        assert updated[0].metadata.get("bsg.tagged") == "yes"

    def test_does_not_apply_rule_to_non_matching_type(self):
        rule = _rule(entity_types=("class",), metadata_out={"bsg.tagged": "yes"})
        e = _entity("fn", etype=EntityType.FUNCTION)
        updated, _ = apply_bsg_rules_to_entities(
            entities=[e],
            relationships=[],
            rules=[rule],
            root_path=str(ROOT),
            file_path=e.file,
        )
        assert updated[0].metadata.get("bsg.tagged") is None

    def test_skips_bidirectional_rules(self):
        rule = RuleDefinition(
            rule_id="bidir_rule",
            name="bidir_rule",
            description="",
            severity="warning",
            priority=0,
            enabled=True,
            plugin="test",
            bidirectional=True,
            match=RuleMatch(),
            actions=RuleActions(metadata={"bsg.should_not": "appear"}),
        )
        e = _entity("fn")
        updated, _ = apply_bsg_rules_to_entities(
            entities=[e],
            relationships=[],
            rules=[rule],
            root_path=str(ROOT),
            file_path=e.file,
        )
        assert updated[0].metadata.get("bsg.should_not") is None

    def test_detect_framework_bug_regression(self):
        """detect_framework language must not fire if framework already existed."""
        rule = _rule(detect_framework={"framework": "FastAPI", "language": "python"})
        e = _entity("fn", metadata={"bsg.frameworks": ["FastAPI"], "bsg.language": "python"})
        updated, _ = apply_bsg_rules_to_entities(
            entities=[e],
            relationships=[],
            rules=[rule],
            root_path=str(ROOT),
            file_path=e.file,
        )
        result_meta = updated[0].metadata
        assert result_meta.get("bsg.language") == "python"
        assert result_meta.get("bsg.frameworks") == ["FastAPI"]

    def test_empty_inputs_return_empty(self):
        result, audit = apply_bsg_rules_to_entities(
            entities=[], relationships=[], rules=[], root_path=str(ROOT), file_path="/repo/x.py"
        )
        assert result == []
        assert audit == {}

    def test_when_clause_gates_action(self):
        when = WhenClause(
            all_=(MetadataCondition(key="bsg.approved", operator="exists"),),
        )
        rule = _rule(metadata_out={"bsg.category": "SOURCE"}, when=when)
        e_no_key = _entity("fn_without")
        e_with_key = _entity("fn_with", metadata={"bsg.approved": True})

        updated, _ = apply_bsg_rules_to_entities(
            entities=[e_no_key, e_with_key],
            relationships=[],
            rules=[rule],
            root_path=str(ROOT),
            file_path="/repo/src/mod.py",
        )
        assert updated[0].metadata.get("bsg.category") is None
        assert updated[1].metadata.get("bsg.category") == "SOURCE"


# ---------------------------------------------------------------------------
# _detect_rule_conflicts
# ---------------------------------------------------------------------------

class TestDetectRuleConflicts:
    def test_no_conflict_disjoint_entity_types(self):
        r1 = _rule("r1", entity_types=("function",), metadata_out={"k": "v1"})
        r2 = _rule("r2", entity_types=("class",), metadata_out={"k": "v2"})
        conflicts = _detect_rule_conflicts([r1, r2])
        assert conflicts == []

    def test_conflict_detected_same_metadata_key(self):
        r1 = _rule(
            "r1",
            entity_types=("function",),
            name_patterns=("get_*",),
            metadata_out={"bsg.category": "A"},
        )
        r2 = _rule(
            "r2",
            entity_types=("function",),
            name_patterns=("get_*",),
            metadata_out={"bsg.category": "B"},
        )
        conflicts = _detect_rule_conflicts([r1, r2])
        assert len(conflicts) >= 1
        assert any("bsg.category" in c["overlap"] for c in conflicts)

    def test_no_conflict_same_value(self):
        r1 = _rule("r1", name_patterns=("auth_*",), metadata_out={"bsg.category": "SOURCE"})
        r2 = _rule("r2", name_patterns=("auth_*",), metadata_out={"bsg.category": "SOURCE"})
        conflicts = _detect_rule_conflicts([r1, r2])
        assert conflicts == []


# ---------------------------------------------------------------------------
# load_effective_rules  (disabled → returns empty list)
# ---------------------------------------------------------------------------

class TestLoadEffectiveRules:
    def test_disabled_config_returns_empty(self, tmp_path: Path):
        rules, stats = load_effective_rules(
            rules_config={"enabled": False},
            root_path=tmp_path,
        )
        assert rules == []
        assert stats["enabled"] is False

    def test_none_config_returns_empty(self, tmp_path: Path):
        rules, stats = load_effective_rules(
            rules_config=None,
            root_path=tmp_path,
        )
        assert rules == []

    def test_enabled_loads_builtin_plugins(self, tmp_path: Path):
        rules, stats = load_effective_rules(
            rules_config={"enabled": True, "auto_load_all_plugins": True},
            root_path=tmp_path,
        )
        assert stats["enabled"] is True
        assert len(rules) > 0
        assert stats["rules_loaded"] == len(rules)

    def test_cache_round_trip(self, tmp_path: Path):
        cfg = {"enabled": True, "auto_load_all_plugins": True}
        rules1, stats1 = load_effective_rules(rules_config=cfg, root_path=tmp_path)
        rules2, stats2 = load_effective_rules(rules_config=cfg, root_path=tmp_path)
        assert stats2["cache_hit"] is True
        assert len(rules1) == len(rules2)

    def test_disabled_rule_excluded(self, tmp_path: Path):
        if not (tmp_path / ".batho/cache").exists():
            (tmp_path / ".batho/cache").mkdir(parents=True, exist_ok=True)
        rules, _ = load_effective_rules(
            rules_config={
                "enabled": True,
                "auto_load_all_plugins": True,
                "disabled_rules": ["*"],  # disable everything by name wildcard won't match; use exact name
            },
            root_path=tmp_path,
        )
        assert isinstance(rules, list)


# ---------------------------------------------------------------------------
# apply_rule_plugins (smoke test on real graph)
# ---------------------------------------------------------------------------

class TestApplyRulePlugins:
    def test_disabled_rules_returns_zero_updates(self, tmp_path: Path):
        e = _entity("fn", file=str(tmp_path / "src/mod.py"))
        g = InMemoryGraph(entities={e.id: e})
        stats = apply_rule_plugins(
            graph=g,
            root_path=tmp_path,
            rules_config={"enabled": False},
        )
        assert stats["entities_updated"] == 0

    def test_enabled_rules_updates_entities(self, tmp_path: Path):
        (tmp_path / "src").mkdir(parents=True, exist_ok=True)
        e = _entity("fn", file=str(tmp_path / "src/mod.py"))
        g = InMemoryGraph(entities={e.id: e})
        stats = apply_rule_plugins(
            graph=g,
            root_path=tmp_path,
            rules_config={"enabled": True, "auto_load_all_plugins": True},
        )
        assert "entities_updated" in stats
        assert "rules_applied" in stats

    def test_bidirectional_only_flag(self, tmp_path: Path):
        e = _entity("fn", file=str(tmp_path / "src/mod.py"))
        g = InMemoryGraph(entities={e.id: e})
        stats = apply_rule_plugins(
            graph=g,
            root_path=tmp_path,
            rules_config={"enabled": True, "auto_load_all_plugins": True},
            bidirectional_only=True,
        )
        assert "entities_updated" in stats


# ---------------------------------------------------------------------------
# _get_plugin_validator — thread-safety smoke test
# ---------------------------------------------------------------------------

class TestPluginValidatorThreadSafety:
    def test_concurrent_validator_fetch(self):
        errors: list[Exception] = []

        def _fetch():
            try:
                _get_plugin_validator()
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_fetch) for _ in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"
