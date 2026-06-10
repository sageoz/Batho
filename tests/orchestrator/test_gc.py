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
        """Verify that running the GC status command on a valid bundle returns successfully.

        Scenario:
            A bundle exists with at least one completed run, and the GC 'status' command is executed.

        Execution Flow:
            1. Bootstrap a bundle with one completed run.
            2. Run GC with GCOptions command set to 'status'.
            3. Verify the operation succeeds and contains "Arrow generation" in the output message.

        Expectations:
            - The GC status execution succeeds.
            - The status message provides details about the current generation of Arrow files.
        """
        _make_bundle_with_run(tmp_path)
        opts = GCOptions(root=tmp_path, command="status")
        result = run_gc(opts)
        assert result["success"]
        assert "Arrow generation" in result["message"]

    def test_status_missing_bundle(self, tmp_path):
        """Verify that running GC status on a directory without a bundle returns an error.

        Scenario:
            An empty directory has no Batho bundle, and a GC 'status' command is run.

        Execution Flow:
            1. Define GCOptions pointing to an empty temporary directory.
            2. Execute GC status.
            3. Verify the operation fails and the output message states "No artifact bundle".

        Expectations:
            - The GC status run fails.
            - The failure message indicates the bundle was not found.
        """
        opts = GCOptions(root=tmp_path, command="status")
        result = run_gc(opts)
        assert not result["success"]
        assert "No artifact bundle" in result["message"]


class TestGCDeleteRun:
    def test_delete_existing_run(self, tmp_path):
        """Verify that deleting an existing run via GC succeeds and removes the run.

        Scenario:
            A bundle exists with a specific run UUID, and GC 'run' delete command is called for that UUID.

        Execution Flow:
            1. Bootstrap a bundle with a test run UUID.
            2. Execute GC with command set to 'run' and the target run UUID.
            3. Verify the GC command succeeds.
            4. Reopen the bundle and query the deleted run UUID.
            5. Assert that the run is no longer present.

        Expectations:
            - The run deletion operation succeeds.
            - The database no longer contains records for the deleted run.
        """
        _, run_uuid = _make_bundle_with_run(tmp_path)
        opts = GCOptions(root=tmp_path, command="run", run_uuid=run_uuid)
        result = run_gc(opts)
        assert result["success"]

        db = BathoBundle(tmp_path)
        assert db.get_run(run_uuid) is None

    def test_delete_nonexistent_run(self, tmp_path):
        """Verify that attempting to delete a nonexistent run returns an error.

        Scenario:
            GC delete run command is executed for a UUID that does not exist in the bundle.

        Execution Flow:
            1. Bootstrap a bundle.
            2. Execute GC with command set to 'run' and a nonexistent run UUID.
            3. Assert that the command failed.
            4. Check that the error message indicates the run was not found.

        Expectations:
            - The run deletion fails.
            - An error message is returned specifying that the run was not found.
        """
        _make_bundle_with_run(tmp_path)
        opts = GCOptions(root=tmp_path, command="run", run_uuid="nonexistent_run")
        result = run_gc(opts)
        assert not result["success"]
        assert "not found" in result["message"].lower()

    def test_delete_run_missing_uuid(self, tmp_path):
        """Verify that attempting to delete a run without providing a UUID returns an error.

        Scenario:
            GC run deletion command is invoked with run_uuid set to None.

        Execution Flow:
            1. Bootstrap a bundle.
            2. Execute GC with command set to 'run' and run_uuid set to None.
            3. Assert that the command fails.

        Expectations:
            - The GC command reports a failure.
        """
        _make_bundle_with_run(tmp_path)
        opts = GCOptions(root=tmp_path, command="run", run_uuid=None)
        result = run_gc(opts)
        assert not result["success"]


