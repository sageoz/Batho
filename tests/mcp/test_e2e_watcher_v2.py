"""E2E tests for watcher v2 git sentinel mode — real git, real patch."""

from pathlib import Path
import shutil
import subprocess
import time

import pytest
from fastmcp import FastMCP

from batho.mcp.registry import RepoRegistry
from batho.mcp.server import create_app
from batho.mcp.watcher import BathoWatcherEngine
from batho.modules.graph.incremental import resolve_git_dir
from batho.orchestrator.build import run_build, BuildOptions


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    if shutil.which("git") is None:
        pytest.skip("git not installed")
    repo = tmp_path / "git_repo"
    repo.mkdir()
    (repo / "main.py").write_text("def initial(): return 1\n", encoding="utf-8")
    run_build(BuildOptions(root=repo))
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@batho.dev")
    _git(repo, "config", "user.name", "Batho Test")
    _git(repo, "add", "main.py")
    _git(repo, "commit", "-m", "init")
    if resolve_git_dir(repo) is None:
        pytest.skip("git not reachable via batho's restricted PATH")
    return repo


@pytest.fixture
def registry(tmp_path: Path) -> RepoRegistry:
    return RepoRegistry(config_path=tmp_path / "mcp-repos.json")


def _wait_for_flush(watcher: BathoWatcherEngine, repo: str, timeout: float = 10.0) -> bool:
    """True once a boundary-triggered patch has *completed*.

    sync_state can read "pending" while a patch is mid-flight (a late worktree
    event re-pends during patching), so completion is tracked by the
    monotonic patch_runs counter instead.
    """
    start = time.time()
    while time.time() - start < timeout:
        st = watcher.status().get(repo, {})
        if st.get("last_flush_reason") == "boundary" and st.get("patch_runs", 0) >= 1:
            return True
        time.sleep(0.1)
    return False


@pytest.mark.asyncio
async def test_e2e_git_add_triggers_patch(git_repo: Path, registry: RepoRegistry):
    """A real `git add` writes .git/index → sentinel boundary → auto-patch."""
    registry.add("grepo", str(git_repo), watch=True, debounce_ms=10_000)
    watcher = BathoWatcherEngine(registry)
    watcher.start()
    app = create_app(registry_path=registry.config_path, watcher=watcher)
    try:
        watch = watcher._watches["grepo"]
        assert watch.mode == "git"
        # Edit + stage — the index write is the boundary signal; debounce is
        # huge so only the sentinel settle path can flush.
        (git_repo / "main.py").write_text(
            "def initial(): return 1\ndef staged_func(): return 2\n", encoding="utf-8"
        )
        _git(git_repo, "add", "main.py")
        assert _wait_for_flush(watcher, "grepo"), "boundary flush never fired"
        res = await app.call_tool("search_entities", {"repo": "grepo", "query": "staged_func"})
        assert not res.is_error
        assert "staged_func" in res.content[0].text
    finally:
        watcher.stop()


@pytest.mark.asyncio
async def test_e2e_git_checkout_branch_boundary(git_repo: Path, registry: RepoRegistry):
    """`git checkout -b` writes HEAD → boundary flush."""
    registry.add("grepo", str(git_repo), watch=True, debounce_ms=10_000)
    watcher = BathoWatcherEngine(registry)
    watcher.start()
    try:
        watcher.start()  # idempotent re-entry covered by unwatch-on-rewatch
        watch = watcher._watches["grepo"]
        assert watch.mode == "git"
        _git(git_repo, "checkout", "-b", "feature-x")
        assert _wait_for_flush(watcher, "grepo"), "boundary flush never fired"
    finally:
        watcher.stop()


@pytest.mark.asyncio
async def test_e2e_gc_noise_no_flush(git_repo: Path, registry: RepoRegistry):
    """objects/ churn is never watched → zero boundary flushes."""
    registry.add("grepo", str(git_repo), watch=True, debounce_ms=10_000)
    watcher = BathoWatcherEngine(registry)
    watcher.start()
    try:
        watch = watcher._watches["grepo"]
        assert watch.mode == "git"
        # Synthesize objects/ writes directly — gc also prunes refs (a real
        # boundary), so the noise test uses pure object traffic.
        obj_dir = watch.git_dir / "objects" / "ab"
        obj_dir.mkdir(parents=True, exist_ok=True)
        (obj_dir / "cdef0123456789").write_text("blob")
        (watch.git_dir / "objects" / "pack" / "pack-test.idx").write_text("idx")
        time.sleep(1.0)  # well past git_settle_ms
        assert watcher.status()["grepo"].get("last_flush_reason") != "boundary"
        assert watch.boundary_pending is False
    finally:
        watcher.stop()
