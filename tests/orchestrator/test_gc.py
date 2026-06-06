"""Tests for batho gc orchestrator against the Arrow Bundle."""
from __future__ import annotations

import pytest
from pathlib import Path

from batho.modules.storage.arrow_bundle.bundle import BathoBundle, resolve_bundle_dir
from batho.orchestrator.gc import GCOptions, run_gc


def _make_bundle_with_run(tmp_path: Path) -> tuple[BathoBundle, str]:
    """Bootstrap a minimal bundle with one completed run."""
    db = BathoBundle(tmp_path)
    run_uuid = "build_test_gc_0001"
    db.create_run(run_uuid, root_path=str(tmp_path))
    db.complete_run(run_uuid, entity_count=5, rel_count=3, file_count=1, duration_ms=100)
    db.close()
    return BathoBundle(tmp_path), run_uuid


class TestGCStatus:
    def test_status_returns_success(self, tmp_path):
        _make_bundle_with_run(tmp_path)
        opts = GCOptions(root=tmp_path, command="status")
        result = run_gc(opts)
        assert result["success"]
        assert "Arrow generation" in result["message"]

    def test_status_missing_bundle(self, tmp_path):
        opts = GCOptions(root=tmp_path, command="status")
        result = run_gc(opts)
        assert not result["success"]
        assert "No artifact bundle" in result["message"]


class TestGCDeleteRun:
    def test_delete_existing_run(self, tmp_path):
        _, run_uuid = _make_bundle_with_run(tmp_path)
        opts = GCOptions(root=tmp_path, command="run", run_uuid=run_uuid)
        result = run_gc(opts)
        assert result["success"]

        db = BathoBundle(tmp_path)
        assert db.get_run(run_uuid) is None

    def test_delete_nonexistent_run(self, tmp_path):
        _make_bundle_with_run(tmp_path)
        opts = GCOptions(root=tmp_path, command="run", run_uuid="nonexistent_run")
        result = run_gc(opts)
        assert not result["success"]
        assert "not found" in result["message"].lower()

    def test_delete_run_missing_uuid(self, tmp_path):
        _make_bundle_with_run(tmp_path)
        opts = GCOptions(root=tmp_path, command="run", run_uuid=None)
        result = run_gc(opts)
        assert not result["success"]


class TestGCVacuum:
    def test_vacuum_removes_orphans(self, tmp_path):
        db, run_uuid = _make_bundle_with_run(tmp_path)
        bundle_dir = resolve_bundle_dir(tmp_path)

        orphan = bundle_dir / "agent_views.v999.ipc"
        orphan.write_bytes(b"fake")

        opts = GCOptions(root=tmp_path, command="vacuum")
        result = run_gc(opts)
        assert result["success"]
        assert not orphan.exists()

    def test_orphans_subcommand(self, tmp_path):
        _make_bundle_with_run(tmp_path)
        bundle_dir = resolve_bundle_dir(tmp_path)
        (bundle_dir / "rels_views.v888.ipc").write_bytes(b"stale")

        opts = GCOptions(root=tmp_path, command="orphans")
        result = run_gc(opts)
        assert result["success"]
        assert "stale IPC file" in result["message"]


class TestGCPruneOldRuns:
    def test_prune_no_old_runs(self, tmp_path):
        _make_bundle_with_run(tmp_path)
        opts = GCOptions(root=tmp_path, command="runs", older_than=365)
        result = run_gc(opts)
        assert result["success"]
        assert "No runs found" in result["message"]

    def test_prune_invalid_threshold(self, tmp_path):
        _make_bundle_with_run(tmp_path)
        opts = GCOptions(root=tmp_path, command="runs", older_than=-1)
        result = run_gc(opts)
        assert not result["success"]


class TestGCUnknownCommand:
    def test_unknown_command(self, tmp_path):
        _make_bundle_with_run(tmp_path)
        opts = GCOptions(root=tmp_path, command="noop")
        result = run_gc(opts)
        assert not result["success"]
        assert "Unknown gc command" in result["message"]