class TestGCVacuum:
    def test_vacuum_removes_orphans(self, tmp_path):
        """Verify that the GC vacuum command deletes orphan IPC files.

        Scenario:
            An orphan IPC file (not registered in the active manifest) is placed in the bundle directory.

        Execution Flow:
            1. Bootstrap a bundle and get its directory.
            2. Write a dummy/fake orphan IPC file to the bundle directory.
            3. Execute GC with command set to 'vacuum'.
            4. Verify the GC command succeeds.
            5. Check if the orphan file was deleted.

        Expectations:
            - The vacuum command finishes successfully.
            - The orphan IPC file is deleted from the disk.
        """
        db, run_uuid = _make_bundle_with_run(tmp_path)
        bundle_dir = resolve_bundle_dir(tmp_path)

        orphan = bundle_dir / "agent_views.v999.ipc"
        orphan.write_bytes(b"fake")

        opts = GCOptions(root=tmp_path, command="vacuum")
        result = run_gc(opts)
        assert result["success"]
        assert not orphan.exists()

    def test_orphans_subcommand(self, tmp_path):
        """Verify that the GC orphans command identifies stale IPC files.

        Scenario:
            An orphan IPC file exists in the bundle directory, and the 'orphans' status command is executed.

        Execution Flow:
            1. Bootstrap a bundle and create an orphan IPC file in the bundle directory.
            2. Execute GC with command set to 'orphans'.
            3. Verify the command succeeds.
            4. Assert that the returned message references the stale IPC file.

        Expectations:
            - The command reports success.
            - The output lists the stale/orphan IPC file.
        """
        _make_bundle_with_run(tmp_path)
        bundle_dir = resolve_bundle_dir(tmp_path)
        (bundle_dir / "rels_views.v888.ipc").write_bytes(b"stale")

        opts = GCOptions(root=tmp_path, command="orphans")
        result = run_gc(opts)
        assert result["success"]
        assert "stale IPC file" in result["message"]


class TestGCPruneOldRuns:
    def test_prune_no_old_runs(self, tmp_path):
        """Verify that pruning old runs does not delete new runs.

        Scenario:
            A run was just created, and the GC 'runs' pruning command is run with a large older_than threshold.

        Execution Flow:
            1. Bootstrap a bundle with a new run.
            2. Run GC with command set to 'runs' and older_than set to 365 days.
            3. Verify the command succeeds and reports "No runs found" to prune.

        Expectations:
            - Pruning succeeds without deleting the recently created run.
        """
        _make_bundle_with_run(tmp_path)
        opts = GCOptions(root=tmp_path, command="runs", older_than=365)
        result = run_gc(opts)
        assert result["success"]
        assert "No runs found" in result["message"]

    def test_prune_invalid_threshold(self, tmp_path):
        """Verify that pruning with an invalid negative threshold returns an error.

        Scenario:
            The GC 'runs' pruning command is executed with an older_than parameter of -1.

        Execution Flow:
            1. Bootstrap a bundle.
            2. Execute GC with command set to 'runs' and older_than set to -1.
            3. Assert that the operation failed.

        Expectations:
            - The pruning run returns success as False.
        """
        _make_bundle_with_run(tmp_path)
        opts = GCOptions(root=tmp_path, command="runs", older_than=-1)
        result = run_gc(opts)
        assert not result["success"]


class TestGCUnknownCommand:
    def test_unknown_command(self, tmp_path):
        """Verify that executing an unknown GC command returns a failure.

        Scenario:
            GC command is invoked with a non-existent sub-command.

        Execution Flow:
            1. Bootstrap a bundle.
            2. Execute GC command with command set to 'noop'.
            3. Assert that the operation failed.
            4. Verify the message points out "Unknown gc command".

        Expectations:
            - The GC run fails due to an invalid command.
        """
        _make_bundle_with_run(tmp_path)
        opts = GCOptions(root=tmp_path, command="noop")
        result = run_gc(opts)
        assert not result["success"]
        assert "Unknown gc command" in result["message"]
