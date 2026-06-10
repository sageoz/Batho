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
        """Verify resolve_bundle_dir returns the resolved path to the `.batho/artifact` subdirectory.

        Scenario:
            A temporary path is provided as the project root directory.

        Execution Flow:
            1. Call resolve_bundle_dir with the root path.
            2. Verify that the returned path is the absolute path to `<root>/.batho/artifact`.

        Expectations:
            - The returned path points to the correct subfolder.
            - The path is resolved to its absolute representation.
        """
        bundle_dir = resolve_bundle_dir(tmp_path)
        assert bundle_dir == (tmp_path / ".batho" / "artifact").resolve()

    def test_consistent_across_calls(self, tmp_path):
        """Verify resolve_bundle_dir returns consistent paths across multiple invocations for the same root.

        Scenario:
            A root path is provided for resolution multiple times.

        Execution Flow:
            1. Call resolve_bundle_dir multiple times with the same path.
            2. Compare the returned paths.

        Expectations:
            - The returned paths are identical.
        """
        assert resolve_bundle_dir(tmp_path) == resolve_bundle_dir(tmp_path)

    def test_different_roots_different_dirs(self, tmp_path):
        """Verify resolve_bundle_dir yields distinct artifact directories for different project roots.

        Scenario:
            Two distinct project directories are created under the temp path.

        Execution Flow:
            1. Create two subdirectories in tmp_path.
            2. Resolve the artifact directory for both.
            3. Verify that the returned paths are different.

        Expectations:
            - Different roots map to separate artifact directories.
        """
        a = tmp_path / "proj_a"
        b = tmp_path / "proj_b"
        a.mkdir(); b.mkdir()
        assert resolve_bundle_dir(a) != resolve_bundle_dir(b)

    def test_str_input_accepted(self, tmp_path):
        """Verify resolve_bundle_dir accepts a string representation of the root directory path.

        Scenario:
            A string path representing the root directory is passed instead of a Path object.

        Execution Flow:
            1. Convert tmp_path to a string.
            2. Call resolve_bundle_dir with the string.
            3. Verify that the returned value is a Path instance.

        Expectations:
            - The function accepts string arguments without errors.
            - The return type is always a Path object.
        """
        bundle_dir = resolve_bundle_dir(str(tmp_path))
        assert isinstance(bundle_dir, Path)


class TestGetBundle:
    def test_returns_batho_bundle(self, tmp_path):
        """Verify get_bundle returns a BathoBundle instance.

        Scenario:
            A workspace root is specified for resolving a BathoBundle.

        Execution Flow:
            1. Call get_bundle with the root path.
            2. Assert that the return value is an instance of BathoBundle.

        Expectations:
            - A valid BathoBundle instance is instantiated and returned.
        """
        db = get_bundle(tmp_path)
        assert isinstance(db, BathoBundle)

    def test_creates_artifact_dir(self, tmp_path):
        """Verify get_bundle automatically creates the `.batho/artifact` subdirectory if it doesn't exist.

        Scenario:
            get_bundle is called on a directory that does not yet contain a `.batho` folder.

        Execution Flow:
            1. Call get_bundle with the root path.
            2. Assert that the `.batho/artifact` directory has been created.

        Expectations:
            - The underlying artifact folder structure is initialized on disk.
        """
        get_bundle(tmp_path)
        assert (tmp_path / ".batho" / "artifact").exists()


# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------

