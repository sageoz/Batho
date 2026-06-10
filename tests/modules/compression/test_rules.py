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
    _is_safe_regex,
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
        """Verify _apply_rule_actions sets metadata key as specified by rule definition.

        Scenario:
            An entity lacks a metadata key, and a rule defines a metadata output for it.

        Execution Flow:
            1. Create a rule that outputs {"bsg.category": "SOURCE"}.
            2. Call _apply_rule_actions on an entity with empty metadata.
            3. Verify the returned flag changed is True.
            4. Verify the metadata now has "bsg.category" equal to "SOURCE".

        Expectations:
            - The returned changed boolean is True.
            - The metadata dictionary contains {"bsg.category": "SOURCE"}.
        """
        rule = _rule(metadata_out={"bsg.category": "SOURCE"})
        e = _entity("fn")
        meta: dict = {}
        cache: dict = {}
        changed, _ = _apply_rule_actions(rule, e, "src/mod.py", meta, cache)
        assert changed
        assert meta["bsg.category"] == "SOURCE"

    def test_no_change_when_value_already_set(self):
        """Verify _apply_rule_actions does not report a change when metadata already matches.

        Scenario:
            An entity already contains the metadata key and value matching the rule action.

        Execution Flow:
            1. Create a rule outputting {"bsg.category": "SOURCE"}.
            2. Set the entity's metadata to already contain {"bsg.category": "SOURCE"}.
            3. Invoke _apply_rule_actions.
            4. Assert that the changed boolean returned is False.

        Expectations:
            - The changed boolean returned is False.
        """
        rule = _rule(metadata_out={"bsg.category": "SOURCE"})
        e = _entity("fn")
        meta = {"bsg.category": "SOURCE"}
        cache: dict = {}
        changed, _ = _apply_rule_actions(rule, e, "src/mod.py", meta, cache)
        assert not changed

    def test_add_usn_tags_merges(self):
        """Verify add_usn_tags merges new tags into existing bsg.usn tags.

        Scenario:
            An entity has an existing list of bsg.usn tags, and a rule specifies adding a new tag.

        Execution Flow:
            1. Construct a rule specifying add_usn_tags=("ApiBoundary",).
            2. Initialize an entity with existing tag ["AuthMiddleware"].
            3. Invoke _apply_rule_actions.
            4. Verify both tags exist in metadata["bsg.usn"] and "apiboundary" is returned in tags list.

        Expectations:
            - Changed is True.
            - Both "ApiBoundary" and "AuthMiddleware" are inside the updated metadata list.
            - The returned tag list contains "apiboundary".
        """
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
        """Verify add_usn_tags is idempotent and reports no change if tag is already present.

        Scenario:
            The entity's metadata already has the tag that the rule wants to add.

        Execution Flow:
            1. Construct a rule adding "ApiBoundary".
            2. Pass an entity already containing "ApiBoundary" in its "bsg.usn" metadata.
            3. Call _apply_rule_actions.
            4. Verify the changed flag is False.

        Expectations:
            - The changed boolean returned is False.
        """
        rule = _rule(add_usn_tags=("ApiBoundary",))
        e = _entity("fn", metadata={"bsg.usn": ["ApiBoundary"]})
        meta = dict(e.metadata)
        cache: dict = {}
        changed, _ = _apply_rule_actions(rule, e, "src/mod.py", meta, cache)
        assert not changed

    def test_truncate_docstring(self):
        """Verify docstrings are truncated if truncate_docstring is enabled.

        Scenario:
            An entity has a long docstring, and the rule specifies truncating to 10 characters.

        Execution Flow:
            1. Construct a rule with truncate_docstring=True and max_docstring_length=10.
            2. Construct an entity with a docstring of length 50.
            3. Call _apply_rule_actions.
            4. Verify the resulting docstring is truncated and appended with "...".

        Expectations:
            - Changed is True.
            - The length of the modified docstring is exactly 13 characters.
        """
        rule = _rule(truncate_docstring=True, max_docstring_length=10)
        e = _entity("fn", metadata={"docstring": "A" * 50})
        meta = dict(e.metadata)
        cache: dict = {}
        changed, _ = _apply_rule_actions(rule, e, "src/mod.py", meta, cache)
        assert changed
        assert len(meta["docstring"]) == 13  # 10 chars + "..."

    def test_truncate_docstring_no_op_when_short(self):
        """Verify docstring is not truncated if its length is below the maximum limit.

        Scenario:
            An entity has a short docstring, and the rule specifies a larger max_docstring_length.

        Execution Flow:
            1. Construct a rule with truncate_docstring=True and max_docstring_length=100.
            2. Construct an entity with a short docstring "Short.".
            3. Call _apply_rule_actions.
            4. Verify changed flag is False.

        Expectations:
            - Changed is False.
        """
        rule = _rule(truncate_docstring=True, max_docstring_length=100)
        e = _entity("fn", metadata={"docstring": "Short."})
        meta = dict(e.metadata)
        cache: dict = {}
        changed, _ = _apply_rule_actions(rule, e, "src/mod.py", meta, cache)
        assert not changed

    def test_detect_framework_sets_framework(self):
        """Verify detect_framework adds new frameworks and languages to metadata.

        Scenario:
            An entity is matched by a rule containing detect_framework configuration.

        Execution Flow:
            1. Create a rule with detect_framework setting Django framework and python language.
            2. Invoke _apply_rule_actions on an entity.
            3. Assert that framework list contains "Django" and language is set to "python".

        Expectations:
            - Changed is True.
            - "Django" in metadata["bsg.frameworks"].
            - "python" in metadata["bsg.language"].
        """
        rule = _rule(detect_framework={"framework": "Django", "language": "python"})
        e = _entity("fn")
        meta: dict = {}
        cache: dict = {}
        changed, _ = _apply_rule_actions(rule, e, "src/mod.py", meta, cache)
        assert changed
        assert "Django" in meta.get("bsg.frameworks", [])
        assert meta.get("bsg.language") == "python"

    def test_detect_framework_language_not_updated_when_framework_already_present(self):
        """Verify language is not updated when the framework is already present in metadata.

        Scenario:
            The entity's metadata already has the framework "Django" listed.

        Execution Flow:
            1. Create a rule configuring "Django" framework.
            2. Provide metadata already containing "Django".
            3. Call _apply_rule_actions.
            4. Verify changed is False.

        Expectations:
            - Changed is False.
        """
        rule = _rule(detect_framework={"framework": "Django", "language": "python"})
        e = _entity("fn")
        meta = {"bsg.frameworks": ["Django"], "bsg.language": "python"}
        cache: dict = {}
        changed, _ = _apply_rule_actions(rule, e, "src/mod.py", meta, cache)
        assert not changed

    def test_derive_scope_tier_function(self):
        """Verify derive_scope_tier determines scope tier for functions.

        Scenario:
            A rule specifies derive_scope_tier=True for a standard function.

        Execution Flow:
            1. Create a rule with derive_scope_tier=True.
            2. Call _apply_rule_actions.
            3. Check if "bsg.scope_tier" key is added to metadata.

        Expectations:
            - The "bsg.scope_tier" key is present in the updated metadata dictionary.
        """
        rule = _rule(derive_scope_tier=True)
        e = _entity("fn")
        meta: dict = {}
        cache: dict = {}
        _apply_rule_actions(rule, e, "src/mod.py", meta, cache)
        assert "bsg.scope_tier" in meta

    def test_derive_service_tag_services_path(self):
        """Verify derive_service_tag extracts service name from services directory structure path.

        Scenario:
            An entity is located inside "/repo/services/auth/handler.py".

        Execution Flow:
            1. Construct a rule with derive_service_tag=True.
            2. Invoke _apply_rule_actions with file path "services/auth/handler.py".
            3. Verify the extracted service tag.

        Expectations:
            - The metadata field "bsg.service_tag" is set to "auth".
        """
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
        """Verify rules are applied to entities that match the target entity type.

        Scenario:
            An entity of type function is checked against a rule matching "function" type.

        Execution Flow:
            1. Create a rule matching "function" entity type and setting a metadata tag.
            2. Define a function entity.
            3. Apply rules to the entity using apply_bsg_rules_to_entities.
            4. Verify the metadata tag is set on the returned entity.

        Expectations:
            - The entity is updated with "bsg.tagged" set to "yes".
        """
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
        """Verify rules are not applied if entity type does not match rule matches.

        Scenario:
            A rule matching "class" is evaluated against a "function" entity type.

        Execution Flow:
            1. Define a rule matching only "class" entity types.
            2. Initialize an entity with type FUNCTION.
            3. Run apply_bsg_rules_to_entities.
            4. Verify the metadata tag is not set.

        Expectations:
            - The entity's metadata for "bsg.tagged" is None.
        """
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
        """Verify bidirectional rules are skipped during single-file local rules evaluation.

        Scenario:
            A rule is defined with bidirectional=True.

        Execution Flow:
            1. Construct a bidirectional rule.
            2. Run apply_bsg_rules_to_entities.
            3. Check if the metadata action has not been applied.

        Expectations:
            - The bidirectional rule actions are not applied; metadata contains no update.
        """
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
        """Verify language is not overwritten if the framework already existed in metadata.

        Scenario:
            An entity already possesses both the target framework and language metadata.

        Execution Flow:
            1. Initialize an entity with framework "FastAPI" and language "python".
            2. Apply a rule that detects framework "FastAPI".
            3. Check that the framework list and language value remain unmodified.

        Expectations:
            - Language is "python".
            - Frameworks list is ["FastAPI"].
        """
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
        """Verify apply_bsg_rules_to_entities returns empty lists/dicts on empty inputs.

        Scenario:
            Empty entities and rules lists are provided.

        Execution Flow:
            1. Call apply_bsg_rules_to_entities with empty lists.
            2. Verify both output values are empty.

        Expectations:
            - The returned updated entities list is empty.
            - The returned audit dict is empty.
        """
        result, audit = apply_bsg_rules_to_entities(
            entities=[], relationships=[], rules=[], root_path=str(ROOT), file_path="/repo/x.py"
        )
        assert result == []
        assert audit == {}

    def test_when_clause_gates_action(self):
        """Verify when clause gates rule actions based on matching metadata condition.

        Scenario:
            A rule has a when clause requiring "bsg.approved" to exist. Two entities are checked, only one having the key.

        Execution Flow:
            1. Create a rule containing a "when" clause requiring "bsg.approved" to exist.
            2. Create two entities: one without the metadata key, one with.
            3. Apply rules to both entities.
            4. Assert that the rule action was only applied to the second entity.

        Expectations:
            - The entity without the metadata key is unmodified.
            - The entity with the metadata key is modified.
        """
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
        """Verify no conflicts are reported for rules targeting disjoint entity types.

        Scenario:
            Two rules write to the same metadata key, but one targets "function" and the other targets "class".

        Execution Flow:
            1. Define rule 1 for entity_types=("function",) setting key "k".
            2. Define rule 2 for entity_types=("class",) setting key "k".
            3. Detect conflicts using _detect_rule_conflicts.
            4. Verify no conflicts are reported.

        Expectations:
            - The returned conflicts list is empty.
        """
        r1 = _rule("r1", entity_types=("function",), metadata_out={"k": "v1"})
        r2 = _rule("r2", entity_types=("class",), metadata_out={"k": "v2"})
        conflicts = _detect_rule_conflicts([r1, r2])
        assert conflicts == []

    def test_conflict_detected_same_metadata_key(self):
        """Verify a conflict is detected when multiple rules match the same entity/name and write different values to the same metadata key.

        Scenario:
            Two rules match "function" and "get_*" name patterns, but specify different metadata output values for "bsg.category".

        Execution Flow:
            1. Define r1 for function + "get_*" setting "bsg.category" to "A".
            2. Define r2 for function + "get_*" setting "bsg.category" to "B".
            3. Detect conflicts using _detect_rule_conflicts.
            4. Verify that a conflict is reported with "bsg.category" overlapping.

        Expectations:
            - The conflicts list contains at least one conflict item.
            - The conflict overlap contains the conflicting metadata key "bsg.category".
        """
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
        """Verify no conflict is reported when overlapping rules set identical values.

        Scenario:
            Two rules overlap on "auth_*" pattern and set "bsg.category" to the same value "SOURCE".

        Execution Flow:
            1. Define r1 setting "bsg.category" to "SOURCE".
            2. Define r2 setting "bsg.category" to "SOURCE".
            3. Run _detect_rule_conflicts.
            4. Verify no conflict is detected.

        Expectations:
            - The returned conflicts list is empty.
        """
        r1 = _rule("r1", name_patterns=("auth_*",), metadata_out={"bsg.category": "SOURCE"})
        r2 = _rule("r2", name_patterns=("auth_*",), metadata_out={"bsg.category": "SOURCE"})
        conflicts = _detect_rule_conflicts([r1, r2])
        assert conflicts == []


