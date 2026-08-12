"""Unit tests for BathoWatcherEngine."""

from pathlib import Path
import time
from unittest.mock import MagicMock, patch

import pytest

from batho.mcp.registry import RepoRegistry, RepoEntry
from batho.mcp.watcher import BathoWatcherEngine, WatchEntry
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


def test_watch_starts_observer(repo_with_artifact: Path, registry: RepoRegistry):
    entry = registry.add("sample", str(repo_with_artifact), watch=True)
    engine = BathoWatcherEngine(registry)
    try:
        engine.start()
        status = engine.status()
        assert "sample" in status
        assert status["sample"]["watching"] is True
        assert status["sample"]["sync_state"] == "idle"
    finally:
        engine.stop()


def test_debounce_schedules_single_patch(repo_with_artifact: Path, registry: RepoRegistry):
    entry = registry.add("sample", str(repo_with_artifact), watch=True, debounce_ms=200)
    engine = BathoWatcherEngine(registry)
    patch_mock = MagicMock()

    with patch("batho.orchestrator.patch.run_patch", patch_mock), patch("batho.mcp.tools.invalidate_reader_pool"):
        try:
            engine.start()
            # Rapid file changes
            file1 = repo_with_artifact / "main.py"
            file1.write_text("def hello(): return 1\n", encoding="utf-8")
            engine._on_change("sample", "main.py", file1)
            engine._on_change("sample", "main.py", file1)

            assert engine.is_pending("sample", "main.py")
            # Wait for debounce window
            time.sleep(0.4)
            patch_mock.assert_called_once()
            assert not engine.is_pending("sample", "main.py")
        finally:
            engine.stop()


def test_ignore_patterns(repo_with_artifact: Path, registry: RepoRegistry):
    entry = registry.add("sample", str(repo_with_artifact), watch=True, debounce_ms=100)
    engine = BathoWatcherEngine(registry)
    try:
        engine.start()
        # Internal artifact path should be ignored
        batho_file = repo_with_artifact / ".batho" / "artifact" / "meta.json"
        engine._on_change("sample", ".batho/artifact/meta.json", batho_file)
        assert not engine.is_pending("sample", ".batho/artifact/meta.json")
    finally:
        engine.stop()


def test_patch_on_success_clears_pending(repo_with_artifact: Path, registry: RepoRegistry):
    entry = registry.add("sample", str(repo_with_artifact), watch=True, debounce_ms=100)
    engine = BathoWatcherEngine(registry)
    file1 = repo_with_artifact / "main.py"
    file1.write_text("def hello(): return 2\n", encoding="utf-8")

    with patch("batho.mcp.tools.invalidate_reader_pool") as inv_mock:
        try:
            engine.watch(entry)
            engine._watches["sample"].pending_files.add("main.py")
            engine._run_patch("sample")
            assert engine.status()["sample"]["sync_state"] == "idle"
            assert len(engine.status()["sample"]["pending_files"]) == 0
            inv_mock.assert_called_with("sample")
        finally:
            engine.stop()


def test_patch_on_failure_sets_error(repo_with_artifact: Path, registry: RepoRegistry):
    entry = registry.add("sample", str(repo_with_artifact), watch=True, debounce_ms=100)
    engine = BathoWatcherEngine(registry)
    file1 = repo_with_artifact / "main.py"

    with patch("batho.orchestrator.patch.run_patch", side_effect=RuntimeError("Patch error")):
        try:
            engine.watch(entry)
            engine._run_patch("sample")
            status = engine.status()["sample"]
            assert status["sync_state"] == "error"
            assert "Patch error" in status["error_message"]
        finally:
            engine.stop()




def test_catch_up_detects_changed_files(repo_with_artifact: Path, registry: RepoRegistry):
    entry = registry.add("sample", str(repo_with_artifact), watch=True)
    engine = BathoWatcherEngine(registry)

    # Modify file while watcher is down
    file1 = repo_with_artifact / "main.py"
    file1.write_text("def hello(): return 999\n", encoding="utf-8")

    with patch.object(engine, "_run_patch") as patch_mock:
        engine.catch_up("sample")
        patch_mock.assert_called_once_with("sample")


def test_staleness_banner_patching(repo_with_artifact: Path, registry: RepoRegistry):
    entry = registry.add("sample", str(repo_with_artifact), watch=True)
    engine = BathoWatcherEngine(registry)
    engine.watch(entry)
    try:
        engine._watches["sample"].sync_state = "patching"
        banner = engine.get_staleness_banner("sample")
        assert "currently being re-patched" in banner
    finally:
        engine.stop()


def test_staleness_banner_pending_file(repo_with_artifact: Path, registry: RepoRegistry):
    entry = registry.add("sample", str(repo_with_artifact), watch=True)
    engine = BathoWatcherEngine(registry)
    engine.watch(entry)
    try:
        engine._watches["sample"].pending_files.add("main.py")
        engine._watches["sample"].sync_state = "pending"
        banner = engine.get_staleness_banner("sample", file_path="main.py")
        assert "pending re-index" in banner
        assert "`main.py`" in banner
    finally:
        engine.stop()


def test_staleness_banner_idle(repo_with_artifact: Path, registry: RepoRegistry):
    entry = registry.add("sample", str(repo_with_artifact), watch=True)
    engine = BathoWatcherEngine(registry)
    engine.watch(entry)
    try:
        assert engine.get_staleness_banner("sample") is None
    finally:
        engine.stop()


def test_stop_cleans_up_observers(repo_with_artifact: Path, registry: RepoRegistry):
    entry = registry.add("sample", str(repo_with_artifact), watch=True)
    engine = BathoWatcherEngine(registry)
    engine.start()
    assert len(engine._watches) == 1
    engine.stop()
    assert len(engine._watches) == 0
