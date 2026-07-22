"""Backend parity tests: in-memory vs arrow over a real build_graph run."""

from __future__ import annotations

from pathlib import Path

import structlog.testing

from batho.modules.graph.builder.arrow_graph import ArrowGraph
from batho.modules.graph.builder.codegraph import CodeGraphIndexer, InMemoryGraph
from batho.orchestrator.patch import PatchOptions, run_patch

_PY_FILES = {
    "mod_a.py": (
        '"""Module A."""\n\n\ndef helper(x: int) -> int:\n    return x + 1\n'
    ),
    "mod_b.py": (
        "from mod_a import helper\n\n\n"
        "def use_it(y: int) -> int:\n    return helper(y) * 2\n"
    ),
    "pkg/__init__.py": "",
    "pkg/mod_c.py": (
        "class Base:\n    pass\n\n\n"
        "class Derived(Base):\n    def run(self) -> None:\n        pass\n"
    ),
}


def _write_fixture_repo(root: Path) -> None:
    for rel, content in _PY_FILES.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _build(root: Path, backend: str):
    indexer = CodeGraphIndexer(cache_path=str(root), root=str(root))
    try:
        graph = indexer.build_graph(
            root=str(root),
            max_workers=1,
            ast_cache_enabled=False,
            graph_backend=backend,
        )
        return graph
    finally:
        indexer.close()


def test_build_graph_backend_parity(tmp_path: Path):
    """Both backends produce identical entity/relationship sets and stats."""
    # Same root for both builds: entity ids embed the absolute root path.
    root = tmp_path / "repo"
    _write_fixture_repo(root)

    graph_im = _build(root, "in-memory")
    graph_ar = _build(root, "arrow")
    try:
        assert isinstance(graph_im, InMemoryGraph)
        assert isinstance(graph_ar, ArrowGraph)
        assert graph_ar._compacted  # compacted by end of build_graph

        stats_im = graph_im.stats()
        stats_ar = graph_ar.stats()
        assert stats_im["entity_count"] == stats_ar["entity_count"] > 0
        assert stats_im["relationship_count"] == stats_ar["relationship_count"] > 0
        assert stats_im["entity_types"] == stats_ar["entity_types"]
        assert stats_im["relationship_types"] == stats_ar["relationship_types"]

        # Entity/rel id sets and payloads match on the storage view
        dict_im = graph_im.to_dict(view="storage")
        dict_ar = graph_ar.to_dict(view="storage")
        assert dict_ar["entities_by_id"].keys() == dict_im["entities_by_id"].keys()
        for eid, payload in dict_im["entities_by_id"].items():
            assert dict_ar["entities_by_id"][eid] == payload
        assert {r["id"] for r in dict_ar["relationships"]} == {
            r["id"] for r in dict_im["relationships"]
        }

        # Traversal parity on a sample of entities
        for eid in list(dict_im["entities_by_id"].keys())[:10]:
            assert sorted(graph_ar.neighbors(eid, "out")) == sorted(
                graph_im.neighbors(eid, "out")
            )
            assert sorted(graph_ar.neighbors(eid, "in")) == sorted(
                graph_im.neighbors(eid, "in")
            )
    finally:
        graph_ar.close()

    # Staging dir removed by close()
    assert not (root / ".batho" / "graph_staging").exists()


def test_auto_resolves_in_memory_for_small_repo(tmp_path: Path):
    """A small fixture repo stays on the in-memory backend under auto."""
    root = tmp_path / "repo"
    _write_fixture_repo(root)
    graph = _build(root, "auto")
    assert isinstance(graph, InMemoryGraph)


def test_patch_ignores_arrow_graph_backend(tmp_path: Path):
    """run_patch with graph_backend='arrow' warns and proceeds with in-memory."""
    root = tmp_path / "repo"
    root.mkdir()
    with structlog.testing.capture_logs() as logs:
        result = run_patch(PatchOptions(root=root, graph_backend="arrow"))
    # No bundle exists -> patch fails cleanly, but the warning is logged first
    assert result.success is False
    assert any(
        entry.get("event") == "patch_ignoring_graph_backend"
        and entry.get("requested") == "arrow"
        and entry.get("log_level") == "warning"
        for entry in logs
    ), logs