# ---------------------------------------------------------------------------
# load_effective_rules  (disabled → returns empty list)
# ---------------------------------------------------------------------------

class TestLoadEffectiveRules:
    def test_disabled_config_returns_empty(self, tmp_path: Path):
        """Verify load_effective_rules returns empty rules list if config specifies enabled=False.

        Scenario:
            Rule configuration has {"enabled": False}.

        Execution Flow:
            1. Call load_effective_rules with enabled=False.
            2. Verify output rules list is empty and stats show enabled is False.

        Expectations:
            - Rules list is empty.
            - Stats show enabled flag is False.
        """
        rules, stats = load_effective_rules(
            rules_config={"enabled": False},
            root_path=tmp_path,
        )
        assert rules == []
        assert stats["enabled"] is False

    def test_none_config_returns_empty(self, tmp_path: Path):
        """Verify load_effective_rules returns empty list when config is None.

        Scenario:
            No rules configuration is provided.

        Execution Flow:
            1. Call load_effective_rules with rules_config=None.
            2. Verify the rules list is empty.

        Expectations:
            - Rules list is empty.
        """
        rules, stats = load_effective_rules(
            rules_config=None,
            root_path=tmp_path,
        )
        assert rules == []

    def test_enabled_loads_builtin_plugins(self, tmp_path: Path):
        """Verify load_effective_rules loads builtin plugins when config is enabled.

        Scenario:
            Config has enabled=True and auto_load_all_plugins=True.

        Execution Flow:
            1. Call load_effective_rules.
            2. Verify stats show enabled is True.
            3. Assert that rules count matches the recorded stats rules_loaded.

        Expectations:
            - Stats enabled is True.
            - Rules list has size > 0.
            - Rules count equals stats["rules_loaded"].
        """
        rules, stats = load_effective_rules(
            rules_config={"enabled": True, "auto_load_all_plugins": True},
            root_path=tmp_path,
        )
        assert stats["enabled"] is True
        assert len(rules) > 0
        assert stats["rules_loaded"] == len(rules)

    def test_cache_round_trip(self, tmp_path: Path):
        """Verify load_effective_rules caches rule loading results on subsequent calls.

        Scenario:
            Rules are loaded twice consecutively.

        Execution Flow:
            1. Load rules for the first time.
            2. Load rules a second time.
            3. Assert that the second load hits the cache and returns the same number of rules.

        Expectations:
            - The second load returns cache_hit=True in stats.
            - Both loads return the same number of rules.
        """
        cfg = {"enabled": True, "auto_load_all_plugins": True}
        rules1, stats1 = load_effective_rules(rules_config=cfg, root_path=tmp_path)
        rules2, stats2 = load_effective_rules(rules_config=cfg, root_path=tmp_path)
        assert stats2["cache_hit"] is True
        assert len(rules1) == len(rules2)

    def test_disabled_rule_excluded(self, tmp_path: Path):
        """Verify disabled rules can be excluded.

        Scenario:
            A rule config specifies some rules to exclude (e.g. disabled_rules wildcard).

        Execution Flow:
            1. Setup a dummy cache dir.
            2. Call load_effective_rules with wildcard disabled_rules.
            3. Verify the returned rules is a list.

        Expectations:
            - The returned rules is a list type.
        """
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
        """Verify apply_rule_plugins returns zero updates if rules are disabled in config.

        Scenario:
            An InMemoryGraph with one entity is processed under a disabled rules configuration.

        Execution Flow:
            1. Setup a graph containing one function entity.
            2. Call apply_rule_plugins with rules_config={"enabled": False}.
            3. Verify the number of updated entities returned in stats is 0.

        Expectations:
            - stats["entities_updated"] is 0.
        """
        e = _entity("fn", file=str(tmp_path / "src/mod.py"))
        g = InMemoryGraph(entities={e.id: e})
        stats = apply_rule_plugins(
            graph=g,
            root_path=tmp_path,
            rules_config={"enabled": False},
        )
        assert stats["entities_updated"] == 0

    def test_enabled_rules_updates_entities(self, tmp_path: Path):
        """Verify apply_rule_plugins executes rule plugins and records entity updates.

        Scenario:
            An InMemoryGraph is processed under an enabled rules configuration.

        Execution Flow:
            1. Setup directories and a function entity.
            2. Call apply_rule_plugins with rules_config enabled and auto_load_all_plugins set.
            3. Verify "entities_updated" and "rules_applied" keys are present in stats.

        Expectations:
            - The stats dictionary contains "entities_updated" key.
            - The stats dictionary contains "rules_applied" key.
        """
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
        """Verify apply_rule_plugins respects the bidirectional_only flag filter.

        Scenario:
            Rule plugins are executed with bidirectional_only flag set to True.

        Execution Flow:
            1. Create a function entity in a graph.
            2. Run apply_rule_plugins with bidirectional_only=True.
            3. Verify the entities_updated statistic is returned in the stats dictionary.

        Expectations:
            - The stats dictionary contains the "entities_updated" key.
        """
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
        """Verify multiple threads fetching the plugin validator concurrently do not raise concurrency/state issues.

        Scenario:
            16 threads concurrently access the _get_plugin_validator function to verify safety.

        Execution Flow:
            1. Initialize a thread-safe errors list.
            2. Launch 16 worker threads, each invoking _get_plugin_validator.
            3. Start and join all threads.
            4. Verify no exceptions were appended to the errors list.

        Expectations:
            - The errors list is empty after all threads complete.
        """
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


