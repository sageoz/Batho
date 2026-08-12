"""Tests for batho_status MCP tool."""

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
def repo_with_artifact(repo_dir: Path) -> Path:
    run_build(BuildOptions(root=repo_dir))
    return repo_dir


@pytest.fixture
def registry(tmp_path: Path) -> RepoRegistry:
    cfg = tmp_path / "mcp-repos.json"
    return RepoRegistry(config_path=cfg)


@pytest.mark.asyncio
async def test_status_single_repo(tmp_path: Path, repo_with_artifact: Path, registry: RepoRegistry):
    registry.add("repo_a", str(repo_with_artifact), watch=True)
    app = create_app(registry_path=registry.config_path)

    res = await app.call_tool("batho_status", {"repo": "repo_a"})
    assert not res.is_error
    assert res.structured_content["total"] == 1
    item = res.structured_content["repos"][0]
    assert item["repo"] == "repo_a"
    assert item["has_artifact"] is True
    assert item["run_count"] > 0
    assert item["watching"] is True
    assert item["sync_state"] == "idle"


@pytest.mark.asyncio
async def test_status_all_repos(tmp_path: Path, repo_with_artifact: Path, registry: RepoRegistry):
    registry.add("repo_a", str(repo_with_artifact), watch=True)
    registry.add("repo_b", str(repo_with_artifact), watch=False)
    app = create_app(registry_path=registry.config_path)

    res = await app.call_tool("batho_status", {})
    assert not res.is_error
    assert res.structured_content["total"] == 2


@pytest.mark.asyncio
async def test_status_no_artifact(tmp_path: Path, repo_dir: Path, registry: RepoRegistry):
    registry.add("unbuilt", str(repo_dir))
    app = create_app(registry_path=registry.config_path)

    res = await app.call_tool("batho_status", {"repo": "unbuilt"})
    assert not res.is_error
    item = res.structured_content["repos"][0]
    assert item["repo"] == "unbuilt"
    assert item["has_artifact"] is False
    assert item["run_count"] == 0
