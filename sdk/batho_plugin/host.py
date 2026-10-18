"""batho_plugin/host.py — PluginHost: discover, validate, compile, dispatch.

The host is the single seam between the engine and plugins
(PLUGIN_ARCHITECTURE_SPEC §4.4):

- **Compile once**: data plugins are compiled at load; the engine reads their
  artifacts via O(1) ``get_set``/``get_map`` lookups (hot-path contract, C4).
- **Deterministic dispatch**: stage → priority descending → ``plugin_id``
  ascending. Identical inputs produce identical outputs regardless of load
  order (§15.7 determinism invariant, enforced by tests).
- **Validation at load**: plugin_id/version types, stage/handler consistency,
  duplicate-id rejection, and dependency-cycle detection over optional
  ``requires`` declarations.
- **Telemetry**: every hook invocation is timed into
  :class:`~batho_plugin.telemetry.PluginTelemetry` (rule_perf shape).
- **Pack discovery**: ``core/`` is mandatory (auto-loaded); ``external/`` is
  config-gated; YAML rule packs reach the host through pack ``get_plugins()``
  exports carrying ``rule_ids`` and :meth:`register_rule` (T05).

``load_host()`` is the engine's entry point and the worker-preload seam
(replacing the ``_WORKER_RULES_CACHE`` pattern — C2) once T11 wires it.
"""

from __future__ import annotations

import importlib
import logging
import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from batho_plugin.api import DataPlugin, HookPlugin, PluginData, StageResult
from batho_plugin.context import PluginContext
from batho_plugin.stages import Stage
from batho_plugin.telemetry import PluginTelemetry

# stdlib logging — host.py is SDK surface: no batho.* imports (the SDK has
# no engine dependency; rule_engine.py is the documented Tier-3 exception).
_LOGGER = logging.getLogger(__name__)


class PluginLoadError(RuntimeError):
    """Raised when the plugin set cannot be loaded or validated."""


@dataclass(frozen=True, slots=True)
class DataRegistration:
    """A compiled data plugin registration."""

    plugin_id: str
    version: str
    data: PluginData
    plugin_class: str = "standard"


@dataclass(frozen=True, slots=True)
class HookRegistration:
    """A hook plugin registration with its dispatch priority."""

    plugin: HookPlugin
    priority: int
    plugin_class: str = "standard"


@dataclass(frozen=True, slots=True)
class RuleRegistration:
    """A rule-plugin registration (YAML pack surfaced via ``rule_ids``)."""

    plugin_id: str
    version: str
    rule_ids: tuple[str, ...]
    plugin_class: str = "standard"


