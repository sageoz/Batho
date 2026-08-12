"""Tests for add_repo MCP tool with watch parameters."""

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
    py_file.write_text("def main(): pass\n", encoding="utf-8")
    return repo


@pytest.fixture
def repo_with_artifact(repo_dir: Path) -> Path:
    run_build(BuildOptions(root=repo_dir))
    return repo_dir


@pytest.fixture
def mcp_app(tmp_path: Path) -> FastMCP:
    cfg = tmp_path / "mcp-repos.json"
    return create_app(registry_path=cfg)


@pytest.mark.asyncio
async def test_add_repo_with_watch_true(mcp_app: FastMCP, repo_with_artifact: Path):
    res = await mcp_app.call_tool(
        "add_repo",
        {
            "name": "watched_repo",
            "path": str(repo_with_artifact),
            "watch": True,
            "debounce_ms": 1500,
        },
    )
    assert not res.is_error
    assert res.structured_content["watch"] is True
    assert res.structured_content["debounce_ms"] == 1500


@pytest.mark.asyncio
async def test_add_repo_watch_no_artifact(mcp_app: FastMCP, repo_dir: Path):
    res = await mcp_app.call_tool(
        "add_repo",
        {
            "name": "unbuilt_repo",
            "path": str(repo_dir),
            "watch": True,
        },
    )
    assert res.is_error
    assert "No Batho artifact found" in res.content[0].text or "Cannot watch repo without an artifact" in res.content[0].text


@pytest.mark.asyncio
async def test_add_repo_watch_false_default(mcp_app: FastMCP, repo_with_artifact: Path):
    res = await mcp_app.call_tool(
        "add_repo",
        {
            "name": "default_watch_repo",
            "path": str(repo_with_artifact),
        },
    )
    assert not res.is_error
    assert res.structured_content["watch"] is False
    assert res.structured_content["debounce_ms"] == 2000
