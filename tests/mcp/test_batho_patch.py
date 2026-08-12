"""Tests for batho_patch MCP tool."""

from pathlib import Path

import pytest
from fastmcp import FastMCP

from batho.mcp.registry import RepoRegistry
from batho.mcp.server import create_app
from batho.orchestrator.build import run_build, BuildOptions


@pytest.fixture
def repo_dir(tmp_path: Path) -> Path:
    repo = tmp_path / "sample_repo"
    repo.mkdir()
    py_file = repo / "main.py"
    py_file.write_text("def hello(): pass\n", encoding="utf-8")
    return repo


@pytest.fixture
def registry(tmp_path: Path) -> RepoRegistry:
    cfg = tmp_path / "mcp-repos.json"
    return RepoRegistry(config_path=cfg)


@pytest.mark.asyncio
async def test_patch_success(repo_dir: Path, registry: RepoRegistry):
    run_build(BuildOptions(root=repo_dir))
    registry.add("my_repo", str(repo_dir))
    app = create_app(registry_path=registry.config_path)

    # Modify file
    (repo_dir / "main.py").write_text("def hello(): return 42\n", encoding="utf-8")

    res = await app.call_tool("batho_patch", {"repo": "my_repo"})
    assert not res.is_error
    assert res.structured_content["success"] is True
    assert res.structured_content["changes_applied"] > 0


@pytest.mark.asyncio
async def test_patch_no_changes(repo_dir: Path, registry: RepoRegistry):
    run_build(BuildOptions(root=repo_dir))
    registry.add("my_repo", str(repo_dir))
    app = create_app(registry_path=registry.config_path)

    res = await app.call_tool("batho_patch", {"repo": "my_repo"})
    assert not res.is_error
    assert res.structured_content["changes_applied"] == 0


@pytest.mark.asyncio
async def test_patch_no_artifact(repo_dir: Path, registry: RepoRegistry):
    registry.add("unbuilt_repo", str(repo_dir))
    app = create_app(registry_path=registry.config_path)

    res = await app.call_tool("batho_patch", {"repo": "unbuilt_repo"})
    assert res.is_error
    assert "No artifact found" in res.content[0].text
