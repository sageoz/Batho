"""Tests for batho_load MCP tool."""

from pathlib import Path

import pytest
from fastmcp import FastMCP

from batho.mcp.registry import RepoRegistry
from batho.mcp.server import create_app
from batho.orchestrator.build import run_build, BuildOptions
from batho.orchestrator.export import run_export, ExportOptions


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
async def test_load_success(repo_dir: Path, registry: RepoRegistry, tmp_path: Path):
    target_repo = tmp_path / "target_repo"
    target_repo.mkdir()
    # Place the ZIP inside the target repo root (path containment).
    zip_path = target_repo / "artifact.zip"
    run_export(ExportOptions(root=repo_dir, pack=True, output=zip_path))

    registry.add("target", str(target_repo))
    app = create_app(registry_path=registry.config_path)

    res = await app.call_tool("batho_load", {"repo": "target", "artifact_path": "artifact.zip", "force": True})
    assert not res.is_error
    assert res.structured_content["success"] is True


@pytest.mark.asyncio
async def test_load_no_file(repo_dir: Path, registry: RepoRegistry):
    registry.add("my_repo", str(repo_dir))
    app = create_app(registry_path=registry.config_path)

    res = await app.call_tool("batho_load", {"repo": "my_repo", "artifact_path": "nonexistent.zip"})
    assert res.is_error
    assert "not found" in res.content[0].text


@pytest.mark.asyncio
async def test_load_rejects_path_outside_repo(repo_dir: Path, registry: RepoRegistry, tmp_path: Path):
    """artifact_path outside the repo root must be rejected (path containment)."""
    registry.add("my_repo", str(repo_dir))
    app = create_app(registry_path=registry.config_path)
    outside = tmp_path / "escape.zip"

    res = await app.call_tool("batho_load", {"repo": "my_repo", "artifact_path": str(outside)})
    assert res.is_error
    assert "Artifact path rejected" in res.content[0].text or "traversal" in res.content[0].text.lower()
