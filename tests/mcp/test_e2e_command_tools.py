"""End-to-end integration tests for command-as-tools."""

from pathlib import Path

import pytest
from fastmcp import FastMCP

from batho.mcp.registry import RepoRegistry
from batho.mcp.server import create_app


@pytest.fixture
def repo_dir(tmp_path: Path) -> Path:
    repo = tmp_path / "e2e_cmd_repo"
    repo.mkdir()
    py_file = repo / "app.py"
    py_file.write_text("def start(): return 'ok'\n", encoding="utf-8")
    return repo


@pytest.fixture
def registry(tmp_path: Path) -> RepoRegistry:
    cfg = tmp_path / "mcp-repos.json"
    return RepoRegistry(config_path=cfg)


@pytest.mark.asyncio
async def test_e2e_build_then_query(repo_dir: Path, registry: RepoRegistry):
    registry.add("cmd_repo", str(repo_dir))
    app = create_app(registry_path=registry.config_path, disabled_tools=set())

    build_res = await app.call_tool("batho_build", {"repo": "cmd_repo"})
    assert not build_res.is_error
    assert build_res.structured_content["entity_count"] > 0

    query_res = await app.call_tool("graph_overview", {"repo": "cmd_repo"})
    assert not query_res.is_error
    assert query_res.structured_content["overview"]["stats"]["total_entities"] > 0


@pytest.mark.asyncio
async def test_e2e_patch_then_delta(repo_dir: Path, registry: RepoRegistry):
    registry.add("cmd_repo", str(repo_dir))
    app = create_app(registry_path=registry.config_path, disabled_tools=set())

    await app.call_tool("batho_build", {"repo": "cmd_repo"})

    # Modify file
    (repo_dir / "app.py").write_text("def start(): return 'ok'\ndef stop(): pass\n", encoding="utf-8")

    patch_res = await app.call_tool("batho_patch", {"repo": "cmd_repo"})
    assert not patch_res.is_error
    assert patch_res.structured_content["changes_applied"] > 0

    delta_res = await app.call_tool("get_delta", {"repo": "cmd_repo"})
    assert not delta_res.is_error


@pytest.mark.asyncio
async def test_e2e_export_then_load(repo_dir: Path, registry: RepoRegistry, tmp_path: Path):
    registry.add("source_repo", str(repo_dir))
    dest_repo = tmp_path / "dest_repo"
    dest_repo.mkdir()
    registry.add("dest_repo", str(dest_repo))

    app = create_app(registry_path=registry.config_path, disabled_tools=set())

    await app.call_tool("batho_build", {"repo": "source_repo"})

    # Export writes into the source repo root (path containment); load reads
    # from the dest repo root. To move the artifact between repos we copy it
    # via the filesystem, then load it by its relative path under dest_repo.
    export_res = await app.call_tool("batho_export", {"repo": "source_repo", "json_mode": False, "output": "exported.zip"})
    assert not export_res.is_error

    import shutil
    shutil.copy(repo_dir / "exported.zip", dest_repo / "exported.zip")

    load_res = await app.call_tool("batho_load", {"repo": "dest_repo", "artifact_path": "exported.zip", "force": True})
    assert not load_res.is_error
    assert load_res.structured_content["success"] is True


@pytest.mark.asyncio
async def test_e2e_gc_status_after_build(repo_dir: Path, registry: RepoRegistry):
    registry.add("cmd_repo", str(repo_dir))
    app = create_app(registry_path=registry.config_path, disabled_tools=set())

    await app.call_tool("batho_build", {"repo": "cmd_repo"})

    gc_res = await app.call_tool("batho_gc", {"repo": "cmd_repo", "subcommand": "status"})
    assert not gc_res.is_error
    assert gc_res.structured_content["success"] is True


@pytest.mark.asyncio
async def test_e2e_fix_after_build(repo_dir: Path, registry: RepoRegistry):
    registry.add("cmd_repo", str(repo_dir))
    app = create_app(registry_path=registry.config_path, disabled_tools=set())

    await app.call_tool("batho_build", {"repo": "cmd_repo"})

    fix_res = await app.call_tool("batho_fix", {"repo": "cmd_repo", "dry_run": True})
    assert not fix_res.is_error
    assert fix_res.structured_content["success"] is True
