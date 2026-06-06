"""Tests for BathoBundle facade — full public API (create_run, complete_run,
file_tracking, file_changelog, run_artifacts, get_bundle, resolve_bundle_dir)."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from batho.modules.storage.arrow_bundle import BathoBundle, get_bundle, resolve_bundle_dir
from batho.modules.storage.arrow_bundle.schemas import BUNDLE_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _new_bundle(root: Path) -> BathoBundle:
    return BathoBundle(root)


def _run_lifecycle(db: BathoBundle, run_uuid: str, files: list[str]) -> int:
    run_id = db.create_run(run_uuid, root_path=str(db._repo_root))
    for i, fp in enumerate(files):
        db.upsert_file_tracking([{
            "file_path": fp,
            "content_hash": f"hash_{i}",
            "mtime_ns": i * 1000,
            "inode": None,
            "size": 100 + i,
            "is_indexed": True,
            "last_run_uuid": run_uuid,
        }])
    db.complete_run(run_uuid, entity_count=len(files), file_count=len(files))
    return run_id


# ---------------------------------------------------------------------------
# resolve_bundle_dir / get_bundle
# ---------------------------------------------------------------------------

class TestResolveBundleDir:
    def test_returns_batho_artifact_subdir(self, tmp_path):
        bundle_dir = resolve_bundle_dir(tmp_path)
        assert bundle_dir == (tmp_path / ".batho" / "artifact").resolve()

    def test_consistent_across_calls(self, tmp_path):
        assert resolve_bundle_dir(tmp_path) == resolve_bundle_dir(tmp_path)

    def test_different_roots_different_dirs(self, tmp_path):
        a = tmp_path / "proj_a"
        b = tmp_path / "proj_b"
        a.mkdir(); b.mkdir()
        assert resolve_bundle_dir(a) != resolve_bundle_dir(b)

    def test_str_input_accepted(self, tmp_path):
        bundle_dir = resolve_bundle_dir(str(tmp_path))
        assert isinstance(bundle_dir, Path)


class TestGetBundle:
    def test_returns_batho_bundle(self, tmp_path):
        db = get_bundle(tmp_path)
        assert isinstance(db, BathoBundle)

    def test_creates_artifact_dir(self, tmp_path):
        get_bundle(tmp_path)
        assert (tmp_path / ".batho" / "artifact").exists()


# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------

class TestRunLifecycle:
    def test_create_and_complete_run(self, tmp_path):
        db = _new_bundle(tmp_path)
        run_id = db.create_run("r1")
        assert run_id == 1
        db.complete_run("r1", entity_count=5, file_count=2)

        db2 = _new_bundle(tmp_path)
        run = db2.get_run("r1")
        assert run is not None
        assert run["status"] == "completed"
        assert run["entity_count"] == 5

    def test_fail_run_records_error(self, tmp_path):
        db = _new_bundle(tmp_path)
        db.create_run("r_fail")
        db.fail_run("r_fail", error_message="boom")

        db2 = _new_bundle(tmp_path)
        run = db2.get_run("r_fail")
        assert run["status"] == "failed"
        assert run["error_message"] == "boom"

    def test_get_latest_run_id(self, tmp_path):
        db = _new_bundle(tmp_path)
        db.create_run("r1")
        db.complete_run("r1")
        db.create_run("r2")
        db.complete_run("r2")

        db2 = _new_bundle(tmp_path)
        assert db2.get_latest_run_id() == "r2"

    def test_get_run_internal_id(self, tmp_path):
        db = _new_bundle(tmp_path)
        db.create_run("r1")
        db.complete_run("r1")

        db2 = _new_bundle(tmp_path)
        assert db2.get_run_internal_id("r1") == 1

    def test_multiple_sequential_runs(self, tmp_path):
        for i in range(3):
            db = _new_bundle(tmp_path)
            db.create_run(f"r{i}")
            db.complete_run(f"r{i}")

        db_final = _new_bundle(tmp_path)
        runs = db_final._reader.get_all_runs()
        assert len(runs) == 3


# ---------------------------------------------------------------------------
# File tracking
# ---------------------------------------------------------------------------

class TestFileTracking:
    def test_upsert_and_retrieve(self, tmp_path):
        db = _new_bundle(tmp_path)
        db.create_run("r1")
        db.upsert_file_tracking([{
            "file_path": "src/main.py", "content_hash": "abc123",
            "mtime_ns": 1000, "inode": None, "size": 500,
            "is_indexed": True, "last_run_uuid": "r1",
        }])
        db.complete_run("r1")

        db2 = _new_bundle(tmp_path)
        hashes = db2.get_all_file_hashes()
        assert "src/main.py" in hashes
        assert hashes["src/main.py"] == "abc123"

    def test_upsert_updates_existing_entry(self, tmp_path):
        db = _new_bundle(tmp_path)
        db.create_run("r1")
        db.upsert_file_tracking([{
            "file_path": "f.py", "content_hash": "old",
            "mtime_ns": 0, "inode": None, "size": 10,
            "is_indexed": True, "last_run_uuid": "r1",
        }])
        db.complete_run("r1")

        db2 = _new_bundle(tmp_path)
        db2.create_run("r2")
        db2.upsert_file_tracking([{
            "file_path": "f.py", "content_hash": "new",
            "mtime_ns": 9999, "inode": None, "size": 20,
            "is_indexed": True, "last_run_uuid": "r2",
        }])
        db2.complete_run("r2")

        db3 = _new_bundle(tmp_path)
        hashes = db3.get_all_file_hashes()
        assert hashes["f.py"] == "new"

    def test_get_all_file_tracking_returns_dict(self, tmp_path):
        db = _new_bundle(tmp_path)
        _run_lifecycle(db, "r1", ["a.py", "b.py"])

        db2 = _new_bundle(tmp_path)
        tracking = db2.get_all_file_tracking()
        assert isinstance(tracking, dict)
        assert len(tracking) == 2

    def test_delete_file_tracking(self, tmp_path):
        db = _new_bundle(tmp_path)
        _run_lifecycle(db, "r1", ["a.py", "b.py"])

        db2 = _new_bundle(tmp_path)
        db2.delete_file_tracking("a.py")

        db3 = _new_bundle(tmp_path)
        tracking = db3.get_all_file_tracking()
        assert "a.py" not in tracking
        assert "b.py" in tracking


# ---------------------------------------------------------------------------
# File changelog
# ---------------------------------------------------------------------------

class TestFileChangelog:
    def _make_diff(self, file_id: int, entity_id: str, kind: str = "added") -> dict:
        return {
            "entity_id": entity_id,
            "entity_name": "fn",
            "entity_type": "function",
            "change_kind": kind,
            "changed_fields": [],
            "old_hash": None,
            "new_hash": "newhash",
            "file_id": file_id,
        }

    def test_record_and_retrieve_changelog(self, tmp_path):
        db = _new_bundle(tmp_path)
        db.create_run("r1")
        db.upsert_file_tracking([{
            "file_path": "a.py", "content_hash": "h",
            "mtime_ns": 0, "inode": None, "size": 10,
            "is_indexed": True, "last_run_uuid": "r1",
        }])
        file_id = db._get_or_create_file_id("a.py")
        db.record_file_changelog("r1", None, [self._make_diff(file_id, "e1")])
        db.complete_run("r1")

        db2 = _new_bundle(tmp_path)
        history = db2._reader.get_file_changelog_raw()
        assert len(history) >= 1

    def test_get_file_node_history(self, tmp_path):
        db = _new_bundle(tmp_path)
        db.create_run("r1")
        db.upsert_file_tracking([{
            "file_path": "x.py", "content_hash": "hx",
            "mtime_ns": 0, "inode": None, "size": 10,
            "is_indexed": True, "last_run_uuid": "r1",
        }])
        file_id = db._get_or_create_file_id("x.py")
        db.record_file_changelog("r1", None, [self._make_diff(file_id, "ent_x")])
        db.complete_run("r1")

        db2 = _new_bundle(tmp_path)
        history = db2.get_file_node_history("ent_x")
        assert len(history) >= 1
        assert history[0]["entity_id"] == "ent_x"


# ---------------------------------------------------------------------------
# Run artifacts
# ---------------------------------------------------------------------------

class TestRunArtifacts:
    def test_finalize_and_retrieve_run_artifacts(self, tmp_path):
        db = _new_bundle(tmp_path)
        run_id = db.create_run("r1")
        db.finalize_run_artifacts(run_id, {
            "context_overview": {"summary": "test"},
            "telemetry_metrics": {"duration_ms": 100},
        })
        db.complete_run("r1")

        db2 = _new_bundle(tmp_path)
        arts = db2.get_run_artifacts(run_id)
        assert arts is not None
        assert arts["run_id"] == run_id

    def test_run_artifacts_missing_returns_none(self, tmp_path):
        db = _new_bundle(tmp_path)
        assert db.get_run_artifacts(999) is None


# ---------------------------------------------------------------------------
# Bundle isolation — two independent roots
# ---------------------------------------------------------------------------

class TestBundleIsolation:
    def test_two_roots_independent(self, tmp_path):
        root_a = tmp_path / "project_a"
        root_b = tmp_path / "project_b"
        root_a.mkdir(); root_b.mkdir()

        db_a = _new_bundle(root_a)
        _run_lifecycle(db_a, "r_a", ["a.py"])

        db_b = _new_bundle(root_b)
        _run_lifecycle(db_b, "r_b", ["b.py"])

        check_a = _new_bundle(root_a)
        check_b = _new_bundle(root_b)

        assert "a.py" in check_a.get_all_file_hashes()
        assert "b.py" not in check_a.get_all_file_hashes()

        assert "b.py" in check_b.get_all_file_hashes()
        assert "a.py" not in check_b.get_all_file_hashes()

    def test_bundle_manifest_exists_after_run(self, tmp_path):
        db = _new_bundle(tmp_path)
        _run_lifecycle(db, "r1", ["main.py"])
        assert (resolve_bundle_dir(tmp_path) / "meta.json").exists()
