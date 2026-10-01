"""Unit tests for watcher v2: compound triggers, git sentinels, VCS-op hold."""

from pathlib import Path
import shutil
import subprocess
import time
from unittest.mock import MagicMock, patch

import pytest

from batho.core.config.loader import get_config_with_root
from batho.core.config.models import Config, WatchConfig
from batho.mcp import git_sentinel
from batho.mcp.registry import RepoRegistry
from batho.mcp.watcher import BathoWatcherEngine, _is_hidden_path
from batho.modules.graph.incremental import resolve_git_dir
from batho.orchestrator.build import run_build, BuildOptions


@pytest.fixture
def repo_dir(tmp_path: Path) -> Path:
    repo = tmp_path / "sample_repo"
    repo.mkdir()
    (repo / "main.py").write_text("def hello(): pass\n", encoding="utf-8")
    return repo


@pytest.fixture
def repo_with_artifact(repo_dir: Path) -> Path:
    run_build(BuildOptions(root=repo_dir))
    return repo_dir


@pytest.fixture
def git_repo(repo_with_artifact: Path) -> Path:
    if shutil.which("git") is None:
        pytest.skip("git not installed")
    subprocess.run(["git", "init"], cwd=repo_with_artifact, check=True, capture_output=True)
    if resolve_git_dir(repo_with_artifact) is None:
        pytest.skip("git not reachable via batho's restricted PATH")
    return repo_with_artifact


@pytest.fixture
def registry(tmp_path: Path) -> RepoRegistry:
    return RepoRegistry(config_path=tmp_path / "mcp-repos.json")


# ---------------------------------------------------------------------
# T01 — IndexerConfig dead-key restore
# ---------------------------------------------------------------------

def test_indexer_config_dead_keys_restored():
    cfg = Config()
    assert cfg.indexer.strict_hashing is False
    assert cfg.indexer.file_changelog_max_runs == 100
    cfg2 = Config.model_validate({"indexer": {"strict_hashing": True, "file_changelog_max_runs": 7}})
    assert cfg2.indexer.strict_hashing is True
    assert cfg2.indexer.file_changelog_max_runs == 7


