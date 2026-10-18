"""batho_plugin/__init__.py — Batho plugin SDK public API.

Pluggable plugin service module for the Batho engine
(PLUGIN_ARCHITECTURE_SPEC §3–§4). Ships the stage contracts, plugin
protocols, PluginHost, the mandatory ``core/`` foundation pack, the
config-gated ``external/`` pack, and the Tier-3 rule engine.

The CONTRACT SURFACE (stages/context/api/host/fingerprint/packs/hooks) is
engine-agnostic: it never imports ``batho`` (no cycles, constraint §3.1) and
talks to the engine only through opaque payloads. The one documented
exception is ``batho_plugin.rule_engine`` — the Tier-3 rule backend, which is
deliberately engine-coupled. Runtime dependencies are ``pyyaml`` and
``jsonschema`` (rule-engine validation); the contract surface alone is
dependency-free.
Engine payloads (entities, tree-sitter nodes) cross the boundary as opaque
``Any`` values documented on :class:`~batho_plugin.context.PluginContext`.

Public API:
    Stage, PluginContext, PluginData, StageResult, PruneDecision,
    DataPlugin, HookPlugin, RulePlugin, PluginHost, load_host
"""

from __future__ import annotations

from batho_plugin.api import (
    DataPlugin,
    HookPlugin,
    PluginData,
    PruneDecision,
    RulePlugin,
    StageResult,
)
from batho_plugin.context import PluginContext
from batho_plugin.host import PluginHost, PluginLoadError, load_host
from batho_plugin.stages import Stage

__version__ = "0.1.0"

__all__ = [
    "DataPlugin",
    "HookPlugin",
    "PluginContext",
    "PluginData",
    "PluginHost",
    "PluginLoadError",
    "PruneDecision",
    "RulePlugin",
    "Stage",
    "StageResult",
    "__version__",
    "load_host",
]
