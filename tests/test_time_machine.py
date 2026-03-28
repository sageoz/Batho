"""Tests for batho_core.time_machine module."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from batho_core.context.codegraph import InMemoryGraph
from batho_core.context.repomap import RepoMap
from batho_core.context.schema import Entity, EntityType
from batho_core.time_machine import (
    compute_staleness,
    create_snapshot,
    diff_snapshots,
    generate_snapshot_id,
    list_snapshots,
    load_snapshot,
    webhook_stub,
)


# ---------------------------------------------------------------------------
# generate_snapshot_id
# ---------------------------------------------------------------------------

class TestGenerateSnapshotId:

    def test_format(self):
        sid = generate_snapshot_id()
        assert sid.startswith("batho_")
        assert "T" in sid  # timestamp portion

    def test_unique(self):
        a = generate_snapshot_id()
        b = generate_snapshot_id()
        assert a != b


# ---------------------------------------------------------------------------
# create_snapshot / load_snapshot / list_snapshots
# ---------------------------------------------------------------------------

class TestSnapshotLifecycle:

    def test_create_and_load(self, tmp_path: Path, mock_graph):
        ctn_dir = tmp_path / ".ctn"
        ctn_dir.mkdir()
        repomap = RepoMap.build(mock_graph, root=str(tmp_path))

        sid = create_snapshot(ctn_dir, tmp_path, mock_graph, repomap, label="test")
        assert sid.startswith("batho_")

        loaded = load_snapshot(ctn_dir, sid)
        assert loaded is not None
        assert loaded["snapshot_id"] == sid
        assert loaded["label"] == "test"

    def test_list_snapshots(self, tmp_path: Path, mock_graph):
        ctn_dir = tmp_path / ".ctn"
        ctn_dir.mkdir()
        repomap = RepoMap.build(mock_graph, root=str(tmp_path))

        create_snapshot(ctn_dir, tmp_path, mock_graph, repomap)
        create_snapshot(ctn_dir, tmp_path, mock_graph, repomap, label="second")

        snaps = list_snapshots(ctn_dir)
        assert len(snaps) == 2

    def test_load_missing_returns_none(self, tmp_path: Path):
        ctn_dir = tmp_path / ".ctn"
        ctn_dir.mkdir()
        assert load_snapshot(ctn_dir, "nonexistent_id") is None

    def test_load_corrupted_checksum_returns_none(self, tmp_path: Path):
        ctn_dir = tmp_path / ".ctn"
        ctn_dir.mkdir()
        snap_dir = ctn_dir / "snapshots"
        snap_dir.mkdir()
        snap_file = snap_dir / "bad_snap.json"
        snap_file.write_text(json.dumps({
            "snapshot_id": "bad_snap",
            "_checksum": "invalidchecksum",
            "data": "test",
        }))
        assert load_snapshot(ctn_dir, "bad_snap") is None


# ---------------------------------------------------------------------------
# diff_snapshots
# ---------------------------------------------------------------------------

class TestDiffSnapshots:

    def test_same_snapshot(self, tmp_path: Path, mock_graph):
        ctn_dir = tmp_path / ".ctn"
        ctn_dir.mkdir()
        repomap = RepoMap.build(mock_graph, root=str(tmp_path))

        sid = create_snapshot(ctn_dir, tmp_path, mock_graph, repomap)
        snap = load_snapshot(ctn_dir, sid)

        diff = diff_snapshots(snap, snap)
        assert diff["entity_delta"] == 0
        assert diff["relationship_delta"] == 0
        assert diff["added_files"] == []
        assert diff["removed_files"] == []

    def test_diff_with_changes(self):
        a = {
            "stats": {"entity_count": 10, "relationship_count": 5},
            "repomap": {"files": {"a.py": [], "b.py": []}},
        }
        b = {
            "stats": {"entity_count": 15, "relationship_count": 8},
            "repomap": {"files": {"b.py": [], "c.py": []}},
        }
        diff = diff_snapshots(a, b)
        assert diff["entity_delta"] == 5
        assert diff["relationship_delta"] == 3
        assert "c.py" in diff["added_files"]
        assert "a.py" in diff["removed_files"]


# ---------------------------------------------------------------------------
# compute_staleness
# ---------------------------------------------------------------------------

class TestComputeStaleness:

    def test_no_previous_entry(self):
        assert compute_staleness(None, "hash1") == 1.0

    def test_same_hash_low_staleness(self):
        prev = {"repo_hash": "abc", "file_count": 10}
        score = compute_staleness(prev, "abc")
        assert score < 0.5

    def test_different_hash_higher_staleness(self):
        prev = {"repo_hash": "abc", "file_count": 10}
        score = compute_staleness(prev, "xyz")
        assert score >= 0.6

    def test_returns_float_in_range(self):
        prev = {"repo_hash": "abc", "file_count": 10, "timestamp": "2025-01-01T00:00:00+00:00"}
        score = compute_staleness(prev, "abc", {"files_parsed": 5, "errors": 0})
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# webhook_stub
# ---------------------------------------------------------------------------

class TestWebhookStub:

    def test_returns_expected_keys(self):
        result = webhook_stub({"event": "push", "repository": {"full_name": "user/repo"}})
        assert result["event"] == "push"
        assert result["repo"] == "user/repo"
        assert result["status"] == "not_implemented"

    def test_missing_event(self):
        result = webhook_stub({})
        assert result["event"] == "unknown"
