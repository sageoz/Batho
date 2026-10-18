"""tests/sdk/test_host_load.py — T03: PluginHost load/dispatch/telemetry.

Discovery (core mandatory, external config-gated), validation, duplicate-id
rejection, dependency-cycle detection, deterministic dispatch, and telemetry
recording (rule_perf shape).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from batho_plugin import (
    PluginContext,
    PluginData,
    PluginHost,
    PluginLoadError,
    Stage,
    StageResult,
    load_host,
)


class _Pack:
    """Data plugin with per-language data for merge tests."""

    plugin_id = "pack"
    version = "1.0"

    def compile(self) -> PluginData:
        return PluginData(
            sets={"builtins": frozenset({"len"})},
            maps={"strategy_confidence": {"exact_match": 0.95}},
            per_language={
                "python": PluginData(sets={"builtins": frozenset({"print"})}),
            },
        )


class _Hook:
    plugin_id = "hook"
    version = "1.0"
    stages = (Stage.ON_POST_ENTITIES,)

    def __init__(self) -> None:
        self.calls = 0

    def on_post_entities(self, ctx: PluginContext) -> StageResult:
        self.calls += 1
        return StageResult(changed=True)


def test_load_core_pack_mandatory() -> None:
    """core/ loads unconditionally; the pack registers its plugins (T07/T08
    populated it: 5 hooks + 7 data packs). A missing/invalid core module
    would raise PluginLoadError (core.required default true)."""
    host = load_host()
    assert isinstance(host, PluginHost)
    assert len(host.plugin_ids) >= 12
    # A FRESH host loads the pack cleanly (no duplicate-id errors).
    errors = PluginHost()._load_pack("batho_plugin.core")
    assert errors == []


def test_load_rejects_invalid_core_pack() -> None:
    """A core pack that fails get_plugins() must refuse the load."""
    host = PluginHost()
    errors = host._load_pack("batho_plugin.core")  # exists, zero plugins
    assert errors == []
    errors = host._load_pack("batho_plugin.does_not_exist_xyz")
    assert errors and "import failed" in errors[0]


def test_duplicate_plugin_id_rejected() -> None:
    host = PluginHost()
    host.register_data(_Pack())
    with pytest.raises(PluginLoadError, match="duplicate plugin_id"):
        host.register_data(_Pack())


def test_hook_stage_handler_consistency_validated() -> None:
    class _Broken:
        plugin_id = "broken"
        version = "1.0"
        stages = (Stage.ON_POST_ENTITIES,)  # no on_post_entities method

    host = PluginHost()
    with pytest.raises(PluginLoadError, match="does not implement"):
        host.register_hook(_Broken())

    class _BadStages:
        plugin_id = "badstages"
        version = "1.0"
        stages = ("on_post_entities",)  # strings, not Stage

    with pytest.raises(PluginLoadError, match="tuple of Stage"):
        PluginHost().register_hook(_BadStages())  # type: ignore[arg-type]


def test_dependency_cycle_detection() -> None:
    class _A:
        plugin_id = "a"
        version = "1.0"
        stages = (Stage.ON_POST_ENTITIES,)
        requires = ("b",)

        def on_post_entities(self, ctx: PluginContext) -> StageResult:
            return StageResult()

    class _B:
        plugin_id = "b"
        version = "1.0"
        stages = (Stage.ON_POST_ENTITIES,)
        requires = ("a",)

        def on_post_entities(self, ctx: PluginContext) -> StageResult:
            return StageResult()

    host = PluginHost()
    host.register_hook(_A())
    host.register_hook(_B())
    with pytest.raises(PluginLoadError, match="dependency cycle"):
        host._validate_dependency_cycles()


def test_no_plugins_flag_returns_empty_host() -> None:
    host = load_host(no_plugins=True)
    assert host.plugin_ids == ()
    assert host.data_registrations() == ()


def test_dispatch_records_telemetry() -> None:
    host = PluginHost()
    hook = _Hook()
    host.register_hook(hook, priority=5)
    ctx = PluginContext(file_path="a.py", root_path=Path("."))
    host.dispatch(Stage.ON_POST_ENTITIES, ctx)
    host.dispatch(Stage.ON_POST_ENTITIES, ctx)

    snap = host.telemetry.snapshot()
    assert snap["schema_version"] == "plugin-telemetry.v1"
    entry = snap["plugins"]["hook"]
    assert entry["calls"] == 2
    assert entry["total_ns"] > 0
    assert entry["avg_ns"] == entry["total_ns"] // 2
    assert entry["changed"] == 2


def test_registrations_sorted_and_versioned() -> None:
    host = PluginHost()
    host.register_data(_Pack())
    host.register_hook(_Hook())
    host.register_rule("rules-pack", "2.0", ("rule-a", "rule-b"))

    assert [r.plugin_id for r in host.data_registrations()] == ["pack"]
    assert host.data_registrations()[0].version == "1.0"
    assert [r.plugin_id for r in host.rule_registrations()] == ["rules-pack"]
    assert host.rule_registrations()[0].rule_ids == ("rule-a", "rule-b")
    assert host.plugin_ids == ("hook", "pack", "rules-pack")


def test_dispatch_coerces_none_returning_hook() -> None:
    """A hook that forgets its StageResult must not poison the results list:
    coerced to changed=False with an error detail, telemetry error counted,
    later hooks still run (per-unit isolation)."""

    class _NoneHook:
        plugin_id = "nonehook"
        version = "1.0"
        stages = (Stage.ON_POST_ENTITIES,)

        def on_post_entities(self, ctx: PluginContext) -> None:
            return None

    host = PluginHost()
    host.register_hook(_NoneHook(), priority=10)
    host.register_hook(_Hook(), priority=0)
    ctx = PluginContext(file_path="a.py", root_path=Path("."))

    results = host.dispatch(Stage.ON_POST_ENTITIES, ctx)

    assert len(results) == 2
    assert results[0].changed is False
    assert "returned None" in results[0].detail["error"]
    assert results[1].changed is True
    snap = host.telemetry.snapshot()["plugins"]
    assert snap["nonehook"]["errors"] == 1
    assert snap["nonehook"]["changed"] == 0
    assert snap["hook"]["calls"] == 1


def test_dispatch_order_recomputed_on_registration() -> None:
    """Priority-desc / id-asc order is precomputed at registration time and
    must track registrations made after earlier dispatches."""

    class _PrioHook:
        def __init__(self, pid: str) -> None:
            self.plugin_id = pid
            self.seen: list[str] = []

        version = "1.0"
        stages = (Stage.ON_POST_ENTITIES,)

        def on_post_entities(self, ctx: PluginContext) -> StageResult:
            self.seen.append(self.plugin_id)
            return StageResult()

    low = _PrioHook("aaa-low")
    high = _PrioHook("zzz-high")
    host = PluginHost()
    host.register_hook(low, priority=0)
    ctx = PluginContext(file_path="a.py", root_path=Path("."))
    host.dispatch(Stage.ON_POST_ENTITIES, ctx)  # order computed with one hook
    host.register_hook(high, priority=5)  # must reorder despite prior dispatch

    host.dispatch(Stage.ON_POST_ENTITIES, ctx)
    assert host._ordered_hooks[0][0] == "zzz-high"
    assert low.seen == ["aaa-low", "aaa-low"]
    assert high.seen == ["zzz-high"]


def test_lookup_caches_invalidate_on_registration() -> None:
    """get_set/get_map results are memoized per (key, language) and must be
    recomputed when a new data plugin registers (C4 compile-once contract)."""
    host = PluginHost()
    assert host.get_set("builtins", language="python") == frozenset()
    assert dict(host.get_map("strategy_confidence")) == {}

    host.register_data(_Pack())

    assert host.get_set("builtins", language="python") == frozenset({"print"})
    assert host.get_set("builtins") == frozenset({"len"})
    assert dict(host.get_map("strategy_confidence")) == {"exact_match": 0.95}


def test_get_map_returns_read_only_view() -> None:
    """The memoized merge is shared across calls — the public return is a
    read-only view so a mutating caller fails fast instead of corrupting
    the cache for every later caller."""
    host = PluginHost()
    host.register_data(_Pack())

    view = host.get_map("strategy_confidence")
    assert dict(view) == {"exact_match": 0.95}
    with pytest.raises(TypeError):
        view["exact_match"] = 0.0
    # Cache not corrupted by the attempted mutation.
    assert dict(host.get_map("strategy_confidence")) == {"exact_match": 0.95}


def test_degraded_core_pack_logs_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """core.required=false downgrades a broken core pack to a warning —
    never a silent degradation (a shifted plugin set changes the fingerprint
    and patch drift behavior)."""
    monkeypatch.setattr(
        PluginHost,
        "_load_pack",
        classmethod(lambda cls, name, select=None: [f"{name}: boom"]),
    )
    with caplog.at_level(logging.WARNING, logger="batho_plugin.host"):
        host = PluginHost.load(
            config={"plugins": {"core": {"required": False}}},
        )
    assert host.plugin_ids == ()
    assert "plugin_pack_load_degraded" in caplog.text
    assert "boom" in caplog.text


def test_degraded_external_pack_logs_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(
        PluginHost,
        "_load_pack",
        classmethod(
            lambda cls, name, select=None: []
            if name != "batho_plugin.external"
            else ["batho_plugin.external: boom"]
        ),
    )
    with caplog.at_level(logging.WARNING, logger="batho_plugin.host"):
        PluginHost.load(config={"plugins": {"external": {"enabled": True}}})
    assert "plugin_pack_load_degraded" in caplog.text
    assert "batho_plugin.external" in caplog.text
