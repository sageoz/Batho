"""T6 ground-truth trace_path regression suite (graph-accuracy-overhaul).

Fixture repos live checked-in under ``tests/fixtures/trace_repos/<name>/`` and
``tests/fixtures/trace_ground_truth.yaml`` declares each expected trace as
``{repo_fixture, source, target, expected_hops, expected_edge_kinds}`` (or
``expect_no_path: true`` for negative cases). Each fixture is copied to a tmp
dir and built in-session — the suite never touches an external repo.

The suite locks in three guarantees:

- endpoint→service traces resolve to direct CALLS hops (no structural detours)
- traversal is default-deny: only whitelisted structural edge kinds are
  expanded — RATIONALE_FOR and any future annotation relation can
  never leak into a path, even when they would shorten it
- every call-expression family T1 binds (``call`` / ``call_expression`` /
  ``method_invocation``) is covered: python, ts/tsx, rust, go, java
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pyarrow as pa
import pyarrow.ipc as pa_ipc
import pytest
import yaml
from fastmcp import FastMCP

from batho.mcp.server import create_app
from batho.mcp.tools import TRACE_TRAVERSABLE_RELATIONS
from batho.modules.storage.arrow_bundle.reader import BathoBundleReader
from batho.orchestrator.build import BuildOptions, run_build

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"
MANIFEST_PATH = FIXTURE_DIR / "trace_ground_truth.yaml"
REPO_FIXTURES_DIR = FIXTURE_DIR / "trace_repos"

TRACES: list[dict] = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))["traces"]


def _trace_id(trace: dict) -> str:
    return f"{trace['repo_fixture']}:{trace['source']}->{trace['target']}"


@pytest.fixture(scope="module")
def built_repos(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Copy each checked-in fixture repo to tmp and run `batho build` once.

    Building the copy keeps the checked-in fixtures free of `.batho/`
    artifacts; the AST cache makes rebuilds cheap.
    """
    roots: dict[str, Path] = {}
    for repo_dir in sorted(REPO_FIXTURES_DIR.iterdir()):
        if not repo_dir.is_dir():
            continue
        dest = tmp_path_factory.mktemp(f"tt_{repo_dir.name}") / repo_dir.name
        shutil.copytree(repo_dir, dest)
        result = run_build(BuildOptions(root=dest))
        assert result.success, f"build failed for {repo_dir.name}: {result.warnings}"
        roots[repo_dir.name] = dest
    return roots


@pytest.fixture
def mcp_app(tmp_path: Path) -> FastMCP:
    return create_app(registry_path=tmp_path / "mcp-repos.json")


_HASH_SUFFIX = re.compile(r"_\[[0-9a-f]{6}\]$")


def _entity_id(reader: BathoBundleReader, spec: str, repo_fixture: str) -> str:
    """Resolve a manifest name to a unique entity_id in the fixture artifact.

    `spec` may carry an ``@ENTITY_TYPE`` suffix (e.g. ``orphan_a@FUNCTION``)
    to disambiguate MODULE/FUNCTION name collisions. ``unresolved:`` stubs are
    skipped — a trace endpoint must be a real entity. Display names get a
    ``_[xxxxxx]`` collision suffix, which is stripped before comparing.
    """
    spec_name, _, spec_kind = spec.partition("@")
    matches = []
    for row in reader._get_table("agent_views").to_pylist():
        eid = str(row.get("entity_id") or "")
        if eid.startswith("unresolved:"):
            continue
        name = _HASH_SUFFIX.sub("", str(row.get("name") or ""))
        if spec_kind and row.get("entity_type") != spec_kind:
            continue
        if name == spec_name or name.endswith(f".{spec_name}"):
            matches.append(eid)
    unique = sorted(set(matches))
    assert len(unique) == 1, (
        f"{spec!r} matched {unique or 'nothing'} in fixture {repo_fixture}"
    )
    return unique[0]


async def _register(mcp_app: FastMCP, repo: Path, name: str = "t") -> None:
    res = await mcp_app.call_tool("add_repo", {"name": name, "path": str(repo)})
    assert not res.is_error


