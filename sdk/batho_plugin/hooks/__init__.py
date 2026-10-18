"""batho_plugin/hooks/__init__.py — generic, data-driven hook plugins.

Each hook contains logic migrated out of the engine (PLUGIN_ARCHITECTURE_SPEC
§7.1), driven entirely by core-pack data via the host. Hooks are
engine-agnostic: they operate on :class:`~batho_plugin.context.PluginContext`
and opaque entity objects (``.metadata`` dicts), never on engine imports.

Parity contract: every hook's decision function is byte-identical to the
engine implementation it replaces (enforced by tests comparing against the
engine functions on fixture inputs). The engine keeps the call sites until
T11–T17 wire the dispatch.
"""

from __future__ import annotations

from batho_plugin.hooks.comment_classify import CommentClassifyHook, classify_marker
from batho_plugin.hooks.language_detect import LanguageDetectHook, detect_language
from batho_plugin.hooks.prune_stub import PruneStubHook, should_prune
from batho_plugin.hooks.property_classify import PropertyClassifyHook, infer_access_type
from batho_plugin.hooks.stamp_language import StampLanguageHook, stamp_entities

__all__ = [
    "CommentClassifyHook",
    "LanguageDetectHook",
    "PruneStubHook",
    "PropertyClassifyHook",
    "StampLanguageHook",
    "classify_marker",
    "detect_language",
    "infer_access_type",
    "should_prune",
    "stamp_entities_language",
]

# Alias kept singular for readability at call sites.
stamp_entities_language = stamp_entities
