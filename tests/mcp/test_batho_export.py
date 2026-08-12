"""Tests for batho_export MCP tool."""

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
async def test_export_json_storage_view(repo_dir: Path, registry: RepoRegistry, tmp_path: Path):
    registry.add("my_repo", str(repo_dir))
    app = create_app(registry_path=registry.config_path)
    # Output must be a relative path under the repo root (path containment).
    out_file = repo_dir / "export.json"

    res = await app.call_tool("batho_export", {"repo": "my_repo", "view": "storage", "output": "export.json"})
    assert not res.is_error
    assert out_file.exists()


@pytest.mark.asyncio
async def test_export_pack_mode(repo_dir: Path, registry: RepoRegistry, tmp_path: Path):
    registry.add("my_repo", str(repo_dir))
    app = create_app(registry_path=registry.config_path)
    # Output must be a relative path under the repo root (path containment).
    out_pack = repo_dir / "artifact.zip"

    res = await app.call_tool("batho_export", {"repo": "my_repo", "json_mode": False, "output": "artifact.zip"})
    assert not res.is_error
    assert out_pack.exists()


@pytest.mark.asyncio
async def test_export_rejects_path_outside_repo(repo_dir: Path, registry: RepoRegistry, tmp_path: Path):
    """Export output outside the repo root must be rejected (path containment)."""
    registry.add("my_repo", str(repo_dir))
    app = create_app(registry_path=registry.config_path)
    outside = tmp_path / "escape.json"

    res = await app.call_tool("batho_export", {"repo": "my_repo", "view": "storage", "output": str(outside)})
    assert res.is_error
    assert "Output path rejected" in res.content[0].text or "traversal" in res.content[0].text.lower()
