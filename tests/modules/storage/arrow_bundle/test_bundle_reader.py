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
        """Verify get_all_file_hashes returns an empty dictionary when there are no active tracking files.

        Scenario:
            An empty or uninitialized Arrow bundle directory.

        Execution Flow:
            1. Initialize BathoBundleReader with the temp path.
            2. Call get_all_file_hashes.
            3. Assert that the returned value is `{}`.

        Expectations:
            - Gracefully returns an empty dictionary when no files are tracked.
        """
        reader = BathoBundleReader(tmp_path)
        assert reader.get_all_file_hashes() == {}

    def test_get_all_file_tracking_empty(self, tmp_path):
        """Verify get_all_file_tracking returns an empty dictionary in an uninitialized bundle.

        Scenario:
            The bundle has no active tracking files committed.

        Execution Flow:
            1. Initialize BathoBundleReader.
            2. Call get_all_file_tracking.
            3. Assert that the returned value is `{}`.

        Expectations:
            - Returns an empty mapping safely.
        """
        reader = BathoBundleReader(tmp_path)
        assert reader.get_all_file_tracking() == {}

    def test_get_all_runs_empty(self, tmp_path):
        """Verify get_all_runs returns an empty list when no runs have been executed/committed.

        Scenario:
            An empty bundle directory.

        Execution Flow:
            1. Initialize BathoBundleReader.
            2. Call get_all_runs.
            3. Assert that the returned value is `[]`.

        Expectations:
            - Returns an empty list safely.
        """
        reader = BathoBundleReader(tmp_path)
        assert reader.get_all_runs() == []

    def test_get_run_missing(self, tmp_path):
        """Verify get_run returns None when searching for a non-existent run.

        Scenario:
            Querying run information for a specific UUID in an empty bundle.

        Execution Flow:
            1. Initialize BathoBundleReader.
            2. Call get_run with "nonexistent".
            3. Assert that the returned value is None.

        Expectations:
            - Non-existent runs resolve to None.
        """
        reader = BathoBundleReader(tmp_path)
        assert reader.get_run("nonexistent") is None

    def test_get_latest_run_id_empty(self, tmp_path):
        """Verify get_latest_run_id returns None in an empty bundle.

        Scenario:
            An empty bundle directory.

        Execution Flow:
            1. Initialize BathoBundleReader.
            2. Call get_latest_run_id.
            3. Assert that the returned value is None.

        Expectations:
            - Resolves to None when no runs exist.
        """
        reader = BathoBundleReader(tmp_path)
        assert reader.get_latest_run_id() is None

    def test_get_file_artifacts_by_id_empty(self, tmp_path):
        """Verify get_file_artifacts_by_id returns empty lists for agent and rels views in an empty bundle.

        Scenario:
            An empty bundle directory.

        Execution Flow:
            1. Initialize BathoBundleReader.
            2. Call get_file_artifacts_by_id with a file ID of 1.
            3. Assert that both "agent_view" and "rels_view" are empty lists.

        Expectations:
            - Returns a default dictionary with empty lists for both views.
        """
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
        """Verify get_all_file_hashes returns file path to hash mapping for committed files.

        Scenario:
            A bundle contains committed file tracking records for two files.

        Execution Flow:
            1. Setup the reader with "a.py" and "b.py" committed.
            2. Call get_all_file_hashes.
            3. Verify the keys are "a.py" and "b.py", and that "a.py"'s hash is "h1".

        Expectations:
            - Returned dictionary contains all tracked files mapped to their content hashes.
        """
        reader = self._setup(tmp_path)
        hashes = reader.get_all_file_hashes()
        assert set(hashes.keys()) == {"a.py", "b.py"}
        assert hashes["a.py"] == "h1"

    def test_get_all_file_tracking(self, tmp_path):
        """Verify get_all_file_tracking returns the full details of all tracked files.

        Scenario:
            Multiple files are tracked in the committed bundle.

        Execution Flow:
            1. Setup the reader with two tracked files.
            2. Call get_all_file_tracking.
            3. Assert that the length of the dictionary is 2.
            4. Verify that "a.py"'s record has file_id 1.

        Expectations:
            - Details for all tracked files are successfully resolved and returned.
        """
        reader = self._setup(tmp_path)
        tracking = reader.get_all_file_tracking()
        assert len(tracking) == 2
        assert tracking["a.py"]["file_id"] == 1

    def test_get_file_tracking_single(self, tmp_path):
        """Verify get_file_tracking returns details for a single specified file.

        Scenario:
            A specific file's details are requested from a populated bundle.

        Execution Flow:
            1. Setup the reader with "b.py" committed.
            2. Call get_file_tracking for "b.py".
            3. Verify the returned dict is not None and matches file_id 2.

        Expectations:
            - Resolves tracking details accurately for the specified file.
        """
        reader = self._setup(tmp_path)
        row = reader.get_file_tracking("b.py")
        assert row is not None
        assert row["file_id"] == 2

    def test_get_file_tracking_missing(self, tmp_path):
        """Verify get_file_tracking returns None for an untracked file.

        Scenario:
            Requesting tracking info for a file not present in the bundle.

        Execution Flow:
            1. Setup the reader with two tracked files.
            2. Call get_file_tracking for "missing.py".
            3. Assert that the result is None.

        Expectations:
            - Missing files resolve to None.
        """
        reader = self._setup(tmp_path)
        assert reader.get_file_tracking("missing.py") is None

    def test_file_id_for_path(self, tmp_path):
        """Verify file_id_for_path resolves the integer file ID for a given file path.

        Scenario:
            A path to file ID lookup is performed.

        Execution Flow:
            1. Setup the reader with "a.py" (ID 1) and "b.py" (ID 2).
            2. Call file_id_for_path for "a.py", "b.py", and a missing file "c.py".
            3. Assert the IDs are 1, 2, and None respectively.

        Expectations:
            - Resolves file path to its correct integer file ID.
            - Returns None for missing paths.
        """
        reader = self._setup(tmp_path)
        assert reader.file_id_for_path("a.py") == 1
        assert reader.file_id_for_path("b.py") == 2
        assert reader.file_id_for_path("c.py") is None

    def test_get_unindexed_files(self, tmp_path):
        """Verify get_unindexed_files_with_details returns only files marked as not indexed.

        Scenario:
            One file is indexed, and another file is not indexed in the tracking table.

        Execution Flow:
            1. Commit tracking records: "a.py" (indexed=True), "b.py" (indexed=False).
            2. Initialize BathoBundleReader.
            3. Call get_unindexed_files_with_details.
            4. Verify that the returned list contains 1 item matching "b.py".

        Expectations:
            - Correctly filters and retrieves unindexed file details.
        """
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
        """Verify get_all_runs returns all committed runs.

        Scenario:
            Two runs are committed in the bundle.

        Execution Flow:
            1. Setup the reader with two runs committed.
            2. Call get_all_runs.
            3. Assert that the returned list contains 2 runs.

        Expectations:
            - Returns the list of all runs stored in the bundle.
        """
        reader = self._setup(tmp_path)
        runs = reader.get_all_runs()
        assert len(runs) == 2

    def test_get_run_by_uuid(self, tmp_path):
        """Verify get_run retrieves correct details for a given run UUID.

        Scenario:
            Details for run "r1" are requested.

        Execution Flow:
            1. Setup the reader with "r1" committed.
            2. Call get_run for "r1".
            3. Assert the returned dictionary is not None and has run_uuid "r1".

        Expectations:
            - Correctly resolves and returns run metadata by its UUID.
        """
        reader = self._setup(tmp_path)
        run = reader.get_run("r1")
        assert run is not None
        assert run["run_uuid"] == "r1"

    def test_get_run_missing(self, tmp_path):
        """Verify get_run returns None for a non-existent run UUID in a populated bundle.

        Scenario:
            Querying a missing run UUID.

        Execution Flow:
            1. Setup the reader.
            2. Call get_run for "r999".
            3. Assert that the result is None.

        Expectations:
            - Returns None for missing run UUIDs.
        """
        reader = self._setup(tmp_path)
        assert reader.get_run("r999") is None

    def test_get_latest_run_id_from_manifest(self, tmp_path):
        """Verify get_latest_run_id returns the UUID of the latest run committed in the manifest.

        Scenario:
            Multiple runs are committed and the latest is registered in the manifest.

        Execution Flow:
            1. Setup the reader with "r2" committed as the latest run.
            2. Call get_latest_run_id.
            3. Assert that the returned UUID is "r2".

        Expectations:
            - The latest run UUID is correctly resolved.
        """
        reader = self._setup(tmp_path)
        assert reader.get_latest_run_id() == "r2"

    def test_get_run_internal_id(self, tmp_path):
        """Verify get_run_internal_id resolves the internal integer run ID for a given run UUID.

        Scenario:
            Mapping run UUID string to its primary key/row index in the Arrow Bundle.

        Execution Flow:
            1. Setup the reader with runs "r1" and "r2" committed.
            2. Call get_run_internal_id for "r1", "r2", and "rX".
            3. Assert the returned IDs are 1, 2, and None respectively.

        Expectations:
            - Correctly maps run UUID strings to their integer database IDs.
        """
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
        """Verify the offset index is built correctly for slicing table records by file ID.

        Scenario:
            Multiple agent views are committed, grouped by file ID.

        Execution Flow:
            1. Setup reader with agent views for file IDs 1, 2, and 3.
            2. Retrieve the "agent_views" table.
            3. Inspect reader._indices["agent_views"].
            4. Assert that the slices mapped to file IDs 1, 2, and 3 are correct.

        Expectations:
            - The offset index maps file IDs to precise slices of the underlying table.
        """
        reader = self._setup_agent_views(tmp_path)
        table = reader._get_table("agent_views")
        assert table.num_rows == 6
        idx = reader._indices["agent_views"]
        assert idx[1] == slice(0, 2)
        assert idx[2] == slice(2, 3)
        assert idx[3] == slice(3, 6)

    def test_get_file_artifacts_by_id_file1(self, tmp_path):
        """Verify get_file_artifacts_by_id retrieves artifacts specifically matching file ID 1.

        Scenario:
            Querying agent views for file ID 1.

        Execution Flow:
            1. Setup reader with agent views.
            2. Call get_file_artifacts_by_id for file ID 1.
            3. Verify the length of the returned agent views list is 2, matching entity IDs "e1" and "e2".

        Expectations:
            - Only artifacts matching file ID 1 are returned.
        """
        reader = self._setup_agent_views(tmp_path)
        result = reader.get_file_artifacts_by_id(1)
        assert len(result["agent_view"]) == 2
        assert {r["entity_id"] for r in result["agent_view"]} == {"e1", "e2"}

    def test_get_file_artifacts_by_id_file3(self, tmp_path):
        """Verify get_file_artifacts_by_id retrieves artifacts specifically matching file ID 3.

        Scenario:
            Querying agent views for file ID 3.

        Execution Flow:
            1. Setup reader with agent views.
            2. Call get_file_artifacts_by_id for file ID 3.
            3. Verify the length of the returned agent views list is 3.

        Expectations:
            - Only artifacts matching file ID 3 are returned.
        """
        reader = self._setup_agent_views(tmp_path)
        result = reader.get_file_artifacts_by_id(3)
        assert len(result["agent_view"]) == 3

    def test_get_file_artifacts_missing_file_id(self, tmp_path):
        """Verify get_file_artifacts_by_id returns empty lists when requesting artifacts for a missing file ID.

        Scenario:
            Querying artifacts for file ID 99 which has no records.

        Execution Flow:
            1. Setup reader with agent views.
            2. Call get_file_artifacts_by_id for file ID 99.
            3. Assert that the returned agent views list is empty.

        Expectations:
            - Gracefully returns empty results for file IDs not present in the index.
        """
        reader = self._setup_agent_views(tmp_path)
        result = reader.get_file_artifacts_by_id(99)
        assert result["agent_view"] == []


# ---------------------------------------------------------------------------
# Invalidation
# ---------------------------------------------------------------------------

class TestInvalidation:
    def test_invalidate_single_table_forces_reread(self, tmp_path):
        """Verify invalidate(table_name) clears the cache for a single table, forcing a reread.

        Scenario:
            An active file tracking table changes and we invalidate its reader cache.

        Execution Flow:
            1. Commit initial tracking record.
            2. Initialize reader and load hashes (caches table).
            3. Commit updated tracking record with an additional file.
            4. Call invalidate("file_tracking").
            5. Verify the table is removed from cache and that subsequent reads fetch the new records.

        Expectations:
            - The single table cache is successfully cleared.
            - New reads fetch fresh database values from disk.
        """
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
        """Verify calling invalidate() without arguments clears the cache for all tables.

        Scenario:
            Reader has multiple tables cached.

        Execution Flow:
            1. Setup reader and query both file hashes and runs (caching both tables).
            2. Verify 2 tables are in cache.
            3. Call invalidate().
            4. Assert that the tables cache and indices cache are completely cleared.

        Expectations:
            - All cached tables and indices are purged.
        """
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