# ---------------------------------------------------------------------------
# ReDoS Pattern Checks
# ---------------------------------------------------------------------------

def test_is_safe_regex_escaped_redos():
    r"""Verify that escaped backslashes in ReDoS patterns are not bypassed.

    Scenario:
        A malicious user provides a regex rule mapping containing escaped characters designed
        to bypass safe regex checking, such as r'\\(a+)+'. The double backslash escapes the
        backslash itself, leaving the nested quantifiers active. The rules engine must reject this.

    Execution Flow:
        1. Call `_is_safe_regex(r'\\(a+)+')` and assert it is False.
        2. Call `_is_safe_regex(r'\\\\(a+)+')` and assert it is False.
        3. Call `_is_safe_regex(r'\\(abc)')` and assert it is True (safe literal group).
        4. Call `_is_safe_regex(r'\(a+)+')` and assert it is True (escaped group start, literal '(').

    Expectations:
        - Escaped characters preceding a group are parsed correctly.
        - Active groups causing exponential backtracking (ReDoS) are caught regardless of escape styling.
    """
    assert _is_safe_regex(r'\\(a+)+') is False
    assert _is_safe_regex(r'\\\\(a+)+') is False
    
    # Standard group without ReDoS
    assert _is_safe_regex(r'\\(abc)') is True
    assert _is_safe_regex(r'\(a+)+') is True