class TestRunLifecycle:
    def test_create_and_complete_run(self, tmp_path):
        """Verify creating and completing a run persists the run state in the bundle.

        Scenario:
            A BathoBundle is initialized, and a run is created, updated, and completed.

        Execution Flow:
            1. Create a run with a specific UUID "r1" and verify the integer run ID is 1.
            2. Call complete_run with some entity and file counts.
            3. Instantiate a new BathoBundle pointing to the same folder and retrieve "r1".
            4. Verify the status is "completed" and counts are correct.

        Expectations:
            - The run is successfully recorded.
            - Run metadata is persisted and can be reloaded by a new bundle instance.
        """
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
        """Verify failing a run records the error message and sets the status to failed.

        Scenario:
            A run is created and then marked as failed with a custom error message.

        Execution Flow:
            1. Create a run with UUID "r_fail".
            2. Call fail_run with an error message "boom".
            3. Reload the bundle and retrieve the run details.
            4. Assert that the status is "failed" and the error message matches "boom".

        Expectations:
            - Failed runs are correctly persisted with a status of "failed".
            - The error message details are recorded in the database.
        """
        db = _new_bundle(tmp_path)
        db.create_run("r_fail")
        db.fail_run("r_fail", error_message="boom")

        db2 = _new_bundle(tmp_path)
        run = db2.get_run("r_fail")
        assert run["status"] == "failed"
        assert run["error_message"] == "boom"

    def test_get_latest_run_id(self, tmp_path):
        """Verify get_latest_run_id returns the UUID of the most recently completed run.

        Scenario:
            Multiple runs are created and completed sequentially.

        Execution Flow:
            1. Create and complete run "r1".
            2. Create and complete run "r2".
            3. Reload the bundle and query the latest run ID.
            4. Assert that "r2" is returned.

        Expectations:
            - The latest completed run UUID is resolved correctly.
        """
        db = _new_bundle(tmp_path)
        db.create_run("r1")
        db.complete_run("r1")
        db.create_run("r2")
        db.complete_run("r2")

        db2 = _new_bundle(tmp_path)
        assert db2.get_latest_run_id() == "r2"

    def test_get_run_internal_id(self, tmp_path):
        """Verify get_run_internal_id resolves the integer run ID for a given run UUID.

        Scenario:
            A run is created, completed, and its internal integer ID needs to be queried.

        Execution Flow:
            1. Create and complete run "r1".
            2. Reload the bundle and fetch the internal ID of "r1".
            3. Assert that the returned ID matches the created run's primary key (1).

        Expectations:
            - Run UUID to internal run ID mapping works correctly.
        """
        db = _new_bundle(tmp_path)
        db.create_run("r1")
        db.complete_run("r1")

        db2 = _new_bundle(tmp_path)
        assert db2.get_run_internal_id("r1") == 1

    def test_multiple_sequential_runs(self, tmp_path):
        """Verify multiple sequential runs are saved and can all be retrieved.

        Scenario:
            Three runs are created and completed in succession.

        Execution Flow:
            1. Iterate 3 times, creating and completing runs "r0", "r1", "r2".
            2. Reload the bundle.
            3. Fetch all runs from the reader.
            4. Assert that exactly 3 runs exist.

        Expectations:
            - All runs are successfully appended to the bundle.
        """
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
        """Verify file tracking records can be upserted and retrieved.

        Scenario:
            A file is added to tracking during a run.

        Execution Flow:
            1. Create run "r1".
            2. Upsert a file tracking record for "src/main.py".
            3. Complete run "r1".
            4. Reload the bundle and retrieve all file hashes.
            5. Assert "src/main.py" is in the tracking dictionary with the correct hash.

        Expectations:
            - File tracking records are saved correctly.
            - Hashes are matching the upserted data.
        """
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
        """Verify upserting a file tracking record for an existing file updates the entry.

        Scenario:
            A file is tracked in run "r1", and updated in a subsequent run "r2".

        Execution Flow:
            1. Create run "r1", upsert file tracking with hash "old".
            2. Create run "r2", upsert file tracking for the same file with hash "new".
            3. Reload the bundle and retrieve all file hashes.
            4. Assert that the file has the new hash "new".

        Expectations:
            - Subsequent updates overwrite existing file tracking entries.
            - The most recent tracking details are returned.
        """
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
        """Verify get_all_file_tracking returns all records as a dictionary.

        Scenario:
            Multiple files are added to file tracking and completed in a run.

        Execution Flow:
            1. Run lifecycle with two files "a.py" and "b.py".
            2. Reload bundle and call get_all_file_tracking().
            3. Verify that the result is a dict containing 2 items.

        Expectations:
            - A dictionary representation of file tracking is successfully returned.
        """
        db = _new_bundle(tmp_path)
        _run_lifecycle(db, "r1", ["a.py", "b.py"])

        db2 = _new_bundle(tmp_path)
        tracking = db2.get_all_file_tracking()
        assert isinstance(tracking, dict)
        assert len(tracking) == 2

    def test_delete_file_tracking(self, tmp_path):
        """Verify delete_file_tracking purges a file tracking record.

        Scenario:
            Two files are tracked, and then one of them is deleted.

        Execution Flow:
            1. Run lifecycle with files "a.py" and "b.py".
            2. Reload bundle and delete file tracking for "a.py".
            3. Reload bundle again, get all file tracking records.
            4. Assert that "a.py" is no longer tracked while "b.py" is.

        Expectations:
            - Specific file tracking records can be deleted successfully.
        """
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
        """Verify record_file_changelog records entity changes and they can be retrieved.

        Scenario:
            A run is executed, tracking a file with a diff recorded in the changelog.

        Execution Flow:
            1. Create run "r1".
            2. Upsert file tracking for "a.py" and get/create its file ID.
            3. Record file changelog diff for the file ID and entity "e1".
            4. Complete run "r1".
            5. Reload bundle, fetch the raw file changelog, and assert at least 1 entry is present.

        Expectations:
            - Changelog details are correctly persisted in the bundle.
        """
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
        """Verify get_file_node_history returns history records for a specific entity.

        Scenario:
            Changelog records are saved for a specific entity.

        Execution Flow:
            1. Create run "r1", upsert file tracking, and record a changelog diff for entity "ent_x".
            2. Complete the run.
            3. Reload bundle and fetch node history for "ent_x".
            4. Assert history contains at least one record matching entity ID "ent_x".

        Expectations:
            - Entity change history is successfully retrieved by entity ID.
        """
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
        """Verify run artifacts can be finalized and retrieved by run ID.

        Scenario:
            Run artifacts (e.g. overview, telemetry) are finalized for a completed run.

        Execution Flow:
            1. Create run "r1".
            2. Call finalize_run_artifacts with custom metadata.
            3. Complete the run.
            4. Reload bundle, retrieve artifacts using the run ID, and assert correctness.

        Expectations:
            - Run artifacts are saved and associated with the correct run ID.
        """
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
        """Verify get_run_artifacts returns None if the run ID does not exist.

        Scenario:
            Querying run artifacts for a non-existent run ID.

        Execution Flow:
            1. Initialize bundle.
            2. Call get_run_artifacts with run ID 999.
            3. Verify that the result is None.

        Expectations:
            - Returns None when no matching run artifacts are found.
        """
        db = _new_bundle(tmp_path)
        assert db.get_run_artifacts(999) is None


