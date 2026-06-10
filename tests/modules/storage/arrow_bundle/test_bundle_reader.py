"""Tests for BathoBundleReader — mmap, offset index, O(1) slice lookup."""

from __future__ import annotations

from pathlib import Path
import time
import json

import pyarrow as pa
import pytest

from batho.modules.storage.arrow_bundle.manager import BathoBundleManager
from batho.modules.storage.arrow_bundle.reader import BathoBundleReader
from batho.modules.storage.arrow_bundle.writer import write_simple_ipc
from batho.modules.storage.arrow_bundle.schemas import (
    BUNDLE_SCHEMA_VERSION,
    FILE_TRACKING_SCHEMA,
    RUNS_SCHEMA,
    AGENT_VIEWS_SCHEMA,
    RELS_VIEWS_SCHEMA,
    FILE_CHANGELOG_SCHEMA,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _commit(artifact_dir: Path, logical: str, rows: list[dict], schema: pa.Schema, run_uuid: str = "r1") -> BathoBundleManager:
    mgr = BathoBundleManager(artifact_dir)
    tmp = artifact_dir / f"{logical}.tmp.ipc"
    write_simple_ipc(rows, schema, tmp)
    mgr.commit_patch({logical: tmp}, run_uuid)
    return mgr


def _tracking_row(file_id: int, file_path: str, run_uuid: str = "r1") -> dict:
    return {
        "file_id": file_id, "file_path": file_path, "content_hash": f"h{file_id}",
        "mtime_ns": 0, "inode": None, "size": 100, "is_indexed": True,
        "last_run_uuid": run_uuid, "updated_at": "2024-01-01T00:00:00", "encoding": "utf-8",
    }


def _agent_row(file_id: int, entity_id: str) -> dict:
    return {
        "file_id": file_id, "entity_id": entity_id, "name": "fn",
        "entity_type": "function", "start_line": 1, "end_line": 5,
        "signature": None, "content_hash": "abc", "is_exported": False, "fqn": None,
    }


def _run_row(uuid: str) -> dict:
    return {
        "run_uuid": uuid, "schema_version": BUNDLE_SCHEMA_VERSION,
        "started_at": "2024-01-01T00:00:00Z", "completed_at": "2024-01-01T00:00:01Z",
        "status": "completed", "git_commit": None, "git_branch": None,
        "root_path": "/repo", "entity_count": 1, "rel_count": 0,
        "file_count": 1, "duration_ms": 100, "error_message": None,
    }


# ---------------------------------------------------------------------------
# Empty bundle
# ---------------------------------------------------------------------------

class TestEmptyBundle:
    def test_get_all_file_hashes_empty(self, tmp_path):
        reader = BathoBundleReader(tmp_path)
        assert reader.get_all_file_hashes() == {}

    def test_get_all_file_tracking_empty(self, tmp_path):
        reader = BathoBundleReader(tmp_path)
        assert reader.get_all_file_tracking() == {}

    def test_get_all_runs_empty(self, tmp_path):
        reader = BathoBundleReader(tmp_path)
        assert reader.get_all_runs() == []

    def test_get_run_missing(self, tmp_path):
        reader = BathoBundleReader(tmp_path)
        assert reader.get_run("nonexistent") is None

    def test_get_latest_run_id_empty(self, tmp_path):
        reader = BathoBundleReader(tmp_path)
        assert reader.get_latest_run_id() is None

    def test_get_file_artifacts_by_id_empty(self, tmp_path):
        reader = BathoBundleReader(tmp_path)
        result = reader.get_file_artifacts_by_id(1)
        assert result["agent_view"] == []
        assert result["rels_view"] == []


# ---------------------------------------------------------------------------
# File tracking reads
# ---------------------------------------------------------------------------

class TestFileTrackingReads:
    def _setup(self, tmp_path: Path) -> BathoBundleReader:
        rows = [_tracking_row(1, "a.py"), _tracking_row(2, "b.py")]
        _commit(tmp_path, "file_tracking", rows, FILE_TRACKING_SCHEMA)
        return BathoBundleReader(tmp_path)

    def test_get_all_file_hashes(self, tmp_path):
        reader = self._setup(tmp_path)
        hashes = reader.get_all_file_hashes()
        assert set(hashes.keys()) == {"a.py", "b.py"}
        assert hashes["a.py"] == "h1"

    def test_get_all_file_tracking(self, tmp_path):
        reader = self._setup(tmp_path)
        tracking = reader.get_all_file_tracking()
        assert len(tracking) == 2
        assert tracking["a.py"]["file_id"] == 1

    def test_get_file_tracking_single(self, tmp_path):
        reader = self._setup(tmp_path)
        row = reader.get_file_tracking("b.py")
        assert row is not None
        assert row["file_id"] == 2

    def test_get_file_tracking_missing(self, tmp_path):
        reader = self._setup(tmp_path)
        assert reader.get_file_tracking("missing.py") is None

    def test_file_id_for_path(self, tmp_path):
        reader = self._setup(tmp_path)
        assert reader.file_id_for_path("a.py") == 1
        assert reader.file_id_for_path("b.py") == 2
        assert reader.file_id_for_path("c.py") is None

    def test_get_unindexed_files(self, tmp_path):
        rows = [
            _tracking_row(1, "a.py") | {"is_indexed": True},
            _tracking_row(2, "b.py") | {"is_indexed": False},
        ]
        _commit(tmp_path, "file_tracking", rows, FILE_TRACKING_SCHEMA)
        reader = BathoBundleReader(tmp_path)
        unindexed = reader.get_unindexed_files_with_details()
        assert len(unindexed) == 1
        assert unindexed[0]["file_path"] == "b.py"


# ---------------------------------------------------------------------------
# Runs reads
# ---------------------------------------------------------------------------

class TestRunsReads:
    def _setup(self, tmp_path: Path) -> BathoBundleReader:
        rows = [_run_row("r1"), _run_row("r2")]
        _commit(tmp_path, "runs", rows, RUNS_SCHEMA, "r2")
        return BathoBundleReader(tmp_path)

    def test_get_all_runs(self, tmp_path):
        reader = self._setup(tmp_path)
        runs = reader.get_all_runs()
        assert len(runs) == 2

    def test_get_run_by_uuid(self, tmp_path):
        reader = self._setup(tmp_path)
        run = reader.get_run("r1")
        assert run is not None
        assert run["run_uuid"] == "r1"

    def test_get_run_missing(self, tmp_path):
        reader = self._setup(tmp_path)
        assert reader.get_run("r999") is None

    def test_get_latest_run_id_from_manifest(self, tmp_path):
        reader = self._setup(tmp_path)
        assert reader.get_latest_run_id() == "r2"

    def test_get_run_internal_id(self, tmp_path):
        reader = self._setup(tmp_path)
        assert reader.get_run_internal_id("r1") == 1
        assert reader.get_run_internal_id("r2") == 2
        assert reader.get_run_internal_id("rX") is None


# ---------------------------------------------------------------------------
# Offset index + O(1) slice
# ---------------------------------------------------------------------------

class TestOffsetIndex:
    def _setup_agent_views(self, tmp_path: Path) -> BathoBundleReader:
        rows = [
            _agent_row(1, "e1"), _agent_row(1, "e2"),
            _agent_row(2, "e3"),
            _agent_row(3, "e4"), _agent_row(3, "e5"), _agent_row(3, "e6"),
        ]
        _commit(tmp_path, "agent_views", rows, AGENT_VIEWS_SCHEMA)
        _commit(tmp_path, "file_tracking",
                [_tracking_row(1, "a.py"), _tracking_row(2, "b.py"), _tracking_row(3, "c.py")],
                FILE_TRACKING_SCHEMA)
        return BathoBundleReader(tmp_path)

    def test_index_built_correctly(self, tmp_path):
        reader = self._setup_agent_views(tmp_path)
        table = reader._get_table("agent_views")
        assert table.num_rows == 6
        idx = reader._indices["agent_views"]
        assert idx[1] == slice(0, 2)
        assert idx[2] == slice(2, 3)
        assert idx[3] == slice(3, 6)

    def test_get_file_artifacts_by_id_file1(self, tmp_path):
        reader = self._setup_agent_views(tmp_path)
        result = reader.get_file_artifacts_by_id(1)
        assert len(result["agent_view"]) == 2
        assert {r["entity_id"] for r in result["agent_view"]} == {"e1", "e2"}

    def test_get_file_artifacts_by_id_file3(self, tmp_path):
        reader = self._setup_agent_views(tmp_path)
        result = reader.get_file_artifacts_by_id(3)
        assert len(result["agent_view"]) == 3

    def test_get_file_artifacts_missing_file_id(self, tmp_path):
        reader = self._setup_agent_views(tmp_path)
        result = reader.get_file_artifacts_by_id(99)
        assert result["agent_view"] == []


# ---------------------------------------------------------------------------
# Invalidation
# ---------------------------------------------------------------------------

class TestInvalidation:
    def test_invalidate_single_table_forces_reread(self, tmp_path):
        rows = [_tracking_row(1, "a.py")]
        _commit(tmp_path, "file_tracking", rows, FILE_TRACKING_SCHEMA, "r1")

        reader = BathoBundleReader(tmp_path)
        reader.get_all_file_hashes()
        assert "file_tracking" in reader._tables

        rows2 = [_tracking_row(1, "a.py"), _tracking_row(2, "b.py")]
        _commit(tmp_path, "file_tracking", rows2, FILE_TRACKING_SCHEMA, "r2")
        reader.invalidate("file_tracking")
        assert "file_tracking" not in reader._tables

        hashes = reader.get_all_file_hashes()
        assert len(hashes) == 2

    def test_invalidate_all_clears_cache(self, tmp_path):
        rows = [_tracking_row(1, "a.py")]
        _commit(tmp_path, "file_tracking", rows, FILE_TRACKING_SCHEMA)
        _commit(tmp_path, "runs", [_run_row("r1")], RUNS_SCHEMA)

        reader = BathoBundleReader(tmp_path)
        reader.get_all_file_hashes()
        reader.get_all_runs()
        assert len(reader._tables) == 2

        reader.invalidate()
        assert reader._tables == {}
        assert reader._indices == {}


class TestReaderCacheInvalidation:
    """Robustness of automated invalidation on reader caches when metadata changes on disk."""

    def test_reader_cache_invalidation(self, tmp_path: Path):
        """Verify that reader caches are invalidated automatically when the active path changes on disk.

        Scenario:
            An Arrow database reader keeps tables cached in memory (`_tables`).
            If another build/patch process updates the manifest generation (e.g. from 1 to 2) and switches
            the active file, the reader must automatically detect this on the next call, clear its cached
            tables, and load the fresh file from disk.

        Execution Flow:
            1. Setup a mock Arrow Bundle directory.
            2. Write initial generation-1 runs table containing `uuid-1` to `runs.v1.ipc` and update `meta.json`.
            3. Instantiate `BathoBundleReader` and call `_get_table("runs")` to cache it.
            4. Assert that cached content yields `["uuid-1"]`.
            5. Write updated generation-2 runs table containing `uuid-2` to `runs.v2.ipc` and update `meta.json`.
            6. Sleep briefly to ensure filesystem modification time st_mtime changes significantly.
            7. Call `_get_table("runs")` again.
            8. Assert that the reader automatically invalidates its cache and yields `["uuid-2"]`.

        Expectations:
            - Multi-process cache consistency.
            - Automatically refreshes memory structures on disk generation bumps.
        """
        # Setup Arrow Bundle dir
        artifact_dir = tmp_path / "artifact"
        artifact_dir.mkdir()
        
        # 1. Write initial runs table
        schema = pa.schema([("run_uuid", pa.string())])
        runs_table_1 = pa.Table.from_pydict({"run_uuid": ["uuid-1"]}, schema=schema)
        
        import pyarrow.ipc as ipc
        tmp1 = artifact_dir / "runs.v1.ipc"
        with ipc.new_file(str(tmp1), schema) as w:
            w.write_table(runs_table_1)
            
        # Write initial meta.json
        import json
        meta_path = artifact_dir / "meta.json"
        meta_path.write_text(json.dumps({
            "generation": 1,
            "active_files": {
                "runs": "runs.v1.ipc"
            }
        }))
        
        # Create reader
        reader = BathoBundleReader(artifact_dir)
        
        # Read table - should return runs.v1.ipc content
        t1 = reader._get_table("runs")
        assert t1.column("run_uuid").to_pylist() == ["uuid-1"]
        
        # 2. Write new runs table (generation 2)
        runs_table_2 = pa.Table.from_pydict({"run_uuid": ["uuid-2"]}, schema=schema)
        tmp2 = artifact_dir / "runs.v2.ipc"
        with ipc.new_file(str(tmp2), schema) as w:
            w.write_table(runs_table_2)
            
        # Update meta.json (and clear manager's manifest cache to ensure it reads it)
        # Sleep a bit to guarantee mtime resolution changes if filesystem resolution is coarse
        time.sleep(0.1)
        meta_path.write_text(json.dumps({
            "generation": 2,
            "active_files": {
                "runs": "runs.v2.ipc"
            }
        }))
        
        # Read table again - should invalidate cache automatically and return runs.v2.ipc content
        t2 = reader._get_table("runs")
        assert t2.column("run_uuid").to_pylist() == ["uuid-2"]