class PluginHost:
    """Registry, validator, and dispatcher for the three plugin kinds."""

    def __init__(self) -> None:
        self._data: dict[str, DataRegistration] = {}
        self._hooks: dict[str, HookRegistration] = {}
        self._rules: dict[str, RuleRegistration] = {}
        self.telemetry = PluginTelemetry()
        # C4 compile-once caches: merged get_set/get_map results are stable
        # for a fixed registration set, so they are computed once per
        # (key, language) and invalidated in register_data. The engine's hot
        # paths (per-file detection, per-reference prune lookups) must never
        # pay the cross-plugin merge per call.
        self._set_cache: dict[tuple[str, str | None], frozenset[str]] = {}
        self._map_cache: dict[tuple[str, str | None], dict[str, Any]] = {}
        # Canonical dispatch order (priority desc, plugin_id asc),
        # precomputed on hook registration so dispatch() sorts zero times.
        self._ordered_hooks: tuple[tuple[str, HookRegistration], ...] = ()

    # -- registration -----------------------------------------------------

    def register_data(self, plugin: DataPlugin) -> None:
        """Compile and register a data plugin (compile-once contract)."""
        self._check_identity(plugin)
        if plugin.plugin_id in self._data:
            raise PluginLoadError(f"duplicate plugin_id: {plugin.plugin_id!r}")
        data = plugin.compile()
        if not isinstance(data, PluginData):
            raise PluginLoadError(
                f"{plugin.plugin_id!r}.compile() must return PluginData, "
                f"got {type(data).__name__}"
            )
        self._data[plugin.plugin_id] = DataRegistration(
            plugin_id=plugin.plugin_id,
            version=plugin.version,
            data=data,
            plugin_class=str(
                getattr(plugin, "pack_class", None)
                or getattr(plugin, "plugin_class", "standard")
            ),
        )
        # New data changes every merged get_set/get_map result.
        self._set_cache.clear()
        self._map_cache.clear()

    def register_hook(self, plugin: HookPlugin, priority: int = 0) -> None:
        """Register a hook plugin; validates stage/handler consistency."""
        self._check_identity(plugin)
        if plugin.plugin_id in self._hooks:
            raise PluginLoadError(f"duplicate plugin_id: {plugin.plugin_id!r}")
        stages = getattr(plugin, "stages", None)
        if not isinstance(stages, tuple) or not all(isinstance(s, Stage) for s in stages):
            raise PluginLoadError(
                f"{plugin.plugin_id!r}.stages must be a tuple of Stage"
            )
        for stage in stages:
            handler = getattr(plugin, stage.value, None)
            if handler is None or not callable(handler):
                raise PluginLoadError(
                    f"{plugin.plugin_id!r} declares {stage.name} but does not "
                    f"implement {stage.value}()"
                )
        self._hooks[plugin.plugin_id] = HookRegistration(
            plugin=plugin,
            priority=int(priority),
            plugin_class=str(getattr(plugin, "plugin_class", "standard")),
        )
        # Recompute the canonical dispatch order (priority desc, id asc) at
        # the only point the registry changes — dispatch() never sorts.
        self._ordered_hooks = tuple(
            sorted(
                self._hooks.items(),
                key=lambda item: (-item[1].priority, item[0]),
            )
        )
        # Hooks that need pack data at dispatch time receive the host here
        # (e.g. LanguageDetectHook.bind) — registration is the single
        # injection point, keeping hook constructors dependency-free.
        bind = getattr(plugin, "bind", None)
        if callable(bind):
            bind(self)

    def register_rule(
        self,
        plugin_id: str,
        version: str,
        rule_ids: tuple[str, ...],
        plugin_class: str = "standard",
    ) -> None:
        """Register a YAML rule pack by plugin_id and its rule ids."""
        if not plugin_id or not isinstance(plugin_id, str):
            raise PluginLoadError("rule plugin_id must be a non-empty string")
        if plugin_id in self._rules:
            raise PluginLoadError(f"duplicate plugin_id: {plugin_id!r}")
        self._rules[plugin_id] = RuleRegistration(
            plugin_id=plugin_id,
            version=version,
            rule_ids=tuple(rule_ids),
            plugin_class=str(plugin_class or "standard"),
        )

    def _check_identity(self, plugin: Any) -> None:
        pid = getattr(plugin, "plugin_id", None)
        ver = getattr(plugin, "version", None)
        if not pid or not isinstance(pid, str):
            raise PluginLoadError(f"plugin {plugin!r} needs a string plugin_id")
        if not ver or not isinstance(ver, str):
            raise PluginLoadError(f"plugin {pid!r} needs a string version")

    # -- load (discovery + validation + cycle detection) -------------------

    @classmethod
    def load(
        cls,
        config: Mapping[str, Any] | None = None,
        no_plugins: bool = False,
    ) -> "PluginHost":
        """Discover, validate, and compile the full plugin set.

        Args:
            config: Effective ``plugins.*`` configuration mapping — either
                the full batho config (``config["plugins"]`` is read) or the
                plugins section itself. Custom-rules-dir discovery is NOT
                the host's job: the rule engine resolves the repo root via
                the engine's active-root config (``set_active_root``).
            no_plugins: Run with compiled-in fallbacks only (``--no-plugins``).

        Raises:
            PluginLoadError: core pack missing/invalid while
                ``plugins.core.required`` is true and ``no_plugins`` is false.
        """
        host = cls()
        if no_plugins:
            return host
        cfg = dict(config or {})
        plugins_cfg = cfg.get("plugins", cfg) if isinstance(cfg.get("plugins", cfg), dict) else {}

        core_required = bool(
            (plugins_cfg.get("core") or {}).get("required", True)
        )
        external_enabled = bool(
            (plugins_cfg.get("external") or {}).get("enabled", False)
        )

        core_errors = host._load_pack("batho_plugin.core")
        if core_errors:
            if core_required:
                raise PluginLoadError(
                    "core plugin pack failed to load: " + "; ".join(core_errors)
                )
            # Non-fatal degradation must still be observable — a silently
            # reduced plugin set shifts the fingerprint and with it patch
            # drift-escalation behavior.
            _LOGGER.warning(
                "plugin_pack_load_degraded module=%s errors=%s",
                "batho_plugin.core",
                "; ".join(core_errors),
            )

        if external_enabled:
            select = [
                str(s).strip()
                for s in ((plugins_cfg.get("external") or {}).get("select") or [])
                if str(s).strip()
            ]
            external_errors = host._load_pack(
                "batho_plugin.external", select=select or None
            )
            if external_errors:
                _LOGGER.warning(
                    "plugin_pack_load_degraded module=%s errors=%s",
                    "batho_plugin.external",
                    "; ".join(external_errors),
                )

        host._validate_dependency_cycles()
        return host

    def _load_pack(self, module_name: str, select: list[str] | None = None) -> list[str]:
        """Import a pack module and register its ``get_plugins()`` exports.

        ``select`` is an optional allowlist of plugin_ids/stems (external
        pack, spec §8.2). Returns a list of error strings (empty on
        success). A missing module is an error for the caller to interpret
        (core = required, external = optional).
        """
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            return [f"{module_name}: import failed ({exc})"]

        errors: list[str] = []
        get_plugins = getattr(module, "get_plugins", None)
        if get_plugins is None:
            return [f"{module_name}: no get_plugins() export"]
        try:
            plugins = list(get_plugins())
        except Exception as exc:  # noqa: BLE001 — load isolation
            return [f"{module_name}: get_plugins() raised ({exc})"]

        if select:
            allowed = set(select)
            plugins = [
                p
                for p in plugins
                if getattr(p, "plugin_id", None) in allowed
                or getattr(p, "path", "").rsplit(".", 1)[0] in allowed
            ]

        for plugin in plugins:
            try:
                rule_ids = getattr(plugin, "rule_ids", None)
                if isinstance(getattr(plugin, "stages", None), tuple):
                    self.register_hook(plugin)
                elif rule_ids is not None:
                    self.register_rule(
                        plugin.plugin_id,
                        plugin.version,
                        tuple(rule_ids),
                        plugin_class=str(
                            getattr(plugin, "plugin_class", "standard")
                        ),
                    )
                elif hasattr(plugin, "compile"):
                    self.register_data(plugin)
                else:
                    errors.append(
                        f"{module_name}: {plugin!r} is neither hook, rule, nor data plugin"
                    )
            except PluginLoadError as exc:
                errors.append(f"{module_name}: {exc}")
        return errors

    def _validate_dependency_cycles(self) -> None:
        """DFS cycle detection over optional ``requires`` declarations."""
        graph: dict[str, tuple[str, ...]] = {}
        for pid in self.plugin_ids:
            reg = (
                self._data.get(pid)
                or self._hooks.get(pid)  # type: ignore[assignment]
                or self._rules.get(pid)  # type: ignore[assignment]
            )
            plugin = getattr(reg, "plugin", None) or (
                reg if isinstance(reg, RuleRegistration) else None
            )
            requires = getattr(plugin, "requires", ()) or ()
            graph[pid] = tuple(str(r) for r in requires)

        state: dict[str, int] = {}  # 0=unvisited, 1=in-stack, 2=done

        def visit(node: str, stack: list[str]) -> None:
            if state.get(node) == 1:
                cycle = " -> ".join([*stack, node])
                raise PluginLoadError(f"plugin dependency cycle: {cycle}")
            if state.get(node) == 2:
                return
            state[node] = 1
            for dep in graph.get(node, ()):
                if dep in graph:
                    visit(dep, [*stack, node])
            state[node] = 2

        for pid in sorted(graph):
            if state.get(pid, 0) == 0:
                visit(pid, [pid])

    # -- data lookups (O(1), engine hot paths) -----------------------------

    def get_set(self, key: str, language: str | None = None) -> frozenset[str]:
        """Union of *key* across data plugins, with per-language override.

        Within one plugin, ``per_language[language]`` REPLACES the plugin's
        top-level entry for that key (override with fallback) — a Python file
        must be pruned by Python's builtins only; unioning other languages'
        sets would cause false prunes. Across plugins, results are unioned.

        The merged result is memoized per (key, language) — C4: hot paths
        call this per file or per reference, and the merged value is stable
        for a fixed registration set (cache invalidated in
        :meth:`register_data`). The returned frozenset is shared; treat it
        as read-only (frozensets are immutable by construction).
        """
        cache_key = (key, language)
        cached = self._set_cache.get(cache_key)
        if cached is not None:
            return cached
        out: set[str] = set()
        for reg in self._data.values():
            data = reg.data
            scoped = data.per_language.get(language) if language else None
            if scoped is not None and key in scoped.sets:
                out |= scoped.sets[key]
            elif key in data.sets:
                out |= data.sets[key]
        merged = frozenset(out)
        self._set_cache[cache_key] = merged
        return merged

    def get_map(self, key: str, language: str | None = None) -> Mapping[str, Any]:
        """Merged mapping for *key*; same override-with-fallback rule as
        :meth:`get_set` (registration order wins on conflicting keys).

        The merge is memoized per (key, language) (C4 — see
        :meth:`get_set`) and the return value is a zero-copy READ-ONLY view
        over the cached merge; mutating it raises ``TypeError``. Copy via
        ``dict(result)`` when a mutable mapping is genuinely needed.
        """
        cache_key = (key, language)
        merged = self._map_cache.get(cache_key)
        if merged is None:
            out: dict[str, Any] = {}
            for reg in self._data.values():
                data = reg.data
                scoped = data.per_language.get(language) if language else None
                if scoped is not None and key in scoped.maps:
                    out.update(scoped.maps[key])
                elif key in data.maps:
                    out.update(data.maps[key])
            merged = out
            self._map_cache[cache_key] = merged
        return MappingProxyType(merged)

    # -- hook dispatch (deterministic + timed) ------------------------------

    def has_stage_hooks(self, stage: Stage) -> bool:
        """True when at least one registered hook handles *stage*.

        Callers building a :class:`PluginContext` for a stage should check
        this first — materializing the context buffers is O(graph) for the
        post-resolve/post-build stages and pure waste when nothing is
        registered to consume it.
        """
        return any(stage in reg.plugin.stages for reg in self._hooks.values())

    def dispatch(self, stage: Stage, ctx: PluginContext) -> list[StageResult]:
        """Invoke every hook registered for *stage*, in canonical order.

        Handlers are resolved with ``getattr(plugin, stage.value)`` and run
        in the registration-time precomputed order (priority desc,
        plugin_id asc). Each invocation is timed into telemetry; exceptions
        from one hook never abort the stage (per-unit isolation, §15.6) —
        the failing hook is skipped and the error is recorded in its result
        and in telemetry. A hook that returns ``None`` is treated the same
        way: coerced to a ``changed=False`` result carrying an error detail.
        """
        results: list[StageResult] = []
        for plugin_id, reg in self._ordered_hooks:
            if stage not in reg.plugin.stages:
                continue
            handler = getattr(reg.plugin, stage.value, None)
            if handler is None:
                continue
            start = time.perf_counter_ns()
            try:
                result = handler(ctx)
                ns = time.perf_counter_ns() - start
                if result is None:
                    self.telemetry.record(
                        plugin_id, stage.value, ns, changed=False, error=True
                    )
                    results.append(
                        StageResult(
                            changed=False,
                            detail={
                                "error": f"{plugin_id}.{stage.value}() returned None"
                            },
                        )
                    )
                    continue
                changed = bool(getattr(result, "changed", False))
                self.telemetry.record(plugin_id, stage.value, ns, changed)
                results.append(result)
            except Exception as exc:  # noqa: BLE001 — isolation by design
                ns = time.perf_counter_ns() - start
                self.telemetry.record(
                    plugin_id, stage.value, ns, changed=False, error=True
                )
                results.append(
                    StageResult(changed=False, detail={"error": str(exc)})
                )
        return results

    # -- introspection -------------------------------------------------------

    def data_registrations(self) -> tuple[DataRegistration, ...]:
        """All data registrations, sorted by plugin_id for stability."""
        return tuple(self._data[k] for k in sorted(self._data))

    def hook_registrations(self) -> tuple[HookRegistration, ...]:
        """All hook registrations, sorted by plugin_id for stability."""
        return tuple(self._hooks[k] for k in sorted(self._hooks))

    def rule_registrations(self) -> tuple[RuleRegistration, ...]:
        """All rule registrations, sorted by plugin_id for stability."""
        return tuple(self._rules[k] for k in sorted(self._rules))

    @property
    def plugin_ids(self) -> tuple[str, ...]:
        """All registered plugin ids (data + hooks + rules), sorted."""
        return tuple(
            sorted({*self._data.keys(), *self._hooks.keys(), *self._rules.keys()})
        )


def load_host(
    config: Mapping[str, Any] | None = None,
    no_plugins: bool = False,
) -> PluginHost:
    """Build a fully-loaded PluginHost (engine entry point / worker preload)."""
    return PluginHost.load(config=config, no_plugins=no_plugins)
