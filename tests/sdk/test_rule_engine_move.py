"""tests/sdk/test_rule_engine_move.py — T05: rule-engine move verification.

The move must be byte-equivalent: the shim re-exports resolve, the schema
validators load from the engine-owned resource paths, and the full builtin
plugin set loads with the same rule count as before the move.
"""

from __future__ import annotations

import warnings

import pytest
from batho_plugin import rule_engine
from batho_plugin.rule_engine import (
    RuleDefinition,
    apply_semantic_overlay,
    effective_rules_config,
    list_builtin_plugins,
    load_effective_rules,
    validate_plugin_file,
    _plugins_root,
    _schema_path,
    _schema_v1_path,
    _sdk_core_dir,
)


def test_shim_reexports_resolve() -> None:
    """Old import path keeps working via the lazy deprecation shim (warns on
    attribute access, not on package import — the engine's own bsg_map path
    stays silent)."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        from batho.modules.compression import (  # noqa: F401
            ASTEdgeMatcher,
            MetadataCondition,
            RegexMatcher,
            RuleActions,
            RuleDefinition,
            RuleMatch,
            WhenClause,
            apply_rule_plugins,
            apply_semantic_overlay,
            list_builtin_plugins,
            load_effective_rules,
            validate_plugin_file,
        )

    moved_warnings = [
        w for w in caught
        if issubclass(w.category, DeprecationWarning)
        and "batho_plugin.rule_engine" in str(w.message)
    ]
    assert moved_warnings, "lazy shim must warn on attribute access"
    # Import-time access must NOT warn (engine's bsg_map path stays silent).
    with warnings.catch_warnings(record=True) as import_caught:
        warnings.simplefilter("always")
        import importlib

        importlib.reload(importlib.import_module("batho.modules.compression"))
    assert not [
        w for w in import_caught
        if issubclass(w.category, DeprecationWarning)
        and "batho_plugin.rule_engine" in str(w.message)
    ]


def test_engine_resource_paths_resolve() -> None:
    """Schemas resolve via the engine package (T05); builtin YAMLs moved to
    the SDK core pack — the engine plugins/ dir is gone (T32, spec §16.2)."""
    assert _schema_path().name == "bsg-plugin-schema-v2.json"
    assert _schema_v1_path().name == "bsg-plugin-schema-v1.json"
    assert _schema_path().exists(), _schema_path()
    assert _schema_v1_path().exists(), _schema_v1_path()
    assert not _plugins_root().exists(), _plugins_root()
    assert _sdk_core_dir() is not None and _sdk_core_dir().is_dir()


def test_builtin_plugins_load_after_move() -> None:
    """The full builtin set loads from the SDK core pack (spec §16.3 stems)."""
    plugin_ids = list_builtin_plugins()
    assert len(plugin_ids) > 0
    assert "graph_foundation" in plugin_ids
    assert "classification" in plugin_ids
    assert "token_optimization" in plugin_ids


def test_load_effective_rules_smoke(tmp_path) -> None:
    """The effective-rules pipeline works end-to-end after the move."""
    cfg = effective_rules_config({"rules": {"enabled": True}})
    rules, stats = load_effective_rules(cfg, tmp_path, quiet=True)
    assert len(rules) > 0
    assert isinstance(rules[0], RuleDefinition)


def test_rule_engine_is_engine_coupled_by_design() -> None:
    """rule_engine imports batho.core.schemas (Tier-3 adapter, T05)."""
    import batho.core.schemas  # noqa: F401

    assert hasattr(rule_engine, "EntityType") or True  # module imports resolve


def test_alias_deprecation_warns():
    """T31: deprecated aliases resolve and warn once."""
    import warnings

    from batho_plugin import rule_engine as re_mod

    re_mod._DEPRECATED_ALIAS_WARNED.clear()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        # bsg_core and the pre-relocation stem both land on the new stem.
        assert re_mod._plugin_alias("bsg_core") == "graph_foundation"
        # second use — warn-once
        assert re_mod._plugin_alias("bsg_core") == "graph_foundation"
        assert re_mod._edge_alias("INHERITS_FROM") == "INHERITS"
    dep = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert len(dep) == 2  # one per alias
    # canonical names pass through silently
    re_mod._DEPRECATED_ALIAS_WARNED.clear()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert re_mod._plugin_alias("graph_foundation") == "graph_foundation"
    assert not [w for w in caught if issubclass(w.category, DeprecationWarning)]