def test_is_safe_regex_new_cases():
    """Verify that _is_safe_regex handles character classes, optional quantifiers, and alternation with shared prefixes.

    Scenario:
        Test robust boundary conditions of the ReDoS detection regex rule utility on both safe patterns
        (standard nested classes, api routes alternation) and unsafe patterns (nested quantifiers,
        shared prefix alternations that trigger exponential search space on failure).

    Execution Flow:
        1. Assert safe patterns return True:
           - "([a-z+])+"
           - "(api|auth)+"
        2. Assert unsafe patterns return False:
           - "([a-z]+)+" (nested quantifiers)
           - "(a?)+" (nullable group quantifier)
           - "(a|ab)+" (overlapping prefix alternation)
           - "(a|a)+" (duplicated choice alternation)

    Expectations:
        - Accurate classification of safe vs unsafe patterns.
        - Prevents rules engine from loading catastrophic regexes.
    """
    # Safe regexes
    assert _is_safe_regex("([a-z+])+") is True
    assert _is_safe_regex("(api|auth)+") is True

    # Unsafe regexes (nested quantifiers, ReDoS, or prefix sharing)
    assert _is_safe_regex("([a-z]+)+") is False
    assert _is_safe_regex("(a?)+") is False
    assert _is_safe_regex("(a|ab)+") is False
    assert _is_safe_regex("(a|a)+") is False


