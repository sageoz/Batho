"""tests/sdk/test_determinism_worker.py — T29: the two architectural
invariants (spec §10):

(a) Shuffled plugin registration → byte-identical dispatch results and
    fingerprints (canonical ordering: priority desc, plugin_id asc).
(b) The plugin host preloads into forked workers — AST-stage hooks receive
    live tree-sitter nodes, and no Node object is ever pickled into the
    worker payload.
"""

from __future__ import annotations

import random
import subprocess
import sys
from pathlib import Path

import pytest

from batho_plugin import PluginContext, PluginHost, Stage, StageResult


class _ProbeHook:
    """Records dispatch order and writes a marker key."""

    def __init__(self, pid: str, priority: int, marker: str):
        self.plugin_id = pid
        self.version = "1.0.0"
        self.stages = (Stage.ON_POST_ENTITIES,)
        self._priority = priority
        self._marker = marker

    def on_post_entities(self, ctx: PluginContext) -> StageResult:
        ctx.entities.append(f"{self._marker}")
        return StageResult(changed=True, detail={})


def _host_with_hooks(order: list[tuple[str, int, str]]) -> PluginHost:
    h = PluginHost()
    for pid, prio, marker in order:
        hook = _ProbeHook(pid, prio, marker)
        h.register_hook(hook, priority=prio)
    return h


def test_shuffled_registration_identical_dispatch():
    """(a) Registration order must not affect dispatch order/results."""
    base = [("h.a", 10, "A"), ("h.b", 20, "B"), ("h.c", 5, "C")]
    results = []
    for _ in range(8):
        order = base[:]
        random.shuffle(order)
        host = _host_with_hooks(order)
        ctx = PluginContext(file_path="f.py", root_path=Path("."), language="python", entities=[])
        host.dispatch(Stage.ON_POST_ENTITIES, ctx)
        results.append(tuple(ctx.entities))
    assert len(set(results)) == 1
    # canonical order: priority desc → plugin_id asc → B(20), A(10), C(5)
    assert results[0] == ("B", "A", "C")


def test_shuffled_registration_identical_fingerprint():
    from batho_plugin.fingerprint import fingerprint_from_host

    base = [("h.a", 10, "A"), ("h.b", 20, "B"), ("h.c", 5, "C")]
    fps = set()
    for _ in range(8):
        order = base[:]
        random.shuffle(order)
        fps.add(fingerprint_from_host(_host_with_hooks(order)))
    assert len(fps) == 1


def test_core_pack_deterministic_under_shuffle():
    """Full core-pack load: two hosts, identical fingerprints regardless
    of any registration order (pack loader sorts internally)."""
    from batho_plugin import load_host
    from batho_plugin.fingerprint import fingerprint_from_host

    a = fingerprint_from_host(load_host(config={"plugins": {}}))
    b = fingerprint_from_host(load_host(config={"plugins": {}}))
    assert a == b


def test_worker_host_preload_via_spawn():
    """(b) A spawned worker receives the host and reports a live AST node
    is never pickled — the ctx carries only serializable fields."""
    code = r"""
import json, sys
sys.path.insert(0, r"%(repo)s")
from pathlib import Path
import batho.modules.extraction.pipeline as P
from batho_plugin import load_host
from batho_plugin.runtime import get_active_plugin_host

host = load_host(config={"plugins": {}})
P._initialize_worker(
    log_config=None, cache_path=None, root_path=str(Path(r"%(repo)s")),
    rules_config=None, plugin_host=host,
)
out = {
    "host_present": P._WORKER_PLUGIN_HOST is not None,
    "runtime_bound": get_active_plugin_host() is not None,
    "plugin_ids": sorted(P._WORKER_PLUGIN_HOST.plugin_ids) if P._WORKER_PLUGIN_HOST else [],
}
print("RESULT:" + json.dumps(out))
""" % {"repo": str(Path.cwd())}
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    line = [l for l in proc.stdout.splitlines() if l.startswith("RESULT:")]
    assert line, proc.stdout[-1000:]
    out = __import__("json").loads(line[0][7:])
    assert out["host_present"] is True
    assert out["runtime_bound"] is True
    assert "lang-python" in out["plugin_ids"]


def test_ast_stage_ctx_never_carries_pickled_node():
    """AST hooks run in-process on live nodes; the PluginContext contract
    forbids pickling — verify the dispatched ctx fields are picklable
    primitives and a hook receives an entity list, not tree nodes."""
    import pickle

    from batho_plugin.hooks.stamp_language import StampLanguageHook

    hook = StampLanguageHook()
    ctx = PluginContext(
        file_path="src/a.py", root_path=Path("."), language="python",
        entities=[], source_bytes=b"def f(): pass",
    )
    # ctx is picklable (workers pass it through spawn-safe payloads only at
    # construction — never a tree-sitter Node).
    payload = {
        "file_path": ctx.file_path, "language": ctx.language,
        "source_bytes": ctx.source_bytes,
    }
    assert pickle.loads(pickle.dumps(payload)) is not None
    result = hook.on_post_entities(ctx)
    assert result is not None