def test_strict_hashing_env_override(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BATHO_STRICT_HASHING", "1")
    cfg = get_config_with_root(tmp_path)
    assert cfg["indexer"]["strict_hashing"] is True
    monkeypatch.delenv("BATHO_STRICT_HASHING")
    cfg = get_config_with_root(tmp_path)
    assert cfg["indexer"]["strict_hashing"] is False


# ---------------------------------------------------------------------
# T02 — WatchConfig schema + registry fields
# ---------------------------------------------------------------------

def test_watch_config_defaults_and_clamps():
    w = WatchConfig()
    assert w.mode == "auto"
    assert w.max_staleness_ms == 60_000
    assert w.flush_threshold == 300
    assert w.git_settle_ms == 300
    assert w.vcs_op_hold_ms == 30_000
    assert WatchConfig(max_staleness_ms=1).max_staleness_ms == 5_000
    assert WatchConfig(max_staleness_ms=10**9).max_staleness_ms == 600_000
    assert WatchConfig(flush_threshold=1).flush_threshold == 10
    # CFG-11: invalid mode raises (consistent with graph.backend.backend)
    # rather than silently coercing to "auto".
    with pytest.raises(Exception):
        WatchConfig(mode="bogus")


def test_registry_watch_fields_roundtrip(tmp_path: Path):
    reg = RepoRegistry(config_path=tmp_path / "mcp-repos.json")
    entry = reg.add(
        "r1", str(tmp_path),
        watch=True, watch_mode="fs",
        max_staleness_ms=15_000, flush_threshold=50,
    )
    assert entry.watch_mode == "fs"
    loaded = {e.name: e for e in RepoRegistry(config_path=tmp_path / "mcp-repos.json").load()}["r1"]
    assert loaded.watch_mode == "fs"
    assert loaded.max_staleness_ms == 15_000
    assert loaded.flush_threshold == 50
    # invalid mode coerces
    assert reg.add("r2", str(tmp_path), watch_mode="bogus").watch_mode == "auto"


def test_registry_legacy_file_defaults(tmp_path: Path):
    cfg = tmp_path / "mcp-repos.json"
    cfg.write_text(
        '{"version": 3, "repos": [{"name": "old", "path": "%s", "watch": true}]}' % tmp_path
    )
    entry = RepoRegistry(config_path=cfg).load()[0]
    assert entry.watch_mode == "auto"
    assert entry.max_staleness_ms is None
    assert entry.flush_threshold is None


# ---------------------------------------------------------------------
# T04 — pre-lock hidden filter
# ---------------------------------------------------------------------

def test_is_hidden_path():
    assert _is_hidden_path(".git/objects/ab/cd")
    assert _is_hidden_path(".env")
    assert _is_hidden_path("a/.hidden/b.py")
    assert not _is_hidden_path("src/app.py")


def test_prelock_hidden_filter(repo_with_artifact: Path, registry: RepoRegistry):
    registry.add("sample", str(repo_with_artifact), watch=True)
    engine = BathoWatcherEngine(registry)
    try:
        engine.start()
        with patch("batho.mcp.watcher.should_ignore_path") as spec_spy:
            for i in range(20):
                engine._on_change(
                    "sample",
                    f".git/objects/ab/{i}",
                    repo_with_artifact / ".git" / "objects" / "ab" / str(i),
                )
            spec_spy.assert_not_called()
        assert not engine._watches["sample"].pending_files
    finally:
        engine.stop()


# ---------------------------------------------------------------------
# T05 — anomaly → patch
# ---------------------------------------------------------------------

def test_anomaly_schedules_patch(repo_with_artifact: Path, registry: RepoRegistry):
    registry.add("sample", str(repo_with_artifact), watch=True, debounce_ms=100)
    engine = BathoWatcherEngine(registry)
    patch_mock = MagicMock()
    with patch("batho.orchestrator.patch.run_patch", patch_mock), patch("batho.mcp.tools.invalidate_reader_pool"):
        try:
            engine.start()
            engine._on_anomaly("sample")
            assert engine._watches["sample"].dirty is True
            time.sleep(0.3)
            patch_mock.assert_called_once()
            assert patch_mock.call_args.kwargs == {}  # called via run_patch(options)
            assert engine._watches["sample"].dirty is False
            assert engine.status()["sample"]["sync_state"] == "idle"
        finally:
            engine.stop()


def test_anomaly_storm_coalesces(repo_with_artifact: Path, registry: RepoRegistry):
    registry.add("sample", str(repo_with_artifact), watch=True, debounce_ms=100)
    engine = BathoWatcherEngine(registry)
    patch_mock = MagicMock()
    with patch("batho.orchestrator.patch.run_patch", patch_mock), patch("batho.mcp.tools.invalidate_reader_pool"):
        try:
            engine.start()
            for _ in range(10):
                engine._on_anomaly("sample")
            time.sleep(0.4)
            assert patch_mock.call_count <= 2
        finally:
            engine.stop()


# ---------------------------------------------------------------------
# T06 — compound flush trigger
# ---------------------------------------------------------------------

def test_staleness_bound_fires_under_continuous_churn(repo_with_artifact: Path, registry: RepoRegistry):
    """Events arriving faster than debounce must still flush within max_staleness_ms."""
    registry.add("sample", str(repo_with_artifact), watch=True, debounce_ms=200)
    engine = BathoWatcherEngine(registry)
    patch_mock = MagicMock()
    with patch("batho.orchestrator.patch.run_patch", patch_mock), patch("batho.mcp.tools.invalidate_reader_pool"):
        try:
            engine.start()
            watch = engine._watches["sample"]
            watch.max_staleness_ms = 400  # below the config clamp floor; test-only
            f = repo_with_artifact / "main.py"
            deadline = time.time() + 0.9
            while time.time() < deadline:
                f.write_text(f"def hello(): return {time.time()}\n", encoding="utf-8")
                engine._on_change("sample", "main.py", f)
                time.sleep(0.1)  # faster than the 200ms debounce window
            patch_mock.assert_called()
            assert engine._watches["sample"].last_flush_reason in ("staleness", "debounce")
        finally:
            engine.stop()


def test_threshold_flush_immediate(repo_with_artifact: Path, registry: RepoRegistry):
    registry.add("sample", str(repo_with_artifact), watch=True, debounce_ms=10_000)
    engine = BathoWatcherEngine(registry)
    patch_mock = MagicMock()
    with patch("batho.orchestrator.patch.run_patch", patch_mock), patch("batho.mcp.tools.invalidate_reader_pool"):
        try:
            engine.start()
            watch = engine._watches["sample"]
            watch.flush_threshold = 3
            for i in range(3):
                p = repo_with_artifact / f"f{i}.py"
                p.write_text("x = 1\n", encoding="utf-8")
                engine._on_change("sample", f"f{i}.py", p)
            time.sleep(0.3)  # Timer(0) needs a moment to fire
            patch_mock.assert_called()
        finally:
            engine.stop()


def test_mode_off_tracks_but_never_patches(repo_with_artifact: Path, registry: RepoRegistry):
    registry.add("sample", str(repo_with_artifact), watch=True, debounce_ms=100, watch_mode="off")
    engine = BathoWatcherEngine(registry)
    patch_mock = MagicMock()
    with patch("batho.orchestrator.patch.run_patch", patch_mock):
        try:
            engine.start()
            watch = engine._watches["sample"]
            assert watch.mode == "off"
            f = repo_with_artifact / "main.py"
            engine._on_change("sample", "main.py", f)
            assert "main.py" in watch.pending_files
            time.sleep(0.3)
            patch_mock.assert_not_called()
            assert watch.sync_state == "pending"
        finally:
            engine.stop()


def test_last_flush_reason_recorded(repo_with_artifact: Path, registry: RepoRegistry):
    registry.add("sample", str(repo_with_artifact), watch=True, debounce_ms=100)
    engine = BathoWatcherEngine(registry)
    with patch("batho.mcp.tools.invalidate_reader_pool"):
        try:
            engine.start()
            f = repo_with_artifact / "main.py"
            engine._on_change("sample", "main.py", f)
            time.sleep(0.3)
            assert engine._watches["sample"].last_flush_reason == "debounce"
        finally:
            engine.stop()


def test_events_during_patch_repend(repo_with_artifact: Path, registry: RepoRegistry):
    """Files changed while a patch runs must re-pend, not be silently cleared."""
    registry.add("sample", str(repo_with_artifact), watch=True, debounce_ms=10_000)
    engine = BathoWatcherEngine(registry)

    def _patch_side_effect(_options):
        from batho.orchestrator.patch import PatchResult

        f = repo_with_artifact / "late.py"
        f.write_text("y = 1\n", encoding="utf-8")
        engine._on_change("sample", "late.py", f)
        return PatchResult(success=True)

    with patch("batho.orchestrator.patch.run_patch", side_effect=_patch_side_effect), patch("batho.mcp.tools.invalidate_reader_pool"):
        try:
            engine.start()
            watch = engine._watches["sample"]
            f = repo_with_artifact / "main.py"
            engine._on_change("sample", "main.py", f)
            engine._run_patch("sample", reason="debounce")
            assert "late.py" in watch.pending_files
            assert watch.sync_state == "pending"
            assert "main.py" not in watch.pending_files  # consumed by the patch
        finally:
            engine.stop()


# ---------------------------------------------------------------------
# T07 — git sentinel watcher
# ---------------------------------------------------------------------

def test_git_sentinel_classify():
    c = git_sentinel.classify
    assert c("index", False, "modified") == "boundary"
    assert c("HEAD", False, "modified") == "boundary"
    assert c("packed-refs", False, "modified") == "ignore"  # gc churn, not a boundary
    assert c("FETCH_HEAD", False, "modified") == "ignore"   # fetch noise; pull still flushes via merge/index
    assert c("refs/heads/main", False, "modified") == "boundary"
    assert c("refs/tags/v1.0", False, "created") == "boundary"
    assert c("refs/remotes/origin/main", False, "modified") == "ignore"  # remote-tracking: worktree untouched
    assert c("MERGE_HEAD", False, "created") == "boundary"
    assert c("index.lock", False, "created") == "lock"
    assert c("refs/heads/x.lock", False, "created") == "lock"
    assert c("objects/ab/cdef", False, "created") == "ignore"
    assert c("logs/HEAD", False, "modified") == "ignore"
    assert c(".watchman-cookie-abc", False, "created") == "ignore"
    assert c("fsmonitor--daemon/cookies/x", False, "created") == "ignore"
    assert c("rebase-merge/done", False, "created") == "in_progress"
    assert c("rebase-merge", True, "created") == "in_progress"
    assert c("rebase-merge", True, "deleted") == "boundary"  # op ended
    assert c("sequencer/todo", False, "modified") == "in_progress"
    assert c("", False, "") == "ignore"


def test_git_mode_resolves(git_repo: Path, registry: RepoRegistry):
    registry.add("sample", str(git_repo), watch=True)
    engine = BathoWatcherEngine(registry)
    try:
        engine.start()
        watch = engine._watches["sample"]
        assert watch.mode == "git"
        assert watch.git_dir is not None
        assert watch.git_observer is not None
        # resolve_git_dir returns both dirs; they coincide for a normal repo
        git_dir, common_dir = resolve_git_dir(git_repo)
        assert git_dir == (git_repo / ".git").resolve()
        assert common_dir == git_dir
    finally:
        engine.stop()


def test_fs_mode_no_git_observer(git_repo: Path, registry: RepoRegistry):
    registry.add("sample", str(git_repo), watch=True, watch_mode="fs")
    engine = BathoWatcherEngine(registry)
    try:
        engine.start()
        watch = engine._watches["sample"]
        assert watch.mode == "fs"
        assert watch.git_observer is None
        assert watch.git_dir is None
    finally:
        engine.stop()


def test_global_watch_mode_inherited(git_repo: Path, registry: RepoRegistry):
    """Registry watch_mode="auto" (unset) inherits the repo's batho.yaml mode."""
    (git_repo / "batho.yaml").write_text("watch:\n  mode: fs\n", encoding="utf-8")
    registry.add("sample", str(git_repo), watch=True)  # watch_mode left unset → "auto"
    engine = BathoWatcherEngine(registry)
    try:
        engine.start()
        watch = engine._watches["sample"]
        assert watch.mode == "fs"          # batho.yaml wins over registry "auto"
        assert watch.git_observer is None
    finally:
        engine.stop()


def test_per_repo_mode_beats_global(git_repo: Path, registry: RepoRegistry):
    """Explicit per-repo watch_mode overrides the global watch.mode."""
    (git_repo / "batho.yaml").write_text("watch:\n  mode: off\n", encoding="utf-8")
    registry.add("sample", str(git_repo), watch=True, watch_mode="fs")
    engine = BathoWatcherEngine(registry)
    try:
        engine.start()
        watch = engine._watches["sample"]
        assert watch.mode == "fs"
    finally:
        engine.stop()


def test_clean_patch_failure_marks_error(repo_with_artifact: Path, registry: RepoRegistry):
    """run_patch returning success=False must hit the error path, not 'idle'."""
    from batho.orchestrator.patch import PatchResult

    registry.add("sample", str(repo_with_artifact), watch=True)
    engine = BathoWatcherEngine(registry)
    fake = PatchResult(success=False, warnings=["missing artifact bundle"])
    with patch("batho.orchestrator.patch.run_patch", return_value=fake):
        try:
            engine.start()
            engine._on_change("sample", "main.py", repo_with_artifact / "main.py")
            engine._run_patch("sample", reason="debounce")
            watch = engine._watches["sample"]
            assert watch.sync_state == "error"
            assert "missing artifact bundle" in (watch.error_message or "")
            assert "main.py" in watch.pending_files  # queue restored, not dropped
            assert watch.staleness_timer is not None  # bounded retry armed
        finally:
            engine.stop()


def test_nongit_repo_fs_mode(repo_with_artifact: Path, registry: RepoRegistry):
    registry.add("sample", str(repo_with_artifact), watch=True)
    engine = BathoWatcherEngine(registry)
    try:
        engine.start()
        watch = engine._watches["sample"]
        assert watch.mode == "fs"
        assert watch.git_observer is None
    finally:
        engine.stop()


def test_git_boundary_event_flushes(git_repo: Path, registry: RepoRegistry):
    registry.add("sample", str(git_repo), watch=True, debounce_ms=10_000)
    engine = BathoWatcherEngine(registry)
    patch_mock = MagicMock()
    with patch("batho.orchestrator.patch.run_patch", patch_mock), patch("batho.mcp.tools.invalidate_reader_pool"):
        try:
            engine.start()
            watch = engine._watches["sample"]
            watch.git_settle_ms = 100
            git_dir = watch.git_dir
            engine._on_git_event("sample", git_dir / "index", False, "modified")
            assert watch.boundary_pending is True
            assert watch.settle_timer is not None
            time.sleep(0.35)
            patch_mock.assert_called()
            assert watch.last_flush_reason == "boundary"
        finally:
            engine.stop()


def test_git_noise_event_ignored(git_repo: Path, registry: RepoRegistry):
    registry.add("sample", str(git_repo), watch=True)
    engine = BathoWatcherEngine(registry)
    try:
        engine.start()
        watch = engine._watches["sample"]
        git_dir = watch.git_dir
        for name in ("objects/ab/cd", "objects/pack/pack-123.idx"):
            engine._on_git_event("sample", git_dir / name, False, "created")
        assert watch.boundary_pending is False
        assert watch.settle_timer is None
    finally:
        engine.stop()


# ---------------------------------------------------------------------
# T08 — VCS-operation hold
# ---------------------------------------------------------------------

def test_vcs_op_in_progress(tmp_path: Path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    assert not git_sentinel.vcs_op_in_progress(git_dir, git_dir)
    (git_dir / "index.lock").write_text("")
    assert git_sentinel.vcs_op_in_progress(git_dir, git_dir)
    (git_dir / "index.lock").unlink()
    assert not git_sentinel.vcs_op_in_progress(git_dir, git_dir)
    (git_dir / "rebase-merge").mkdir()
    assert git_sentinel.vcs_op_in_progress(git_dir, git_dir)


def test_hold_defers_flush(git_repo: Path, registry: RepoRegistry):
    registry.add("sample", str(git_repo), watch=True)
    engine = BathoWatcherEngine(registry)
    patch_mock = MagicMock()
    with patch("batho.orchestrator.patch.run_patch", patch_mock), patch("batho.mcp.tools.invalidate_reader_pool"):
        try:
            engine.start()
            watch = engine._watches["sample"]
            (watch.git_dir / "index.lock").write_text("")
            engine._run_patch("sample", reason="boundary")
            patch_mock.assert_not_called()
            assert watch.hold_started_ts is not None
            assert watch.hold_timer is not None
            watch.hold_timer.cancel()
            # Lock removed → flush proceeds (boundary_pending is set by the
            # sentinel event that accompanies a real "boundary" flush)
            (watch.git_dir / "index.lock").unlink()
            watch.boundary_pending = True
            engine._run_patch("sample", reason="boundary")
            patch_mock.assert_called_once()
            assert watch.hold_started_ts is None
        finally:
            engine.stop()


def test_stale_lock_hold_expires(git_repo: Path, registry: RepoRegistry):
    registry.add("sample", str(git_repo), watch=True)
    engine = BathoWatcherEngine(registry)
    patch_mock = MagicMock()
    with patch("batho.orchestrator.patch.run_patch", patch_mock), patch("batho.mcp.tools.invalidate_reader_pool"):
        try:
            engine.start()
            watch = engine._watches["sample"]
            watch.vcs_op_hold_ms = 100  # below clamp floor; test-only
            (watch.git_dir / "index.lock").write_text("")
            watch.boundary_pending = True  # set by the sentinel event
            engine._run_patch("sample", reason="boundary")  # enters hold
            patch_mock.assert_not_called()
            time.sleep(0.15)
            watch.boundary_pending = True
            engine._run_patch("sample", reason="boundary")  # cap exceeded → flush anyway
            patch_mock.assert_called_once()
            assert watch.hold_started_ts is None
        finally:
            engine.stop()


# ---------------------------------------------------------------------
# T09 — observability
# ---------------------------------------------------------------------

def test_status_schema_fields(repo_with_artifact: Path, registry: RepoRegistry):
    registry.add("sample", str(repo_with_artifact), watch=True)
    engine = BathoWatcherEngine(registry)
    try:
        engine.start()
        watch = engine._watches["sample"]
        watch.pending_files.add("a.py")
        watch.first_pending_ts = time.monotonic() - 5
        st = engine.status()["sample"]
        assert st["mode"] in ("git", "fs", "off")
        assert st["pending_count"] == 1
        assert 4.9 <= st["oldest_pending_age_s"] <= 6.0
        assert st["vcs_op_hold"] is False
        assert "last_flush_reason" in st
    finally:
        engine.stop()


def test_banner_pending_count(repo_with_artifact: Path, registry: RepoRegistry):
    registry.add("sample", str(repo_with_artifact), watch=True)
    engine = BathoWatcherEngine(registry)
    try:
        engine.start()
        watch = engine._watches["sample"]
        watch.pending_files.update({"a.py", "b.py", "c.py"})
        watch.sync_state = "pending"
        banner = engine.get_staleness_banner("sample")
        assert "3 files pending re-index" in banner
    finally:
        engine.stop()


def test_banner_vcs_hold(git_repo: Path, registry: RepoRegistry):
    registry.add("sample", str(git_repo), watch=True)
    engine = BathoWatcherEngine(registry)
    try:
        engine.start()
        watch = engine._watches["sample"]
        watch.sync_state = "pending"
        watch.hold_started_ts = time.monotonic()
        banner = engine.get_staleness_banner("sample")
        assert "Git operation in progress" in banner
    finally:
        engine.stop()


def test_unwatch_cancels_all_timers(repo_with_artifact: Path, registry: RepoRegistry):
    registry.add("sample", str(repo_with_artifact), watch=True, debounce_ms=10_000)
    engine = BathoWatcherEngine(registry)
    try:
        engine.start()
        watch = engine._watches["sample"]
        f = repo_with_artifact / "main.py"
        engine._on_change("sample", "main.py", f)
        engine._on_git_event("sample", repo_with_artifact / "x", False, "created")  # no git_dir → early return
        debounce_timer = watch.debounce_timer
        staleness_timer = watch.staleness_timer
        assert debounce_timer is not None
        assert staleness_timer is not None
        engine.unwatch("sample")
        assert watch.debounce_timer is None and watch.staleness_timer is None
        assert not debounce_timer.is_alive()
        assert not staleness_timer.is_alive()
    finally:
        engine.stop()


class _SpyLock:
    """RLock wrapper tracking hold depth — RLock is thread-reentrant, so
    `acquire()` can't prove "not held"; a depth counter can."""

    def __init__(self, real):
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "depth", 0)

    def __enter__(self):
        self._real.acquire()
        object.__setattr__(self, "depth", self.depth + 1)
        return self

    def __exit__(self, *a):
        object.__setattr__(self, "depth", self.depth - 1)
        self._real.release()
        return False

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_vcs_op_predicate_never_under_engine_lock(git_repo: Path, registry: RepoRegistry, monkeypatch):
    """WAT-01: vcs_op_in_progress() stat()s .git — under a stalled FS that
    would freeze every repo's event delivery while the engine-wide lock is
    held. Both call sites must evaluate it BEFORE acquiring self._lock."""
    registry.add("sample", str(git_repo), watch=True)
    engine = BathoWatcherEngine(registry)
    patch_mock = MagicMock()
    with patch("batho.orchestrator.patch.run_patch", patch_mock), patch(
        "batho.mcp.tools.invalidate_reader_pool"
    ):
        try:
            engine.start()
            watch = engine._watches["sample"]
            engine._lock = _SpyLock(engine._lock)

            depths = []
            def spy_stat(git_dir, common_dir):
                depths.append(engine._lock.depth)
                return False

            monkeypatch.setattr(git_sentinel, "vcs_op_in_progress", spy_stat)

            # site 1: _run_patch git-mode hold check
            watch.mode = "git"
            engine._run_patch("sample", "test")
            # site 2: _on_git_event lock-removal check (needs a live hold)
            watch.hold_started_ts = time.monotonic()
            engine._on_git_event(
                "sample", watch.git_dir / "index.lock", False, "deleted"
            )

            assert len(depths) == 2, f"predicate not reached: {depths}"
            assert depths == [0, 0], (
                f"vcs_op_in_progress ran under the engine lock: {depths}"
            )
        finally:
            engine.stop()


# ---------------------------------------------------------------------
# Phase-3 regressions: WAT-03/04/06/07/08/09
# ---------------------------------------------------------------------

def test_boundary_only_failure_restores_trigger_and_arms_retry(
    repo_with_artifact: Path, registry: RepoRegistry
):
    """WAT-03: a flush triggered purely by boundary_pending that fails must
    restore the trigger and arm a retry — the queue may be empty."""
    registry.add("sample", str(repo_with_artifact), watch=True, debounce_ms=100)
    engine = BathoWatcherEngine(registry)
    patch_mock = MagicMock(side_effect=RuntimeError("boom"))
    with patch("batho.orchestrator.patch.run_patch", patch_mock), \
            patch("batho.mcp.tools.invalidate_reader_pool"):
        try:
            engine.start()
            watch = engine._watches["sample"]
            watch.boundary_pending = True
            engine._run_patch("sample", reason="boundary")
            assert patch_mock.call_count == 1
            # trigger restored + retry armed even though pending_files is empty
            assert watch.boundary_pending is True
            assert watch.sync_state == "error"
            assert watch.staleness_timer is not None
            watch.staleness_timer.cancel()
        finally:
            engine.stop()


def test_stale_timer_preserves_patching_and_error_states(
    repo_with_artifact: Path, registry: RepoRegistry
):
    """WAT-04: a stale-timer fire on an empty queue must not downgrade
    patching/error back to idle."""
    registry.add("sample", str(repo_with_artifact), watch=True)
    engine = BathoWatcherEngine(registry)
    patch_mock = MagicMock()
    with patch("batho.orchestrator.patch.run_patch", patch_mock), \
            patch("batho.mcp.tools.invalidate_reader_pool"):
        try:
            engine.start()
            watch = engine._watches["sample"]
            for state in ("patching", "error"):
                watch.sync_state = state
                engine._run_patch("sample", reason="staleness")
                assert watch.sync_state == state
            patch_mock.assert_not_called()
            # pending still downgrades — the no-op path is intact
            watch.sync_state = "pending"
            engine._run_patch("sample", reason="staleness")
            assert watch.sync_state == "idle"
        finally:
            engine.stop()


def test_schedule_prunes_hidden_and_ignored_dirs_on_linux(
    tmp_path: Path, monkeypatch
):
    """WAT-06: Linux scheduling skips hidden subtrees (.git/objects fan-out)
    and ignored dirs instead of spending an inotify watch on each."""
    import sys as _sys
    from batho.mcp.watcher import _schedule_worktree_watches
    from batho.utils.ignore import load_ignore_spec

    monkeypatch.setattr(_sys, "platform", "linux")
    (tmp_path / ".git" / "objects" / "ab").mkdir(parents=True)
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    (tmp_path / "src" / ".hidden").mkdir()
    (tmp_path / "node_modules" / "dep").mkdir(parents=True)

    observer = MagicMock()
    _schedule_worktree_watches(
        observer, MagicMock(), tmp_path, load_ignore_spec(tmp_path)
    )
    scheduled = {Path(c.args[1]) for c in observer.schedule.call_args_list}
    assert {tmp_path, tmp_path / "src", tmp_path / "src" / "pkg"} <= scheduled
    assert not any(
        ".git" in p.parts or ".hidden" in p.name or "node_modules" in p.parts
        for p in scheduled
    )
    assert all(
        c.kwargs["recursive"] is False
        for c in observer.schedule.call_args_list
    )


def test_schedule_recursive_off_linux(tmp_path: Path, monkeypatch):
    """WAT-06: FSEvents/ReadDirectoryChanges pay no per-dir cost — keep
    recursive=True off Linux."""
    import sys as _sys
    from batho.mcp.watcher import _schedule_worktree_watches

    monkeypatch.setattr(_sys, "platform", "darwin")
    observer = MagicMock()
    _schedule_worktree_watches(observer, MagicMock(), tmp_path, None)
    observer.schedule.assert_called_once()
    assert observer.schedule.call_args.kwargs["recursive"] is True


def test_git_dir_env_does_not_redirect_resolution(
    git_repo: Path, tmp_path: Path, monkeypatch
):
    """WAT-07: an inherited GIT_DIR pointing at a foreign repo must not
    redirect resolve_git_dir's rev-parse output."""
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    subprocess.run(
        ["git", "init"], cwd=foreign, check=True, capture_output=True
    )
    monkeypatch.setenv("GIT_DIR", str(foreign / ".git"))
    resolved = resolve_git_dir(git_repo)
    assert resolved is not None
    git_dir, _common = resolved
    assert git_dir == (git_repo / ".git").resolve()


def test_watch_bails_when_repo_removed_mid_registration(
    repo_with_artifact: Path, registry: RepoRegistry
):
    """WAT-08: remove_repo between registry.add and watch() registration
    must leave no watch (and no live observer) behind."""
    engine = BathoWatcherEngine(registry)
    try:
        engine.start()  # engine running, no repos registered yet
        entry = registry.add("sample", str(repo_with_artifact), watch=True)
        registry.remove("sample")  # removed between add and watch() — the race
        engine.watch(entry)
        assert "sample" not in engine._watches
        assert entry not in registry.load()
    finally:
        engine.stop()


def test_catch_up_skips_watch_mode_off(
    repo_with_artifact: Path, registry: RepoRegistry
):
    """WAT-09: watch_mode='off' means never auto-patch — patch-on-connect
    included, even when files changed while the server was down."""
    registry.add(
        "sample", str(repo_with_artifact), watch=True, watch_mode="off"
    )
    engine = BathoWatcherEngine(registry)
    patch_mock = MagicMock()
    with patch("batho.orchestrator.patch.run_patch", patch_mock), \
            patch("batho.mcp.tools.invalidate_reader_pool"):
        try:
            engine.start()
            assert engine._watches["sample"].mode == "off"
            # mutate a tracked file so needs_patch would be True
            (repo_with_artifact / "main.py").write_text(
                "def changed(): pass\n", encoding="utf-8"
            )
            engine.catch_up("sample")
            patch_mock.assert_not_called()
        finally:
            engine.stop()
