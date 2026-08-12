"""End-to-end integration tests for Batho watcher engine."""

from pathlib import Path
import time

import pytest
from fastmcp import FastMCP

from batho.mcp.registry import RepoRegistry
from batho.mcp.server import create_app
from batho.mcp.watcher import BathoWatcherEngine
from batho.orchestrator.build import run_build, BuildOptions


@pytest.fixture
def repo_dir(tmp_path: Path) -> Path:
    repo = tmp_path / "e2e_repo"
    repo.mkdir()
    py_file = repo / "main.py"
    py_file.write_text("def initial_func(): return 1\n", encoding="utf-8")
    run_build(BuildOptions(root=repo))
    return repo


@pytest.fixture
def registry(tmp_path: Path) -> RepoRegistry:
    cfg = tmp_path / "mcp-repos.json"
    return RepoRegistry(config_path=cfg)


@pytest.mark.asyncio
async def test_e2e_watcher_auto_patch(repo_dir: Path, registry: RepoRegistry):
    entry = registry.add("e2e_repo", str(repo_dir), watch=True, debounce_ms=150)
    watcher = BathoWatcherEngine(registry)
    watcher.start()
    app = create_app(registry_path=registry.config_path, watcher=watcher)

    try:
        # Initial overview
        res1 = await app.call_tool("graph_overview", {"repo": "e2e_repo"})
        assert not res1.is_error

        # Add new function to file
        (repo_dir / "main.py").write_text("def initial_func(): return 1\ndef added_func(): return 2\n", encoding="utf-8")

        # Wait for watcher debounce & auto-patch to start & complete
        time.sleep(0.15)
        start_t = time.time()
        while time.time() - start_t < 5.0:
            status = watcher.status().get("e2e_repo", {})
            if status.get("sync_state") == "idle" and "added_func" not in status.get("pending_files", []):
                break
            time.sleep(0.1)


        # Overview after auto-patch should reflect new entity
        res2 = await app.call_tool("search_entities", {"repo": "e2e_repo", "query": "added_func"})
        assert not res2.is_error
        assert "added_func" in res2.content[0].text

    finally:
        watcher.stop()


@pytest.mark.asyncio
async def test_e2e_watcher_staleness_banner(repo_dir: Path, registry: RepoRegistry):
    entry = registry.add("e2e_repo", str(repo_dir), watch=True, debounce_ms=2000)
    watcher = BathoWatcherEngine(registry)
    watcher.start()
    app = create_app(registry_path=registry.config_path, watcher=watcher)

    try:
        # Modify file to trigger pending state
        (repo_dir / "main.py").write_text("def modified_func(): return 3\n", encoding="utf-8")
        watcher._on_change("e2e_repo", "main.py", repo_dir / "main.py")

        res = await app.call_tool("graph_overview", {"repo": "e2e_repo"})
        assert not res.is_error
        assert "pending re-index" in res.content[0].text
    finally:
        watcher.stop()


@pytest.mark.asyncio
async def test_e2e_watcher_catch_up(repo_dir: Path, registry: RepoRegistry):
    entry = registry.add("e2e_repo", str(repo_dir), watch=True)

    # Modify file while watcher is not running
    (repo_dir / "main.py").write_text("def catchup_func(): return 4\n", encoding="utf-8")

    watcher = BathoWatcherEngine(registry)
    watcher.start()
    watcher.catch_up("e2e_repo")
    app = create_app(registry_path=registry.config_path, watcher=watcher)

    try:
        res = await app.call_tool("search_entities", {"repo": "e2e_repo", "query": "catchup_func"})
        assert not res.is_error
        assert "catchup_func" in res.content[0].text
    finally:
        watcher.stop()


@pytest.mark.asyncio
async def test_e2e_watcher_ignore_batho_dir(repo_dir: Path, registry: RepoRegistry):
    entry = registry.add("e2e_repo", str(repo_dir), watch=True, debounce_ms=100)
    watcher = BathoWatcherEngine(registry)
    watcher.start()
    try:
        batho_file = repo_dir / ".batho" / "artifact" / "meta.json"
        watcher._on_change("e2e_repo", ".batho/artifact/meta.json", batho_file)
        assert not watcher.is_pending("e2e_repo", ".batho/artifact/meta.json")
    finally:
        watcher.stop()


@pytest.mark.asyncio
async def test_e2e_watcher_stop_cleanup(repo_dir: Path, registry: RepoRegistry):
    entry = registry.add("e2e_repo", str(repo_dir), watch=True)
    watcher = BathoWatcherEngine(registry)
    watcher.start()
    assert len(watcher._watches) == 1
    watcher.stop()
    assert len(watcher._watches) == 0


@pytest.mark.asyncio
async def test_e2e_add_repo_with_watch(repo_dir: Path, registry: RepoRegistry):
    watcher = BathoWatcherEngine(registry)
    watcher.start()
    app = create_app(registry_path=registry.config_path, watcher=watcher)

    try:
        res = await app.call_tool("add_repo", {"name": "dynamic_repo", "path": str(repo_dir), "watch": True, "debounce_ms": 500})
        assert not res.is_error
        assert "dynamic_repo" in watcher._watches
    finally:
        watcher.stop()