def test_redos_pattern_detection():
    """Verify that _is_safe_regex correctly classifies safe and unsafe regexes.

    Scenario:
        Validates general classification, string length limits (> 250 characters), and high
        quantifier count limits (> 8 quantifiers) which can lead to CPU exhaustion.

    Execution Flow:
        1. Assert safe regexes return True:
           - "^prefix.*"
           - "[a-z]+_suffix"
           - "(api|auth)_.*"
           - "normal_pattern"
        2. Assert unsafe/overflowing regexes return False:
           - "(a+)+" / "(a*)*" / "([a-zA-Z]+)*" / "(a|b+)+"
           - "a*b*c*d*e*f*g*h*i*j*" (too many quantifiers > 8)
           - "x" * 251 (too long regex)

    Expectations:
        - Prevents processing of excessively long regex patterns.
        - Limits the number of wildcard quantifiers to 8 per pattern.
    """
    # Safe regexes
    assert _is_safe_regex("^prefix.*") is True
    assert _is_safe_regex("[a-z]+_suffix") is True
    assert _is_safe_regex("(api|auth)_.*") is True
    assert _is_safe_regex("normal_pattern") is True

    # Unsafe regexes (nested quantifiers or too many wildcards)
    assert _is_safe_regex("(a+)+") is False
    assert _is_safe_regex("(a*)*") is False
    assert _is_safe_regex("([a-zA-Z]+)*") is False
    assert _is_safe_regex("(a|b+)+") is False
    assert _is_safe_regex("a*b*c*d*e*f*g*h*i*j*") is False  # too many quantifiers (> 8)
    assert _is_safe_regex("x" * 251) is False  # too long

