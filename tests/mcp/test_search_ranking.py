"""T8: kind-aware deterministic search ranking (graph-accuracy-overhaul).

`search_entities` and the `get_entity` name fallback share
`batho/mcp/search_ranking.py`. Real definitions must outrank comments,
externals, and fixture noise; ordering is total and deterministic; recall is
unchanged (nothing is dropped — only reordered).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastmcp import FastMCP

from batho.mcp.search_ranking import (
    KIND_BOOST,
    SCORE_EXACT_NAME,
    SCORE_PREFIX,
    SCORE_SUBSTRING,
    language_for_path,
    rank_hits,
    score_hit,
)
from batho.mcp.server import create_app
from batho.modules.storage.arrow_bundle.reader import BathoBundleReader
from batho.orchestrator.build import BuildOptions, run_build

# ---------------------------------------------------------------------------
# Unit: scorer math per signal
# ---------------------------------------------------------------------------


def _row(name: str, entity_type: str = "FUNCTION", **kw) -> dict:
    row = {"name": name, "entity_type": entity_type, "entity_id": f"id::{name}"}
    row.update(kw)
    return row


def test_match_tiers():
    exact = score_hit(_row("get_entity"), "get_entity")
    prefix = score_hit(_row("get_entity_page"), "get_entity")
    sub = score_hit(_row("the_get_entity_fn"), "get_entity")
    assert exact - prefix == SCORE_EXACT_NAME - SCORE_PREFIX
    assert prefix - sub == SCORE_PREFIX - SCORE_SUBSTRING
    assert exact > prefix > sub


def test_collision_hash_suffix_ignored_for_exact_match():
    """`get_entity_[800748]` must score as an exact match for `get_entity`."""
    assert score_hit(_row("get_entity_[800748]"), "get_entity") >= SCORE_EXACT_NAME


def test_regex_query_scores_like_substring():
    assert score_hit(_row("get_entity"), "get_.*") >= SCORE_SUBSTRING


def test_regex_meta_query_never_runs_python_re():
    """Regex-safety ADR (issue 62b0f022c29c): the user pattern is never
    re-executed by Python `re` inside the scorer — rows already matched
    Arrow-side. `(?<name>a)` is valid RE2 but invalid Python `re`; under the
    old re.search fallback it raised re.error and collapsed to id-only."""
    assert (
        score_hit(_row("anything"), "(?<name>a)")
        == SCORE_SUBSTRING + KIND_BOOST["FUNCTION"]
    )


def test_pathological_regex_scores_without_backtracking():
    """`(a+)+$` catastrophically backtracks under Python `re` on a
    non-matching long input — this test would hang before the fix."""
    name = "a" * 40 + "b"
    assert (
        score_hit(_row(name), "(a+)+$")
        == SCORE_SUBSTRING + KIND_BOOST["FUNCTION"]
    )


def test_kind_boosts():
    fn = score_hit(_row("svc", "FUNCTION"), "svc")
    mod = score_hit(_row("svc", "MODULE"), "svc")
    comment = score_hit(_row("svc", "COMMENT_BLOCK"), "svc")
    ghost = score_hit(_row("svc", "EXTERNAL_SYMBOL"), "svc")
    assert fn == mod + (KIND_BOOST["FUNCTION"] - KIND_BOOST["MODULE"])
    assert comment < ghost < mod < fn


def test_exported_and_fqn_path_signals():
    plain = _row("handler")
    exported = _row("handler", is_exported=True)
    fqned = _row("handler", fqn="app.handlers.handler")
    assert score_hit(exported, "handler") > score_hit(plain, "handler")
    assert score_hit(fqned, "handler", file_path="x.py") > score_hit(
        plain, "handler", file_path="x.py"
    )
    # path segment match
    assert score_hit(plain, "handler", file_path="app/handlers/h.py") > score_hit(
        plain, "handler", file_path="app/main.py"
    )


def test_path_segment_match_never_crosses_segments():
    """Segment-local matching: normalized substring inside ONE segment only."""
    from batho.mcp.search_ranking import _path_segment_match

    assert _path_segment_match("registry", "app/repo_registry.py")
    # snake_case file vs PascalCase query
    assert _path_segment_match("ProcessManager", "core/process_manager.py")
    # cannot span the '/' boundary
    assert not _path_segment_match("appregistry", "app/registry.py")
    assert not _path_segment_match("core", "")


def test_language_hint_uses_entity_language():
    rust_fn = _row("make_thing")
    # query carrying `::` boosts the rust hit, not the python one
    rust = score_hit(rust_fn, "pkg::make_thing", language="rust")
    py = score_hit(rust_fn, "pkg::make_thing", language="python")
    assert rust == py + 5
    # php namespace separator
    php = score_hit(rust_fn, "App\\make_thing", language="php")
    assert php > score_hit(rust_fn, "App\\make_thing", language="python")
    # ts path alias — compare against python (no `/` separator), not go
    # which also lists "/" and would legitimately tie (MCP-08)
    ts = score_hit(rust_fn, "@/lib/make_thing", language="typescript")
    assert ts > score_hit(rust_fn, "@/lib/make_thing", language="python")
    # language derived from file extension
    assert language_for_path("src/lib/util.ts") == "typescript"
    assert language_for_path("App.java") == "java"
    assert language_for_path("x.unknownext") == ""


def test_test_path_demoted_below_real_definition():
    """T8: a test-fixture hit must not tie with the real definition."""
    real = score_hit(
        _row("svc.get_entity", entity_type="METHOD"), "get_entity", "app/services/graph.py"
    )
    fixture = score_hit(
        _row("TestSvc.test_get_entity", entity_type="METHOD"),
        "get_entity",
        "tests/services/test_graph.py",
    )
    assert fixture < real


def test_is_test_path_variants():
    from batho.mcp.search_ranking import _is_test_path

    assert _is_test_path("backend/tests/test_graph.py")
    assert _is_test_path("src/__tests__/client.ts")
    assert _is_test_path("pkg/foo_test.go")
    assert _is_test_path("app/user.test.ts")
    assert _is_test_path("app/user.spec.ts")
    assert not _is_test_path("app/services/graph_service.py")
    assert not _is_test_path("src/testing_utils.py")  # name, not a test file
    assert not _is_test_path("")


def test_rank_hits_deterministic_tiebreak():
    rows = [
        _row("dup", entity_id="id::b", start_line=20, file_id=2),
        _row("dup", entity_id="id::a", start_line=10, file_id=1),
    ]
    file_paths = {1: "a.py", 2: "b.py"}
    first = rank_hits(rows, "dup", file_paths)
    second = rank_hits(list(reversed(rows)), "dup", file_paths)
    assert [r["entity_id"] for r, _ in first] == [r["entity_id"] for r, _ in second]
    assert first[0][0]["start_line"] == 10  # start_line asc wins the tie


def test_rank_hits_memoizes_per_file_id(monkeypatch):
    """a70ed87100b0: path-derived scoring inputs are computed once per unique
    file_id, not once per row — file paths repeat heavily across rows."""
    import batho.mcp.search_ranking as sr

    counts = {"language_for_path": 0, "_path_segment_match": 0, "_is_test_path": 0}
    originals = {
        "language_for_path": sr.language_for_path,
        "_path_segment_match": sr._path_segment_match,
        "_is_test_path": sr._is_test_path,
    }

    def _counted(name):
        def wrapper(*args, **kwargs):
            counts[name] += 1
            return originals[name](*args, **kwargs)

        return wrapper

    for name in counts:
        monkeypatch.setattr(sr, name, _counted(name))

    # 10 rows across 3 unique file_ids (plus rows sharing a file_id).
    file_paths = {1: "app/svc/graph.py", 2: "app/main.py", 3: "tests/test_g.py"}
    rows = [
        _row("dup", entity_id=f"id::{i}", file_id=(i % 3) + 1) for i in range(10)
    ]
    ranked = rank_hits(rows, "dup", file_paths)
    assert len(ranked) == 10
    for name, n in counts.items():
        assert n <= len(file_paths), f"{name} called {n}x for 3 unique file_ids"
    # scores unchanged by memoization — same as an unmemoized score_hit call
    for row, score in ranked:
        assert score == score_hit(
            row, "dup",
            file_path=file_paths[row["file_id"]],
            language=language_for_path(file_paths[row["file_id"]]),
        )


def test_hash_suffix_strips_any_length_mixed_case():
    """d7eeb16f561c: the emitter's `_[hex]` collision suffix is any-length
    mixed-case (`_PARAM_HASH_PATTERN`), not exactly-6 lowercase."""
    exact = score_hit(_row("get_entity"), "get_entity")
    assert score_hit(_row("get_entity_[80AB]"), "get_entity") == exact
    assert score_hit(_row("get_entity_[12345]"), "get_entity") == exact
    # non-hex or malformed suffixes are still NOT stripped (only prefix-match)
    assert score_hit(_row("get_entity_[xyz]"), "get_entity") < exact
    assert score_hit(_row("get_entity_[80AB"), "get_entity") < exact


# ---------------------------------------------------------------------------
# Integration: ranked search over a built fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def repo_dir(tmp_path: Path) -> Path:
    repo = tmp_path / "rank_repo"
    repo.mkdir()
    (repo / "services.py").write_text(
        "class GraphService:\n"
        '    """Graph operations."""\n'
        "    def get_entity(self, entity_id: str) -> dict:\n"
        "        return {}\n"
        "\n"
        "def get_graph_service() -> GraphService:\n"
        "    return GraphService()\n",
        encoding="utf-8",
    )
    (repo / "router.py").write_text(
        "from services import GraphService, get_graph_service\n"
        "\n"
        "def Depends(f):\n"
        "    return f()\n"
        "\n"
        "def endpoint_get_entity(svc: GraphService = Depends(get_graph_service)):\n"
        "    return svc.get_entity('x')\n"
        "\n"
        "def loose(svc):\n"
        "    return svc.get_entity('y')\n",
        encoding="utf-8",
    )
    return repo


@pytest.fixture
def built_repo(repo_dir: Path) -> Path:
    result = run_build(BuildOptions(root=repo_dir))
    assert result.success, result.warnings
    return repo_dir


@pytest.fixture
def mcp_app(tmp_path: Path) -> FastMCP:
    return create_app(registry_path=tmp_path / "mcp-repos.json")


async def _register_and_search(mcp_app: FastMCP, repo: Path, query: str, **kw):
    res = await mcp_app.call_tool("add_repo", {"name": "t", "path": str(repo)})
    assert not res.is_error
    return await mcp_app.call_tool(
        "search_entities", {"query": query, "repo": "t", **kw}
    )


@pytest.mark.asyncio
async def test_real_method_outranks_ghost(mcp_app: FastMCP, built_repo: Path):
    """sageoz analog: `get_entity` top hit is the real METHOD, not the ghost."""
    res = await _register_and_search(mcp_app, built_repo, "get_entity")
    assert not res.is_error
    results = res.structured_content["results"]
    assert results, "no hits"
    top = results[0]
    assert top["type"] == "METHOD"
    assert top["name"].startswith("GraphService.get_entity")
    assert "score" in top


@pytest.mark.asyncio
async def test_unresolved_still_demoted_when_included(mcp_app: FastMCP, built_repo: Path):
    res = await _register_and_search(
        mcp_app, built_repo, "get_entity", include_unresolved=True, limit=50
    )
    assert not res.is_error
    results = res.structured_content["results"]
    ghosts = [r for r in results if r["id"].startswith("unresolved:")]
    real = [r for r in results if not r["id"].startswith("unresolved:")]
    assert ghosts, "expected ghost hits when include_unresolved=true"
    assert real[0]["score"] >= ghosts[0]["score"]


@pytest.mark.asyncio
async def test_class_beats_comment_block(mcp_app: FastMCP, built_repo: Path):
    res = await _register_and_search(mcp_app, built_repo, "GraphService", limit=50)
    assert not res.is_error
    results = res.structured_content["results"]
    assert results[0]["type"] == "CLASS"
    # comment-only kinds still findable — demoted, never hidden
    assert any(r["type"] == "COMMENT_BLOCK" for r in results)


@pytest.mark.asyncio
async def test_deterministic_identical_order(mcp_app: FastMCP, built_repo: Path):
    r1 = await _register_and_search(mcp_app, built_repo, "get", limit=50)
    r2 = await _register_and_search(mcp_app, built_repo, "get", limit=50)
    ids1 = [r["id"] for r in r1.structured_content["results"]]
    ids2 = [r["id"] for r in r2.structured_content["results"]]
    assert ids1 == ids2


@pytest.mark.asyncio
async def test_recall_unchanged_and_pagination_keeps_score(mcp_app: FastMCP, built_repo: Path):
    reader = BathoBundleReader(built_repo / ".batho" / "artifact")
    import pyarrow.compute as pc

    table = reader._get_table("agent_views")
    expected = table.filter(pc.match_substring_regex(table.column("name"), "get"))
    expected_total = expected.num_rows

    res = await _register_and_search(mcp_app, built_repo, "get", limit=50)
    meta = res.structured_content["meta"]
    suppressed = meta.get("unresolved_suppressed", 0)
    # nothing dropped: returned + suppressed == raw name-match count
    assert meta["total_matches"] + suppressed == expected_total

    # pagination: top-2 of limit=2 must equal the head of limit=50
    paged = await _register_and_search(mcp_app, built_repo, "get", limit=2)
    ids_full = [r["id"] for r in res.structured_content["results"]]
    ids_paged = [r["id"] for r in paged.structured_content["results"]]
    assert ids_paged == ids_full[:2]


def test_get_entity_fallback_candidates_ranked(tmp_path: Path):
    """Bare-name fallback: multiple candidates return in scorer order."""
    from batho.mcp.tools import _resolve_entity_id

    repo = tmp_path / "dup_repo"
    (repo / "a").mkdir(parents=True)
    (repo / "b").mkdir(parents=True)
    (repo / "a" / "graph.py").write_text("def ga():\n    return 1\n", encoding="utf-8")
    (repo / "b" / "graph.py").write_text("def gb():\n    return 1\n", encoding="utf-8")
    result = run_build(BuildOptions(root=repo))
    assert result.success, result.warnings

    reader = BathoBundleReader(repo / ".batho" / "artifact")
    cands = _resolve_entity_id("graph", reader)
    assert isinstance(cands, list) and len(cands) >= 2, cands
    scores = [c["score"] for c in cands]
    assert scores == sorted(scores, reverse=True)
    # deterministic across calls
    assert [c["entity_id"] for c in _resolve_entity_id("graph", reader)] == [
        c["entity_id"] for c in cands
    ]
