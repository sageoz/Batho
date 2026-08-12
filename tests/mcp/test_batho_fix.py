"""Tests for batho_fix MCP tool."""

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
    run_build(BuildOptions(root=repo))
    return repo


@pytest.fixture
def registry(tmp_path: Path) -> RepoRegistry:
    cfg = tmp_path / "mcp-repos.json"
    return RepoRegistry(config_path=cfg)


@pytest.mark.asyncio
async def test_fix_dry_run(repo_dir: Path, registry: RepoRegistry):
    registry.add("my_repo", str(repo_dir))
    app = create_app(registry_path=registry.config_path)

    res = await app.call_tool("batho_fix", {"repo": "my_repo", "dry_run": True})
    assert not res.is_error
    assert res.structured_content["success"] is True
    assert res.structured_content["dry_run"] is True


@pytest.mark.asyncio
async def test_fix_no_bundle(tmp_path: Path, registry: RepoRegistry):
    empty_dir = tmp_path / "empty_repo"
    empty_dir.mkdir()
    registry.add("empty", str(empty_dir))
    app = create_app(registry_path=registry.config_path)

    res = await app.call_tool("batho_fix", {"repo": "empty"})
    assert res.is_error
    assert "No artifact bundle found" in res.content[0].text