async def _trace(mcp_app: FastMCP, repo: Path, source_id: str, target_id: str, **extra):
    return await mcp_app.call_tool(
        "trace_path",
        {
            "source_entity_id": source_id,
            "target_entity_id": target_id,
            "repo": "t",
            **extra,
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("trace", TRACES, ids=_trace_id)
async def test_ground_truth_trace(trace: dict, built_repos: dict[str, Path], mcp_app: FastMCP):
    repo = built_repos[trace["repo_fixture"]]
    await _register(mcp_app, repo)

    reader = BathoBundleReader(repo / ".batho" / "artifact")
    source_id = _entity_id(reader, trace["source"], trace["repo_fixture"])
    target_id = _entity_id(reader, trace["target"], trace["repo_fixture"])

    extra = {"max_depth": trace["max_depth"]} if "max_depth" in trace else {}
    res = await _trace(mcp_app, repo, source_id, target_id, **extra)

    if trace.get("expect_no_path"):
        # Disconnected pair → structured "no path" error, not an exception.
        assert res.is_error, (
            f"expected no path for {_trace_id(trace)}, got {res.structured_content}"
        )
        return

    assert not res.is_error, res.content
    sc = res.structured_content
    assert sc["depth"] == trace["expected_hops"], (
        f"{_trace_id(trace)}: depth {sc['depth']} != {trace['expected_hops']}; "
        f"path={sc['path']}"
    )
    kinds = [hop["relation_type"] for hop in sc["path"][1:]]
    assert kinds == trace["expected_edge_kinds"], (
        f"{_trace_id(trace)}: hops {kinds} != {trace['expected_edge_kinds']}"
    )
    assert set(kinds) <= TRACE_TRAVERSABLE_RELATIONS
    assert sc["meta"]["edge_priority"]["path_edge_kinds"] == kinds


@pytest.mark.asyncio
async def test_trace_deterministic(mcp_app: FastMCP, built_repos: dict[str, Path]):
    """Identical query → identical path (stable ordering across calls)."""
    repo = built_repos["py_backend"]
    await _register(mcp_app, repo)
    reader = BathoBundleReader(repo / ".batho" / "artifact")
    sid = _entity_id(reader, "endpoint_create", "py_backend")
    tid = _entity_id(reader, "normalize_name", "py_backend")
    first = await _trace(mcp_app, repo, sid, tid)
    second = await _trace(mcp_app, repo, sid, tid)
    assert first.structured_content["path"] == second.structured_content["path"]


@pytest.mark.asyncio
async def test_trace_source_equals_target(mcp_app: FastMCP, built_repos: dict[str, Path]):
    """0-hop: source == target returns the node itself at depth 0."""
    repo = built_repos["synthetic_min"]
    await _register(mcp_app, repo)
    reader = BathoBundleReader(repo / ".batho" / "artifact")
    sid = _entity_id(reader, "a", "synthetic_min")
    res = await _trace(mcp_app, repo, sid, sid)
    assert not res.is_error, res.content
    assert res.structured_content["depth"] == 0
    assert len(res.structured_content["path"]) == 1


@pytest.mark.asyncio
async def test_trace_cycle_guard(mcp_app: FastMCP, tmp_path: Path):
    """Mutual recursion must not loop forever — the BFS visited-set guards it."""
    repo = tmp_path / "cycle_repo"
    repo.mkdir()
    (repo / "cyc.py").write_text(
        "def ping():\n    return pong()\n\n"
        "def pong():\n    return ping()\n\n"
        "def elsewhere():\n    return 0\n",
        encoding="utf-8",
    )
    result = run_build(BuildOptions(root=repo))
    assert result.success, result.warnings
    await _register(mcp_app, repo)

    reader = BathoBundleReader(repo / ".batho" / "artifact")
    ping = _entity_id(reader, "ping", "cycle_repo")
    elsewhere = _entity_id(reader, "elsewhere", "cycle_repo")
    res = await _trace(mcp_app, repo, ping, elsewhere)
    assert res.is_error  # unreachable target → clean no-path, no hang


@pytest.mark.asyncio
async def test_non_structural_relation_types_rejected(mcp_app: FastMCP, built_repos: dict[str, Path]):
    """An explicit relation_types filter can only narrow the structural
    whitelist — annotation/inferred kinds are not traversable on request."""
    repo = built_repos["synthetic_min"]
    await _register(mcp_app, repo)
    reader = BathoBundleReader(repo / ".batho" / "artifact")
    sid = _entity_id(reader, "a", "synthetic_min")
    tid = _entity_id(reader, "c", "synthetic_min")
    res = await _trace(
        mcp_app, repo, sid, tid, relation_types=["RATIONALE_FOR"]
    )
    assert res.is_error
    text = res.content[0].text if res.content else ""
    assert "traversable" in text


def test_traversal_whitelist_is_default_deny():
    """Annotation/inferred relations are outside the traversable set."""
    assert "RATIONALE_FOR" not in TRACE_TRAVERSABLE_RELATIONS
    # sanity: the documented preference order is whitelisted
    for kind in ("CALLS", "INHERITS", "IMPLEMENTS", "IMPORTS", "READS", "CONTAINS"):
        assert kind in TRACE_TRAVERSABLE_RELATIONS


def _append_rel(repo: Path, source_id: str, target_id: str, relation_type: str) -> None:
    """Rewrite the fixture's rels_views IPC with one extra edge row.

    Simulates a future annotation edge (RATIONALE_FOR) landing in the graph —
    the exact situation default-deny traversal exists for.
    """
    artifact = repo / ".batho" / "artifact"
    reader = BathoBundleReader(artifact)
    active = reader._manager.active_path("rels_views")
    table = reader._get_table("rels_views")
    # Clone an existing row so not-null columns (file_id, roles, ...) stay valid.
    row = dict(table.to_pylist()[-1])
    row.update(
        {"source_id": source_id, "target_id": target_id, "relation_type": relation_type}
    )
    columns = [
        pa.array(table.column(field.name).to_pylist() + [row[field.name]], type=field.type)
        for field in table.schema
    ]
    new_table = pa.Table.from_arrays(columns, schema=table.schema)
    with pa.OSFile(str(active), "wb") as sink:
        with pa_ipc.new_file(sink, table.schema) as writer:
            writer.write_table(new_table)


@pytest.mark.asyncio
async def test_injected_non_whitelisted_edge_never_shortens_path(
    tmp_path: Path, mcp_app: FastMCP
):
    """A direct RATIONALE_FOR hop a→c must not replace the 2-hop CALLS path."""
    repo = tmp_path / "inj_repo"
    repo.mkdir()
    (repo / "chain.py").write_text(
        "def a():\n    return b()\n\n"
        "def b():\n    return c()\n\n"
        "def c():\n    return 1\n",
        encoding="utf-8",
    )
    result = run_build(BuildOptions(root=repo))
    assert result.success, result.warnings

    reader = BathoBundleReader(repo / ".batho" / "artifact")
    a_id = _entity_id(reader, "a", "inj_repo")
    c_id = _entity_id(reader, "c", "inj_repo")
    _append_rel(repo, a_id, c_id, "RATIONALE_FOR")

    await _register(mcp_app, repo)
    res = await _trace(mcp_app, repo, a_id, c_id)
    assert not res.is_error, res.content
    sc = res.structured_content
    assert sc["depth"] == 2
    assert sc["meta"]["edge_priority"]["path_edge_kinds"] == ["CALLS", "CALLS"]
    excluded = sc["meta"]["edge_priority"].get("excluded_edge_kinds", {})
    assert excluded.get("RATIONALE_FOR") == 1


@pytest.mark.asyncio
async def test_legacy_inverse_edge_traverses_as_forward(
    tmp_path: Path, mcp_app: FastMCP
):
    """MCP-01: a stored CALLED_BY row must survive the T6 trav_mask and
    normalize to a CALLS hop — pre-fix the whitelist filter dropped legacy
    inverse types before normalize_legacy_rel_rows could swap endpoints."""
    repo = tmp_path / "legacy_repo"
    repo.mkdir()
    (repo / "chain.py").write_text(
        "def a():\n    return b()\n\n"
        "def b():\n    return 1\n\n"
        "def d():\n    return 2\n",
        encoding="utf-8",
    )
    result = run_build(BuildOptions(root=repo))
    assert result.success, result.warnings

    reader = BathoBundleReader(repo / ".batho" / "artifact")
    a_id = _entity_id(reader, "a", "legacy_repo")
    d_id = _entity_id(reader, "d", "legacy_repo")
    # Stored as "d CALLED_BY a" — normalizes to CALLS a→d (endpoints swap).
    _append_rel(repo, d_id, a_id, "CALLED_BY")

    await _register(mcp_app, repo)
    res = await _trace(mcp_app, repo, a_id, d_id)
    assert not res.is_error, res.content
    sc = res.structured_content
    assert sc["depth"] == 1
    assert sc["meta"]["edge_priority"]["path_edge_kinds"] == ["CALLS"]
    excluded = sc["meta"]["edge_priority"].get("excluded_edge_kinds", {})
    assert "CALLED_BY" not in excluded
