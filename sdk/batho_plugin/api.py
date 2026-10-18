"""batho_plugin/api.py — Plugin protocols and result/data types.

Three plugin kinds (PLUGIN_ARCHITECTURE_SPEC §4.3):

- DataPlugin  exposes precompiled structures (frozensets/dicts) loaded once
  per process; the engine consults them via O(1) lookups. This is the
  mechanism that keeps hot paths (pruning) at set-lookup speed (C4).
- HookPlugin  registers callbacks at pipeline stages; may mutate
  ``ctx.entities`` metadata in place. Concrete hooks implement
  ``on_<stage.value>(ctx)`` methods; the host resolves them via ``getattr``.
- RulePlugin  the existing YAML ``bsg-plugin.v2`` matcher→action system;
  packs surface rule packs through ``get_plugins()`` exports carrying
  ``rule_ids`` (registered via ``PluginHost.register_rule``, T05).

Protocols are structural (``runtime_checkable``) so packs never import the
SDK's concrete classes to be registered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from batho_plugin.context import PluginContext
from batho_plugin.stages import Stage


@dataclass(frozen=True, slots=True)
class PluginData:
    """Precompiled data artifacts exposed by a DataPlugin.

    Attributes:
        sets: Named frozensets (e.g. ``"builtins"``, ``"noise_symbols"``).
        maps: Named plain dicts (e.g. ``"strategy_confidence"``).
        per_language: Language-scoped overrides keyed by language id; lookups
            fall back from ``per_language[lang]`` to the top-level entries.
    """

    sets: dict[str, frozenset[str]] = field(default_factory=dict)
    maps: dict[str, dict[str, Any]] = field(default_factory=dict)
    per_language: dict[str, "PluginData"] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PruneDecision:
    """Verdict returned by the ON_PRE_STUB_CREATE hook.

    Attributes:
        prune: True when the unresolved reference must NOT become an entity.
        reason: Machine-readable prune reason (e.g. ``"builtin"``,
            ``"noise_symbol"``); persisted as ``prune_reason`` by the engine.
    """

    prune: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class StageResult:
    """Generic stage outcome; the mutated context is the primary channel.

    Attributes:
        changed: True when the hook mutated the context (entity metadata).
        detail: Stage-specific extras (e.g. counters for telemetry).
    """

    changed: bool = False
    detail: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class DataPlugin(Protocol):
    """Exposes precompiled data structures via a single ``compile`` call."""

    plugin_id: str
    version: str

    def compile(self) -> PluginData:
        """Build the plugin's data artifacts once at host load time."""
        ...


@runtime_checkable
class HookPlugin(Protocol):
    """Registers ``on_<stage.value>(ctx) -> StageResult`` callbacks.

    ``stages`` declares the stages the plugin participates in; the host
    resolves each handler with ``getattr(plugin, stage.value)`` and skips
    plugins that do not implement a stage's method.
    """

    plugin_id: str
    version: str
    stages: tuple[Stage, ...]


@runtime_checkable
class RulePlugin(Protocol):
    """Marker protocol for YAML rule plugins surfaced through ``rule_ids``.

    The rule engine (``rule_engine.py``) owns the concrete RuleDefinition
    type; the SDK keeps this protocol engine-agnostic so the host can treat
    rule packs uniformly.
    """

    plugin_id: str
    version: str
