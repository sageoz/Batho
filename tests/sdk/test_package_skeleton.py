"""tests/sdk/test_package_skeleton.py — T01 acceptance tests.

Covers the T01 definition of done: package importable from the engine venv,
public API exported with __version__, no import cycles between the engine
and the SDK, and the Stage enum completeness contract (spec §4.1).
"""

from __future__ import annotations

import importlib
import sys

import batho_plugin
from batho_plugin import (
    DataPlugin,
    HookPlugin,
    PluginContext,
    PluginData,
    PluginHost,
    PruneDecision,
    RulePlugin,
    Stage,
    StageResult,
    load_host,
)


def test_version_present() -> None:
    assert isinstance(batho_plugin.__version__, str)
    assert batho_plugin.__version__ == "0.1.0"


def test_public_api_exports() -> None:
    expected = {
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
    }
    assert expected == set(batho_plugin.__all__)
    for name in expected - {"__version__"}:
        assert getattr(batho_plugin, name) is not None


def test_no_engine_import_in_contract_modules() -> None:
    """The CONTRACT surface must be engine-agnostic (§3.1): no batho.* leaks
    from stages/context/api/host/fingerprint/telemetry/hooks. The rule engine
    (rule_engine.py) is deliberately engine-coupled — it is the Tier-3
    adapter operating on engine Entity/Relationship objects (T05)."""
    contract_prefixes = (
        "batho_plugin.stages",
        "batho_plugin.context",
        "batho_plugin.api",
        "batho_plugin.host",
        "batho_plugin.fingerprint",
        "batho_plugin.telemetry",
        "batho_plugin.hooks",
    )
    for mod_name in list(sys.modules):
        if not mod_name.startswith(contract_prefixes):
            continue
        mod = sys.modules[mod_name]
        for value in getattr(mod, "__dict__", {}).values():
            mod_of_value = getattr(value, "__module__", "")
            assert not mod_of_value.startswith("batho."), (
                f"{mod_name} leaks engine object {value!r}"
            )


def test_engine_and_sdk_coexist_without_cycles() -> None:
    """Both packages import in the same interpreter, in either order."""
    importlib.import_module("batho_plugin")
    importlib.import_module("batho.core.schemas")
    importlib.import_module("batho_plugin.host")
    importlib.import_module("batho_plugin.stages")


def test_stage_enum_completeness() -> None:
    """The 9 stages of spec §4.1, in canonical pipeline order."""
    expected = [
        "ON_FILE_DETECTED",
        "ON_PRE_PARSE",
        "ON_POST_PARSE",
        "ON_COMMENT_CLASSIFY",
        "ON_PROPERTY_CLASSIFY",
        "ON_PRE_STUB_CREATE",
        "ON_POST_ENTITIES",
        "ON_POST_RESOLVE",
        "ON_POST_BUILD",
    ]
    assert [s.name for s in Stage] == expected
    assert all(s.value.startswith("on_") for s in Stage)
    assert all(s.hook_method == s.value for s in Stage)


def test_ast_alive_stages() -> None:
    """AST-alive stages per spec §4.1 / constraint C1."""
    alive = {s for s in Stage if s.ast_alive}
    assert alive == {
        Stage.ON_POST_PARSE,
        Stage.ON_COMMENT_CLASSIFY,
        Stage.ON_PROPERTY_CLASSIFY,
        Stage.ON_PRE_STUB_CREATE,
        Stage.ON_POST_ENTITIES,
    }
    assert not Stage.ON_POST_RESOLVE.ast_alive
    assert not Stage.ON_POST_BUILD.ast_alive


