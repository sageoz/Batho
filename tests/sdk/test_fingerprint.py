"""tests/sdk/test_fingerprint.py — T04: plugin-set fingerprint.

Stability, sensitivity to version/data changes, parent/worker parity, and
host integration (spec §9).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from batho_plugin import PluginData, PluginHost, Stage, StageResult, PluginContext
from batho_plugin.fingerprint import (
    compute_fingerprint,
    data_hash,
    entry,
    fingerprint_from_host,
)


class _Pack:
    plugin_id = "pack"
    version = "1.0"

    def __init__(self, extra: str | None = None) -> None:
        self._extra = extra

    def compile(self) -> PluginData:
        sets = {"builtins": frozenset({"len", "range"})}
        if self._extra:
            sets["builtins"] = frozenset({"len", "range", self._extra})
        return PluginData(sets=sets)


def test_fingerprint_stable() -> None:
    a = compute_fingerprint([entry("p", "1.0", "abc")])
    b = compute_fingerprint([entry("p", "1.0", "abc")])
    assert a == b
    assert len(a) == 64  # sha256 hex


def test_fingerprint_order_insensitive() -> None:
    a = compute_fingerprint([entry("a", "1", "h1"), entry("b", "2", "h2")])
    b = compute_fingerprint([entry("b", "2", "h2"), entry("a", "1", "h1")])
    assert a == b


def test_fingerprint_sensitive_to_version_and_data() -> None:
    base = compute_fingerprint([entry("p", "1.0", data_hash(_Pack().compile()))])
    version_bump = compute_fingerprint([entry("p", "1.1", data_hash(_Pack().compile()))])
    data_change = compute_fingerprint(
        [entry("p", "1.0", data_hash(_Pack(extra="print").compile()))]
    )
    membership_change = compute_fingerprint(
        [entry("q", "1.0", data_hash(_Pack().compile()))]
    )
    assert len({base, version_bump, data_change, membership_change}) == 4


def test_data_hash_canonicalizes_sets() -> None:
    """Set iteration order must not affect the hash (determinism)."""
    d1 = PluginData(sets={"s": frozenset({"a", "b", "c"})})
    d2 = PluginData(sets={"s": frozenset({"c", "a", "b"})})
    assert data_hash(d1) == data_hash(d2)


def test_fingerprint_from_host_covers_all_kinds() -> None:
    class _Hook:
        plugin_id = "hook"
        version = "3.0"
        stages = (Stage.ON_POST_ENTITIES,)

        def on_post_entities(self, ctx: PluginContext) -> StageResult:
            return StageResult()

    host = PluginHost()
    host.register_data(_Pack())
    host.register_hook(_Hook(), priority=7)
    host.register_rule("rules", "2.0", ("r1", "r2"))

    fp = fingerprint_from_host(host)
    assert len(fp) == 64

    # Changing hook priority changes the fingerprint (behavior-affecting).
    host2 = PluginHost()
    host2.register_data(_Pack())
    host2.register_hook(_Hook(), priority=8)
    host2.register_rule("rules", "2.0", ("r1", "r2"))
    assert fingerprint_from_host(host2) != fp

    # Identical set → identical fingerprint.
    host3 = PluginHost()
    host3.register_data(_Pack())
    host3.register_hook(_Hook(), priority=7)
    host3.register_rule("rules", "2.0", ("r1", "r2"))
    assert fingerprint_from_host(host3) == fp


def test_fingerprint_same_in_forked_worker() -> None:
    """The fingerprint must be identical in the parent and a forked worker."""
    code = (
        "from batho_plugin import PluginData\n"
        "from batho_plugin.fingerprint import data_hash, entry, compute_fingerprint\n"
        "d = PluginData(sets={'builtins': frozenset({'len', 'range'})})\n"
        "print(compute_fingerprint([entry('pack', '1.0', data_hash(d))]))\n"
    )
    parent = compute_fingerprint(
        [entry("pack", "1.0", data_hash(PluginData(sets={"builtins": frozenset({"len", "range"})})))]
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    assert out.stdout.strip() == parent


def test_cache_variant_includes_plugin_fingerprint() -> None:
    """T15/T28: the AST cache variant must change with the plugin set.

    Same plugin fingerprint → same variant (cache hit); any plugin change
    → different variant (cache miss → re-extract).
    """
    from batho.modules.storage.cache.unified_cache import build_ast_cache_variant

    fp_a = compute_fingerprint([entry("p", "1.0", data_hash(_Pack().compile()))])
    fp_b = compute_fingerprint(
        [entry("p", "1.0", data_hash(_Pack(extra="print").compile()))]
    )
    base_kw = {"include_gaps": True, "parsing_config": {"strict": True}}
    v1 = build_ast_cache_variant(**base_kw, plugin_fingerprint=fp_a)
    v2 = build_ast_cache_variant(**base_kw, plugin_fingerprint=fp_a)
    assert v1 == v2  # identical plugin set → cache hit
    assert build_ast_cache_variant(**base_kw, plugin_fingerprint=fp_b) != v1
    assert build_ast_cache_variant(**base_kw, plugin_fingerprint="") != v1
    # plugins disabled entirely → still distinct, still stable
    assert build_ast_cache_variant(**base_kw) == build_ast_cache_variant(
        **base_kw, plugin_fingerprint=""
    )


def test_pack_membership_toggle() -> None:
    """A pack toggled on/off changes the set fingerprint (spec §9)."""
    host_on = PluginHost()
    host_on.register_data(_Pack())

    class _Pack2:
        plugin_id = "pack2"
        version = "1.0"

        def compile(self) -> PluginData:
            return PluginData(sets={"extra": frozenset({"x"})})

    host_on.register_data(_Pack2())
    host_off = PluginHost()
    host_off.register_data(_Pack())
    assert fingerprint_from_host(host_on) != fingerprint_from_host(host_off)
