"""Tests for batho_build MCP tool."""

from pathlib import Path

import pytest
from fastmcp import FastMCP

from batho.mcp.registry import RepoRegistry
from batho.mcp.server import create_app


@pytest.fixture
def repo_dir(tmp_path: Path) -> Path:
    repo = tmp_path / "sample_repo"
    repo.mkdir()
    py_file = repo / "main.py"
    py_file.write_text("def hello(): return 'world'\n", encoding="utf-8")
    return repo


@pytest.fixture
def registry(tmp_path: Path) -> RepoRegistry:
    cfg = tmp_path / "mcp-repos.json"
    return RepoRegistry(config_path=cfg)


@pytest.mark.asyncio
async def test_build_success(repo_dir: Path, registry: RepoRegistry):
    registry.add("my_repo", str(repo_dir))
    app = create_app(registry_path=registry.config_path)

    res = await app.call_tool("batho_build", {"repo": "my_repo"})
    assert not res.is_error
    assert res.structured_content["success"] is True
    assert res.structured_content["entity_count"] > 0


@pytest.mark.asyncio
async def test_build_already_built(repo_dir: Path, registry: RepoRegistry):
    registry.add("my_repo", str(repo_dir))
    app = create_app(registry_path=registry.config_path)

    # First build
    res1 = await app.call_tool("batho_build", {"repo": "my_repo"})
    assert not res1.is_error

    # Second build without full=True
    res2 = await app.call_tool("batho_build", {"repo": "my_repo"})
    assert not res2.is_error
    assert "already has an artifact" in res2.content[0].text


@pytest.mark.asyncio
async def test_build_full_flag(repo_dir: Path, registry: RepoRegistry):
    registry.add("my_repo", str(repo_dir))
    app = create_app(registry_path=registry.config_path)

    await app.call_tool("batho_build", {"repo": "my_repo"})
    res = await app.call_tool("batho_build", {"repo": "my_repo", "full": True})
    assert not res.is_error
    assert res.structured_content["success"] is True
