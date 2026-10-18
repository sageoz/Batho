"""Tests for unresolved-ref quarantine (T2, graph-accuracy-overhaul).

`unresolved:` stub entities must be hidden from search_entities, graph_overview
counts, graph_query node results, and community detection by default — while
remaining in storage and reachable via include_unresolved=true.
"""

from pathlib import Path

import pytest
from fastmcp import FastMCP

from batho.mcp.server import create_app
from batho.mcp.registry import RepoRegistry
from batho.orchestrator.build import run_build, BuildOptions


@pytest.fixture
def repo_dir(tmp_path: Path) -> Path:
    """Repo whose unresolvable method call produces an `unresolved:` stub."""
    repo = tmp_path / "sample_repo"
    repo.mkdir()
    (repo / "main.py").write_text(
        "def handler(svc):\n"
        "    # svc has no annotation -> ghost_thing() cannot resolve\n"
        "    return svc.ghost_thing()\n"
        "\n"
        "def real_func():\n"
        "    return 1\n",
        encoding="utf-8",
    )
    return repo


@pytest.fixture
def repo_with_artifact(repo_dir: Path) -> Path:
    run_build(BuildOptions(root=repo_dir))
    return repo_dir


@pytest.fixture
def mcp_app(tmp_path: Path) -> FastMCP:
    return create_app(registry_path=tmp_path / "mcp-repos.json")


async def _register(mcp_app: FastMCP, repo: Path):
    res = await mcp_app.call_tool("add_repo", {"name": "t", "path": str(repo)})
    assert not res.is_error


@pytest.mark.asyncio
async def test_search_entities_quarantines_stubs(mcp_app: FastMCP, repo_with_artifact: Path):
    await _register(mcp_app, repo_with_artifact)
    res = await mcp_app.call_tool("search_entities", {"query": "ghost_thing", "repo": "t"})
    assert not res.is_error
    assert res.structured_content["meta"]["total_matches"] == 0

    res2 = await mcp_app.call_tool(
        "search_entities", {"query": "ghost_thing", "repo": "t", "include_unresolved": True}
    )
    assert not res2.is_error
    assert res2.structured_content["meta"]["total_matches"] >= 1


@pytest.mark.asyncio
async def test_search_entities_real_symbols_unaffected(mcp_app: FastMCP, repo_with_artifact: Path):
    await _register(mcp_app, repo_with_artifact)
    res = await mcp_app.call_tool("search_entities", {"query": "real_func", "repo": "t"})
    assert not res.is_error
    assert res.structured_content["meta"]["total_matches"] >= 1


@pytest.mark.asyncio
async def test_graph_overview_counts_exclude_stubs(mcp_app: FastMCP, repo_with_artifact: Path):
    await _register(mcp_app, repo_with_artifact)
    res = await mcp_app.call_tool("graph_overview", {"repo": "t"})
    assert not res.is_error
    stats = res.structured_content["overview"]["stats"]
    # unresolved refs are reported separately, not inside total_entities
    assert stats["unresolved_refs"] == stats["stub_entity_count"]
    if stats["unresolved_refs"]:
        assert stats["unresolved_refs"] >= 1


@pytest.mark.asyncio
async def test_graph_query_quarantines_stubs(mcp_app: FastMCP, repo_with_artifact: Path):
    await _register(mcp_app, repo_with_artifact)
    res = await mcp_app.call_tool(
        "graph_query", {"repo": "t", "name_pattern": "ghost_thing"}
    )
    assert not res.is_error
    assert res.structured_content["meta"]["total_nodes"] == 0

    res2 = await mcp_app.call_tool(
        "graph_query", {"repo": "t", "name_pattern": "ghost_thing", "include_unresolved": True}
    )
    assert not res2.is_error
    assert res2.structured_content["meta"]["total_nodes"] >= 1