def test_host_dispatch_is_deterministic() -> None:
    """Priority desc, then plugin_id asc — regardless of registration order."""

    class Hook:
        def __init__(self, pid: str, stages: tuple) -> None:
            self.plugin_id = pid
            self.version = "0.0.0"
            self.stages = stages
            self.calls: list[str] = []

        def on_post_entities(self, ctx: PluginContext) -> StageResult:
            self.calls.append(ctx.file_path)
            return StageResult(changed=True)

    ctx = PluginContext(file_path="a.py", root_path=None)  # type: ignore[arg-type]
    late_low = Hook("zeta", (Stage.ON_POST_ENTITIES,))
    early_high = Hook("alpha", (Stage.ON_POST_ENTITIES,))
    other_stage = Hook("gamma", (Stage.ON_PRE_PARSE,))

    def _on_pre_parse(self, ctx: PluginContext) -> StageResult:  # noqa: ANN001
        return StageResult()

    other_stage.on_pre_parse = _on_pre_parse.__get__(other_stage)  # type: ignore[attr-defined]

    host = PluginHost()
    host.register_hook(late_low, priority=1)   # registered first, lower priority
    host.register_hook(early_high, priority=9)
    host.register_hook(other_stage, priority=5)  # wrong stage → skipped

    results = host.dispatch(Stage.ON_POST_ENTITIES, ctx)

    assert [r.changed for r in results] == [True, True]
    assert early_high.calls == ["a.py"]
    assert late_low.calls == ["a.py"]
    assert other_stage.calls == []
    # Dispatch order: alpha (priority 9) before zeta (priority 1).
    assert host.plugin_ids == ("alpha", "gamma", "zeta")


def test_hook_exception_isolated() -> None:
    """One failing hook never aborts the stage (per-unit isolation)."""

    class Bad:
        plugin_id = "bad"
        version = "0.0.0"
        stages = (Stage.ON_POST_ENTITIES,)

        def on_post_entities(self, ctx: PluginContext) -> StageResult:
            raise RuntimeError("boom")

    class Good:
        plugin_id = "good"
        version = "0.0.0"
        stages = (Stage.ON_POST_ENTITIES,)

        def on_post_entities(self, ctx: PluginContext) -> StageResult:
            return StageResult(changed=True)

    host = PluginHost()
    host.register_hook(Bad(), priority=9)
    host.register_hook(Good(), priority=1)
    ctx = PluginContext(file_path="x.py", root_path=None)  # type: ignore[arg-type]
    results = host.dispatch(Stage.ON_POST_ENTITIES, ctx)
    assert len(results) == 2
    assert results[0].detail.get("error") == "boom"
    assert results[1].changed is True


def test_data_plugin_lookup_override_with_fallback() -> None:
    """per_language data REPLACES the top-level entry for that key (override
    with fallback) — a Python file must be pruned by Python's builtins only;
    unioning other languages' sets would cause false prunes."""

    class Pack:
        plugin_id = "pack"
        version = "0.0.0"

        def compile(self) -> PluginData:
            return PluginData(
                sets={"noise_symbols": frozenset({"self", "cls"})},
                maps={"strategy_confidence": {"exact_match": 0.95}},
                per_language={
                    "python": PluginData(
                        sets={"noise_symbols": frozenset({"ctx"})},
                        maps={"strategy_confidence": {"exact_match": 0.9}},
                    ),
                },
            )

    host = PluginHost()
    host.register_data(Pack())

    # No language → top-level entries.
    assert host.get_set("noise_symbols") == frozenset({"self", "cls"})
    assert host.get_map("strategy_confidence") == {"exact_match": 0.95}
    # Scoped language → per_language REPLACES the top-level entry.
    assert host.get_set("noise_symbols", language="python") == frozenset({"ctx"})
    assert host.get_map("strategy_confidence", language="python") == {
        "exact_match": 0.9
    }
    # Language without scoped data → falls back to top-level.
    assert host.get_set("noise_symbols", language="go") == frozenset(
        {"self", "cls"}
    )
    # Missing key → empty.
    assert host.get_set("missing") == frozenset()
    assert host.get_map("missing", language="python") == {}


def test_load_host_returns_loaded_host() -> None:
    """load_host() builds the full foundation pack; no_plugins=True returns
    the empty fallback host."""
    host = load_host()
    assert isinstance(host, PluginHost)
    assert len(host.plugin_ids) == 15  # 5 hooks + 10 core-pack data plugins
    empty = load_host(no_plugins=True)
    assert empty.plugin_ids == ()
