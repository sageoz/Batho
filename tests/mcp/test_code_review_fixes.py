"""Regression tests for MCP code review fixes."""

from pathlib import Path
import pytest
from fastmcp import FastMCP, Client
from fastmcp.tools.tool import ToolResult

from batho.orchestrator.build import run_build, BuildOptions
from batho.orchestrator.patch import run_patch, PatchOptions
from batho.modules.storage.arrow_bundle import BathoBundle
from batho.modules.storage.arrow_bundle.reader import BathoBundleReader
from batho.mcp.registry import RepoRegistry
from batho.mcp.server import create_app
from batho.mcp.tools import _manifest_gen, _resolve_root_path


@pytest.fixture
def repo_dir(tmp_path: Path) -> Path:
    repo = tmp_path / "sample_repo"
    repo.mkdir()
    py_file = repo / "main.py"
    py_file.write_text("def hello(): pass\n", encoding="utf-8")
    run_build(BuildOptions(root=repo))
    return repo


def test_manifest_gen_returns_positive_generation(repo_dir: Path):
    reader = BathoBundleReader(repo_dir / ".batho" / "artifact")
    gen = _manifest_gen(reader)
    assert gen > 0


@pytest.mark.asyncio
async def test_batho_diff_since_filters_history(repo_dir: Path, tmp_path: Path):
    repo_dir = repo_dir.resolve()
    py_file = repo_dir / "main.py"

    
    # Patch 1: Add func2
    py_file.write_text("def hello(): pass\ndef func2(a): return a\n", encoding="utf-8")
    patch_res1 = run_patch(PatchOptions(root=repo_dir))
    run_id1 = patch_res1.run_id

    # Patch 2: Add func3
    py_file.write_text("def hello(): pass\ndef func2(a, b): return a + b\ndef func3(): pass\n", encoding="utf-8")
    patch_res2 = run_patch(PatchOptions(root=repo_dir))
    run_id2 = patch_res2.run_id

    reader = BathoBundleReader(repo_dir / ".batho" / "artifact")
    db = BathoBundle(repo_dir)


    changelog = reader._get_table("file_changelog").to_pylist()
    assert len(changelog) >= 2

    # Get an entity that changed in patch 1
    func2_id = [c.get("entity_id") for c in changelog if "func2" in c.get("entity_name", "")][0]

    all_history = db.get_file_node_history(func2_id)
    assert len(all_history) >= 1

    # Filter since run_id2
    since2_history = db.get_file_node_history(func2_id, since_run_uuid=run_id2)
    assert all(h.get("run_uuid") == run_id2 for h in since2_history)




@pytest.mark.asyncio
async def test_batho_export_valid_and_invalid_views(repo_dir: Path, tmp_path: Path):
    reg_path = tmp_path / "mcp-repos.json"
    registry = RepoRegistry(config_path=reg_path)
    registry.add("sample", str(repo_dir))

    app = create_app(registry_path=reg_path)

    # Valid view: overview
    res_overview = await app.call_tool("batho_export", {"repo": "sample", "view": "overview"})
    assert not res_overview.is_error

    # Valid view: files
    res_files = await app.call_tool("batho_export", {"repo": "sample", "view": "files"})
    assert not res_files.is_error

    # Invalid view: invalid_view_name
    res_invalid = await app.call_tool("batho_export", {"repo": "sample", "view": "invalid_view_name"})
    assert res_invalid.is_error
    assert "Invalid view" in res_invalid.content[0].text


def test_resolve_root_path_rejects_unregistered_repo(tmp_path: Path):
    reg_path = tmp_path / "mcp-repos.json"
    registry = RepoRegistry(config_path=reg_path)
    registry.add("sample", str(tmp_path / "sample"))

    # Attempting to resolve unregistered path/name when registry exists should raise ValueError
    with pytest.raises(ValueError, match="is not registered"):
        _resolve_root_path("unregistered_repo", None, registry)