# ---------------------------------------------------------------------------
# Bundle isolation — two independent roots
# ---------------------------------------------------------------------------

class TestBundleIsolation:
    def test_two_roots_independent(self, tmp_path):
        """Verify separate bundle roots operate independently.

        Scenario:
            Two distinct project directories are created, each with its own BathoBundle.

        Execution Flow:
            1. Initialize two BathoBundles in project_a and project_b.
            2. Perform runs and track "a.py" in project_a, "b.py" in project_b.
            3. Verify that checking project_a only returns "a.py" and project_b only returns "b.py".

        Expectations:
            - Complete data isolation between different bundle roots.
        """
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
        """Verify that a meta.json manifest is created in the bundle directory after a run.

        Scenario:
            A run is completed in a fresh BathoBundle.

        Execution Flow:
            1. Initialize BathoBundle and run lifecycle with "main.py".
            2. Verify that the meta.json file exists in the resolved bundle directory.

        Expectations:
            - meta.json manifest is automatically generated and saved.
        """
        db = _new_bundle(tmp_path)
        _run_lifecycle(db, "r1", ["main.py"])
        assert (resolve_bundle_dir(tmp_path) / "meta.json").exists()


class TestBundleFacadeAdvanced:
    """Advanced scenarios and edge cases tested on the public BathoBundle facade."""

    def test_file_id_max_calculation(self, tmp_path: Path):
        """Verify that _compute_next_file_id correctly identifies the max file ID on unsorted tracking tables.

        Scenario:
            When new files are added, Batho needs to allocate the next incremental `file_id`.
            If the tracking records in `file_tracking.v1.ipc` are not sorted by ID (e.g. [5, 2, 9, 3]),
            the generator must find the mathematical maximum (`9`) and return `10`, rather than blindly
            taking the last entry's ID + 1 (which would be `3 + 1 = 4`, leading to ID collision).

        Execution Flow:
            1. Initialize `BathoBundle`.
            2. Write an unsorted IPC file for `file_tracking` containing IDs [5, 2, 9, 3].
            3. Mock `bundle._active_or_empty` to return this file path for table "file_tracking".
            4. Assert that `bundle._compute_next_file_id()` returns `10`.

        Expectations:
            - Safe incremental file ID generation.
            - Robustness against unsorted Arrow database rows.
        """
        import pyarrow as pa
        import pyarrow.ipc as ipc
        
        bundle = BathoBundle(tmp_path)
        
        # Create an unsorted file_tracking table (file_id: 5 then 2 then 9 then 3)
        schema = pa.schema([
            pa.field("file_id", pa.int64()),
            pa.field("file_path", pa.utf8()),
            pa.field("content_hash", pa.utf8()),
            pa.field("size", pa.int64()),
            pa.field("is_indexed", pa.bool_()),
            pa.field("updated_at", pa.utf8())
        ])
        
        table = pa.Table.from_pydict({
            "file_id": [5, 2, 9, 3],
            "file_path": ["a.py", "b.py", "c.py", "d.py"],
            "content_hash": ["h5", "h2", "h9", "h3"],
            "size": [10, 10, 10, 10],
            "is_indexed": [True, True, True, True],
            "updated_at": ["now", "now", "now", "now"]
        }, schema=schema)
        
        # Write to file_tracking table path
        p = bundle.artifact_dir / "file_tracking.v1.ipc"
        with ipc.new_file(str(p), schema) as w:
            w.write_table(table)
            
        # Mock active path
        bundle._active_or_empty = lambda name: p if name == "file_tracking" else None
        
        # Max file ID is 9, next should be 10 (not 3 + 1 = 4)
        assert bundle._compute_next_file_id() == 10

    def test_run_artifacts_specific_run(self, tmp_path: Path):
        """Verify that get_run_artifacts resolves and returns artifacts for the specific requested run.

        Scenario:
            Multiple runs are registered. When calling `get_run_artifacts(run_id)`, the bundle facade
            must explicitly query and retrieve data for that precise run ID, rather than fetching whichever
            is latest or default.

        Execution Flow:
            1. Initialize `BathoBundle`.
            2. Create `run-1`, finalize metadata `{"context_overview": {"run": 1}}` and complete it.
            3. Create `run-2`, finalize metadata `{"context_overview": {"run": 2}}` and complete it.
            4. Assert that `bundle.get_run_artifacts(rid1)` returns `run 1` metadata.
            5. Assert that `bundle.get_run_artifacts(rid2)` returns `run 2` metadata.

        Expectations:
            - Multi-run history resolution is accurate and isolated per run.
        """
        bundle = BathoBundle(tmp_path)
        
        # Create two runs
        rid1 = bundle.create_run("run-uuid-1")
        bundle.finalize_run_artifacts(rid1, {"context_overview": {"run": 1}})
        bundle.complete_run("run-uuid-1")
        
        rid2 = bundle.create_run("run-uuid-2")
        bundle.finalize_run_artifacts(rid2, {"context_overview": {"run": 2}})
        bundle.complete_run("run-uuid-2")
        
        # Retrieve artifacts for run 1 explicitly
        art1 = bundle.get_run_artifacts(rid1)
        assert art1 is not None
        assert art1["context_overview"]["run"] == 1
        
        # Retrieve artifacts for run 2 explicitly
        art2 = bundle.get_run_artifacts(rid2)
        assert art2 is not None
        assert art2["context_overview"]["run"] == 2

    def test_path_separator_normalization(self, tmp_path: Path):
        """Verify that Windows-style path separators are normalized to POSIX forward slashes.

        Scenario:
            Files indexed on a Windows machine have paths like `src\\nested\\module.py`.
            Batho must normalize these path separators to forward slashes `src/nested/module.py`
            across all database lookups, updates, and tracking deletions, ensuring cross-platform database compatibility.

        Execution Flow:
            1. Initialize `BathoBundle`.
            2. Upsert file tracking for `src\\nested\\module.py`.
            3. Assert that lookup via `win_path` (`src\\nested\\module.py`) and `posix_path` (`src/nested/module.py`)
               both return the POSIX normalized representation.
            4. Verify that delete operations using `win_path` successfully purge the posix tracking entry.

        Expectations:
            - Paths stored in the Arrow database are 100% normalized to POSIX styling.
            - Path separator normalization occurs seamlessly inside public API boundaries.
        """
        bundle = BathoBundle(tmp_path)
        
        # Create and flush a run so files are written to disk
        run_uuid = "run_path_sep"
        bundle.create_run(run_uuid, root_path=str(tmp_path))
        
        win_path = "src\\nested\\module.py"
        posix_path = "src/nested/module.py"
        
        # Insert some tracking records
        records = [{
            "file_path": win_path,
            "content_hash": "abc",
            "is_indexed": True,
            "last_run_id": run_uuid,
            "mtime_ns": 12345,
            "size": 100
        }]
        
        bundle.upsert_file_tracking(records)
        bundle.complete_run(run_uuid)
        
        # Check that it is tracked under the posix path
        tracking = bundle.get_file_tracking(win_path)
        assert tracking is not None
        assert tracking["file_path"] == posix_path
        
        tracking_direct = bundle.get_file_tracking(posix_path)
        assert tracking_direct is not None
        assert tracking_direct["file_path"] == posix_path
        
        # Verify get_file_artifacts also normalizes paths
        artifacts = bundle.get_file_artifacts("some-run", win_path)
        assert isinstance(artifacts, list)
        
        # Verify delete_file_tracking normalizes paths
        # Create another run to delete file tracking (requires active run write lock)
        del_run = "run_del"
        bundle.create_run(del_run, root_path=str(tmp_path))
        bundle.delete_file_tracking(win_path)
        bundle.complete_run(del_run)
        assert bundle.get_file_tracking(posix_path) is None

    def test_changelog_base_uuid_resolution(self, tmp_path: Path):
        """Verify that record_file_changelog resolves the base run UUID correctly from history.

        Scenario:
            When storing a patch changelog, the database references run integer IDs (`run_id`).
            The changelog logger must resolve the corresponding base run UUID string (`base_run_uuid`)
            from historical runs in SQLite, ensuring correct linkage of incremental graph patches.

        Execution Flow:
            1. Initialize `BathoBundle`.
            2. Mock historical completed runs (`first-uuid`, `second-uuid`).
            3. Call `record_file_changelog(run_id=3, base_run_id=2, diffs=...)` referencing historical `base_run_id=2`.
            4. Verify that the recorded changelog row has correctly mapped `base_run_uuid` to `second-uuid`.

        Expectations:
            - Correct mapping from SQLite incremental primary key IDs to public UUID strings.
        """
        bundle = BathoBundle(tmp_path)
        
        # Mock self._reader.get_all_runs()
        mock_runs = [
            {"run_uuid": "first-uuid", "status": "completed"},
            {"run_uuid": "second-uuid", "status": "completed"}
        ]
        bundle._reader.get_all_runs = lambda: mock_runs

        # Simulate active run rows
        bundle._run_rows = [{"run_uuid": "active-uuid"}]

        # Record changelog with base_run_id = 2 (second-uuid)
        diffs = [{"file_path": "foo.py", "entity_id": "ent1", "change_kind": "modified"}]
        bundle.record_file_changelog(run_id=3, base_run_id=2, diffs=diffs)

        assert len(bundle._changelog_rows) == 1
        assert bundle._changelog_rows[0]["run_uuid"] == "active-uuid"
        assert bundle._changelog_rows[0]["base_run_uuid"] == "second-uuid"

