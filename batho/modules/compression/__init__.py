"""Compression module re-exports.

The rule engine moved to ``batho_plugin.rule_engine`` (T05,
PLUGIN_ARCHITECTURE_SPEC). This package keeps re-exporting the public API for
backward compatibility; new engine code imports the SDK path directly.

The rule-engine re-exports are LAZY: a DeprecationWarning fires on attribute
access (not on package import), so the engine's own ``bsg_map`` import path
stays silent. Removal is scheduled one minor version after the SDK ships
(T31 tracks the alias/deprecation cycle).
"""

from __future__ import annotations

import warnings

from .bsg import BSGMap as BSGMap

_RULE_ENGINE_EXPORTS = frozenset({
    "ASTEdgeMatcher",
    "MetadataCondition",
    "RegexMatcher",
    "RuleActions",
    "RuleDefinition",
    "RuleMatch",
    "WhenClause",
    "apply_rule_plugins",
    "apply_semantic_overlay",
    "list_builtin_plugins",
    "load_effective_rules",
    "validate_plugin_file",
})

__all__ = [
    "BSGMap",
    *_RULE_ENGINE_EXPORTS,
]


def __getattr__(name: str):
    if name in _RULE_ENGINE_EXPORTS:
        warnings.warn(
            f"batho.modules.compression.{name} moved to "
            f"batho_plugin.rule_engine.{name} (T05); import from "
            "batho_plugin.rule_engine instead. The shim is deprecated and "
            "will be removed one minor version after the SDK ships.",
            DeprecationWarning,
            stacklevel=2,
        )
        from batho_plugin import rule_engine

        return getattr(rule_engine, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
