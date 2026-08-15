"""Tests for batho_gc MCP tool."""

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
async def test_gc_status(repo_dir: Path, registry: RepoRegistry):
    registry.add("my_repo", str(repo_dir))
    app = create_app(registry_path=registry.config_path, disabled_tools=set())

    res = await app.call_tool("batho_gc", {"repo": "my_repo", "subcommand": "status"})
    assert not res.is_error
    assert res.structured_content["success"] is True


@pytest.mark.asyncio
async def test_gc_vacuum(repo_dir: Path, registry: RepoRegistry):
    registry.add("my_repo", str(repo_dir))
    app = create_app(registry_path=registry.config_path, disabled_tools=set())

    res = await app.call_tool("batho_gc", {"repo": "my_repo", "subcommand": "vacuum"})
    assert not res.is_error


@pytest.mark.asyncio
async def test_gc_run_requires_uuid(repo_dir: Path, registry: RepoRegistry):
    registry.add("my_repo", str(repo_dir))
    app = create_app(registry_path=registry.config_path, disabled_tools=set())

    res = await app.call_tool("batho_gc", {"repo": "my_repo", "subcommand": "run"})
    assert res.is_error
    assert "requires run_uuid" in res.content[0].text


@pytest.mark.asyncio
async def test_gc_runs_requires_older_than(repo_dir: Path, registry: RepoRegistry):
    registry.add("my_repo", str(repo_dir))
    app = create_app(registry_path=registry.config_path, disabled_tools=set())

    res = await app.call_tool("batho_gc", {"repo": "my_repo", "subcommand": "runs"})
    assert res.is_error
    assert "requires older_than" in res.content[0].text
