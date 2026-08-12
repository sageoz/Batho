"""Tests for batho_diff MCP tool."""

from pathlib import Path

import pytest
from fastmcp import FastMCP

from batho.mcp.registry import RepoRegistry
from batho.mcp.server import create_app
from batho.orchestrator.build import run_build, BuildOptions
from batho.orchestrator.patch import run_patch, PatchOptions


@pytest.fixture
def repo_dir(tmp_path: Path) -> Path:
    repo = tmp_path / "sample_repo"
    repo.mkdir()
    py_file = repo / "main.py"
    py_file.write_text("def hello(): pass\n", encoding="utf-8")
    run_build(BuildOptions(root=repo))
    return repo


@pytest.fixture
def registry(tmp_path: Path) -> RepoRegistry:
    cfg = tmp_path / "mcp-repos.json"
    return RepoRegistry(config_path=cfg)


@pytest.mark.asyncio
async def test_diff_by_run(repo_dir: Path, registry: RepoRegistry):
    # Apply patch
    (repo_dir / "main.py").write_text("def hello(): return 1\n", encoding="utf-8")
    patch_res = run_patch(PatchOptions(root=repo_dir))
    run_id = patch_res.run_id


    registry.add("my_repo", str(repo_dir))
    app = create_app(registry_path=registry.config_path)

    res = await app.call_tool("batho_diff", {"repo": "my_repo", "run_id": run_id})
    assert not res.is_error
    assert res.structured_content["run_id"] == run_id


@pytest.mark.asyncio
async def test_diff_by_file(repo_dir: Path, registry: RepoRegistry):
    (repo_dir / "main.py").write_text("def hello(): return 2\n", encoding="utf-8")
    run_patch(PatchOptions(root=repo_dir))

    registry.add("my_repo", str(repo_dir))
    app = create_app(registry_path=registry.config_path)

    res = await app.call_tool("batho_diff", {"repo": "my_repo", "file_path": "main.py"})
    assert not res.is_error
    assert res.structured_content["file_path"] == "main.py"


@pytest.mark.asyncio
async def test_diff_mutually_exclusive(repo_dir: Path, registry: RepoRegistry):
    registry.add("my_repo", str(repo_dir))
    app = create_app(registry_path=registry.config_path)

    res = await app.call_tool("batho_diff", {"repo": "my_repo", "run_id": "r1", "file_path": "main.py"})
    assert res.is_error
    assert "exactly ONE" in res.content[0].text


@pytest.mark.asyncio
async def test_diff_since_without_entity(repo_dir: Path, registry: RepoRegistry):
    registry.add("my_repo", str(repo_dir))
    app = create_app(registry_path=registry.config_path)

    res = await app.call_tool("batho_diff", {"repo": "my_repo", "file_path": "main.py", "since": "r1"})
    assert res.is_error
    assert "only be used with 'entity_id'" in res.content[0].text