@pytest.mark.asyncio
async def test_graph_query_reports_suppressed_counts(mcp_app: FastMCP, repo_with_artifact: Path):
    """MCP-03: graph_query must surface how many entities the default
    quarantine/unresolved masks suppressed — in structured meta and the
    markdown footer — not silently drop them."""
    await _register(mcp_app, repo_with_artifact)
    res = await mcp_app.call_tool(
        "graph_query", {"repo": "t", "name_pattern": "ghost_thing"}
    )
    assert not res.is_error
    meta = res.structured_content["meta"]
    assert meta["total_nodes"] == 0
    assert meta.get("unresolved_suppressed", 0) >= 1
    # markdown footer mirrors the structured meta
    md = res.content[0].text if res.content else ""
    assert "unresolved" in md

    # include_unresolved=true clears the suppression counters
    res2 = await mcp_app.call_tool(
        "graph_query", {"repo": "t", "name_pattern": "ghost_thing", "include_unresolved": True}
    )
    assert not res2.is_error
    assert res2.structured_content["meta"]["total_nodes"] == meta["unresolved_suppressed"]
    assert res2.structured_content["meta"].get("unresolved_suppressed", 0) == 0


@pytest.mark.asyncio
async def test_search_entities_suppression_counts_after_type_filter(
    mcp_app: FastMCP, repo_with_artifact: Path
):
    """MCP-07: unresolved/quarantine suppression counts must be computed on
    the type/role-filtered candidate set — a stub filtered out by
    entity_types must not inflate unresolved_suppressed."""
    await _register(mcp_app, repo_with_artifact)
    # ghost stubs are EXTERNAL_SYMBOL — a FUNCTION type filter excludes them
    # upstream, so suppression must report zero, not the pre-filter hit count.
    res = await mcp_app.call_tool(
        "search_entities",
        {"query": "ghost_thing", "repo": "t", "entity_types": ["FUNCTION"]},
    )
    assert not res.is_error
    meta = res.structured_content["meta"]
    assert meta["total_matches"] == 0
    assert meta.get("unresolved_suppressed", 0) == 0
    # …while an EXTERNAL_SYMBOL filter keeps the stub in the candidate set
    res2 = await mcp_app.call_tool(
        "search_entities",
        {"query": "ghost_thing", "repo": "t", "entity_types": ["EXTERNAL_SYMBOL"]},
    )
    assert not res2.is_error
    assert res2.structured_content["meta"].get("unresolved_suppressed", 0) >= 1


@pytest.mark.asyncio
async def test_search_entities_quarantined_suppressed_in_meta(
    mcp_app: FastMCP, repo_with_artifact: Path, monkeypatch
):
    """MCP-05: quarantined_suppressed must appear in structured meta (it was
    previously only rendered in the markdown footer)."""
    from batho.mcp import tools as mcp_tools

    await _register(mcp_app, repo_with_artifact)
    monkeypatch.setattr(
        mcp_tools,
        "_quarantined_entity_ids",
        lambda table: {r["entity_id"] for r in table.to_pylist()},
    )
    res = await mcp_app.call_tool(
        "search_entities", {"query": "real_func", "repo": "t"}
    )
    assert not res.is_error
    meta = res.structured_content["meta"]
    assert meta["total_matches"] == 0
    assert meta.get("quarantined_suppressed", 0) >= 1

    res2 = await mcp_app.call_tool(
        "search_entities",
        {"query": "real_func", "repo": "t", "include_quarantined": True},
    )
    assert not res2.is_error
    assert res2.structured_content["meta"]["total_matches"] == meta["quarantined_suppressed"]


def test_overview_unresolved_pct_uses_pre_quarantine_denominator():
    """MCP-02: stub_entity_count is excluded from total_entities, so the
    'unresolved' percentage must divide by total+stubs — otherwise removing
    stubs inflates the ratio (e.g. 25/100=25% vs the honest 25/125=20%)."""
    from batho.mcp.graph_builder import format_summary

    def patterns_line(total: int, stubs: int) -> str:
        return format_summary(
            {
                "total_entities": total,
                "stub_entity_count": stubs,
                "entity_breakdown": {"EXTERNAL_SYMBOL": stubs},
            }
        )

    # 25/125 = 20% — at the threshold, must NOT report "significant"
    assert "unresolved" not in patterns_line(total=100, stubs=25)
    # 50/150 = 33% — genuinely significant
    assert "(33% unresolved)" in patterns_line(total=100, stubs=50)


@pytest.mark.asyncio
async def test_graph_query_stub_mask_combines_with_other_filters(mcp_app: FastMCP, repo_with_artifact: Path):
    """744fdb79c55c: the `unresolved:` mask is applied together with (after)
    the file/type/name filters — conjunctive, so results must be identical.
    Ghost stubs are EXTERNAL_SYMBOL, so a type filter still must not leak them."""
    await _register(mcp_app, repo_with_artifact)
    res = await mcp_app.call_tool(
        "graph_query", {"repo": "t", "entity_types": ["EXTERNAL_SYMBOL"]}
    )
    assert not res.is_error
    nodes = res.structured_content["graph"]["nodes"]
    assert all(not n["id"].startswith("unresolved:") for n in nodes)

    res2 = await mcp_app.call_tool(
        "graph_query",
        {"repo": "t", "entity_types": ["EXTERNAL_SYMBOL"], "include_unresolved": True},
    )
    assert not res2.is_error
    # stubs are EXTERNAL_SYMBOL in new artifacts — including them must grow
    # the type-filtered count, and they must appear in the page
    total_off = res.structured_content["meta"]["total_nodes"]
    total_on = res2.structured_content["meta"]["total_nodes"]
    assert total_on > total_off
    assert any(
        n["id"].startswith("unresolved:")
        for n in res2.structured_content["graph"]["nodes"]
    )


@pytest.mark.asyncio
async def test_search_entities_reports_suppressed_count(mcp_app: FastMCP, repo_with_artifact: Path):
    """744fdb79c55c(b): unresolved_suppressed counts stubs without
    materializing a filtered table — value must equal the actual stub hits."""
    await _register(mcp_app, repo_with_artifact)
    res = await mcp_app.call_tool(
        "search_entities", {"query": "ghost_thing", "repo": "t"}
    )
    assert not res.is_error
    meta = res.structured_content["meta"]
    assert meta["total_matches"] == 0
    assert meta.get("unresolved_suppressed", 0) >= 1

    res2 = await mcp_app.call_tool(
        "search_entities",
        {"query": "ghost_thing", "repo": "t", "include_unresolved": True},
    )
    assert not res2.is_error
    # suppressed count == hits that reappear when include_unresolved=true
    assert res2.structured_content["meta"]["total_matches"] == meta["unresolved_suppressed"]


class TestCommunityDetectionGhostExclusion:
    def _make_graph(self):
        from batho.modules.graph import InMemoryGraph
        from batho.core.schemas import Entity, EntityType, Relationship, RelationshipType

        g = InMemoryGraph()
        real = []
        for i in range(6):
            e = Entity(
                type=EntityType.FUNCTION,
                name=f"real_{i}",
                file=f"mod_{i % 2}.py",
                start_line=i * 10,
                end_line=i * 10 + 5,
            )
            real.append(e)
            g.add_entity(e)
        for i in range(len(real) - 1):
            g.add_relationship(Relationship(
                source_id=real[i].id, target_id=real[i + 1].id,
                type=RelationshipType.CALLS, file="mod_0.py",
            ))
        # ghost entity + edges targeting it (the pre-fix pollution pattern)
        ghost = Entity(
            type=EntityType.EXTERNAL_SYMBOL, name="ghost_thing", file="mod_0.py",
            start_line=1, end_line=1, id_override="unresolved:mod_0.py::ghost_thing",
        )
        g.add_entity(ghost)
        g.add_relationship(Relationship(
            source_id=real[0].id, target_id=ghost.id,
            type=RelationshipType.CALLS, file="mod_0.py",
        ))
        return g, ghost.id

    def test_ghosts_excluded_from_communities(self):
        from batho.modules.graph import detect_communities

        graph, ghost_id = self._make_graph()
        communities = detect_communities(graph)
        assert communities, "expected at least one community of real entities"
        for c in communities:
            assert ghost_id not in c.member_entity_ids
            assert "ghost_thing" not in c.top_entities

    def test_all_ghost_graph_returns_empty(self):
        from batho.modules.graph import InMemoryGraph, detect_communities
        from batho.core.schemas import Entity, EntityType, Relationship, RelationshipType

        g = InMemoryGraph()
        g1 = Entity(type=EntityType.EXTERNAL_SYMBOL, name="a", file="x.py",
                    start_line=1, end_line=1, id_override="unresolved:x.py::a")
        g2 = Entity(type=EntityType.EXTERNAL_SYMBOL, name="b", file="x.py",
                    start_line=1, end_line=1, id_override="unresolved:x.py::b")
        g.add_entity(g1)
        g.add_entity(g2)
        g.add_relationship(Relationship(
            source_id=g1.id, target_id=g2.id, type=RelationshipType.CALLS, file="x.py"
        ))
        assert detect_communities(g) == []
