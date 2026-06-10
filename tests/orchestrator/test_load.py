"""Tests for batho load orchestrator — pack/unpack round-trip."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from batho.modules.storage.arrow_bundle import BathoBundle, resolve_bundle_dir
from batho.modules.storage.arrow_bundle.manager import BathoBundleManager
from batho.modules.storage.arrow_bundle.writer import write_simple_ipc
from batho.modules.storage.arrow_bundle.schemas import BUNDLE_SCHEMA_VERSION, RUNS_SCHEMA
from batho.orchestrator.load import LoadOptions, LoadResult, run_load


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_minimal_bundle(artifact_dir: Path) -> BathoBundleManager:
    """Create a one-run bundle and return its manager."""
    mgr = BathoBundleManager(artifact_dir)
    row = {
        "run_uuid": "build_001",
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "started_at": "2024-01-01T00:00:00Z",
        "completed_at": "2024-01-01T00:00:01Z",
        "status": "completed",
        "git_commit": None, "git_branch": None,
        "root_path": "/test/repo",
        "entity_count": 2, "rel_count": 1,
        "file_count": 1, "duration_ms": 200, "error_message": None,
    }
    tmp = artifact_dir / "runs.tmp.ipc"
    write_simple_ipc([row], RUNS_SCHEMA, tmp)
    mgr.commit_patch({"runs": tmp}, "build_001")
    return mgr


def _export_bundle(src_root: Path) -> Path:
    """Build a bundle under src_root and export a ZIP; return ZIP path."""
    artifact_dir = resolve_bundle_dir(src_root)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    mgr = _build_minimal_bundle(artifact_dir)
    zip_path = src_root / "export.batho"
    mgr.export_artifact(zip_path)
    return zip_path


# ---------------------------------------------------------------------------
# run_load success path
# ---------------------------------------------------------------------------

class TestRunLoadSuccess:
    def test_load_populates_bundle_dir(self, tmp_path):
        """Verify that load successfully populates the destination bundle directory.

        Scenario:
            An exported bundle ZIP package is loaded into a clean destination directory.

        Execution Flow:
            1. Create a source directory and export a minimal bundle ZIP into it.
            2. Create a clean destination directory.
            3. Run `run_load` on the destination directory with the exported ZIP.
            4. Verify that the operation succeeds and a meta.json file exists in the destination.

        Expectations:
            - The load operation returns success.
            - The destination bundle directory contains the unpacked meta.json metadata file.
        """
        src = tmp_path / "src"
        src.mkdir()
        zip_path = _export_bundle(src)

        dst_root = tmp_path / "dst"
        dst_root.mkdir()

        result = run_load(LoadOptions(root=dst_root, artifact_path=zip_path))
        assert result.success, result.message
        assert (resolve_bundle_dir(dst_root) / "meta.json").exists()

    def test_load_result_has_correct_tables_count(self, tmp_path):
        """Verify that the load operation returns the correct count of loaded tables.

        Scenario:
            A bundle is exported to ZIP and then loaded, and the table load count is inspected.

        Execution Flow:
            1. Export a minimal bundle ZIP from the source directory.
            2. Run `run_load` targeting a destination directory.
            3. Assert that the operation succeeded.
            4. Verify that `tables_loaded` in the result is at least 1.

        Expectations:
            - The load result indicates success.
            - The number of tables successfully loaded is 1 or more.
        """
        src = tmp_path / "src"
        src.mkdir()
        zip_path = _export_bundle(src)

        dst_root = tmp_path / "dst"
        dst_root.mkdir()

        result = run_load(LoadOptions(root=dst_root, artifact_path=zip_path))
        assert result.success
        assert result.tables_loaded >= 1

    def test_load_result_has_generation(self, tmp_path):
        """Verify that the load result returns a valid bundle generation.

        Scenario:
            A bundle ZIP package is loaded, and the generation attribute of the LoadResult is checked.

        Execution Flow:
            1. Export a minimal bundle ZIP from the source directory.
            2. Run `run_load` targeting a destination directory.
            3. Verify the generation in the result is greater than or equal to 1.

        Expectations:
            - The load result contains a valid generation integer (>= 1).
        """
        src = tmp_path / "src"
        src.mkdir()
        zip_path = _export_bundle(src)

        dst_root = tmp_path / "dst"
        dst_root.mkdir()

        result = run_load(LoadOptions(root=dst_root, artifact_path=zip_path))
        assert result.generation >= 1

    def test_loaded_bundle_is_readable(self, tmp_path):
        """Verify that the loaded bundle can be successfully read and queried.

        Scenario:
            A bundle ZIP package is loaded into a destination directory, and then the BathoBundle reader is used to read the data.

        Execution Flow:
            1. Export a minimal bundle ZIP.
            2. Run `run_load` targeting a destination directory.
            3. Instanciate a `BathoBundle` on the destination directory.
            4. Query all runs from the database and check if the runs array length is 1 and the run UUID is 'build_001'.

        Expectations:
            - The database is readable post-load.
            - The runs table contains the correct, matching run details bootstrapped during export.
        """
        src = tmp_path / "src"
        src.mkdir()
        zip_path = _export_bundle(src)

        dst_root = tmp_path / "dst"
        dst_root.mkdir()

        run_load(LoadOptions(root=dst_root, artifact_path=zip_path))

        db = BathoBundle(dst_root)
        runs = db._reader.get_all_runs()
        assert len(runs) == 1
        assert runs[0]["run_uuid"] == "build_001"

    def test_load_then_export_roundtrip(self, tmp_path):
        """Export -> load into dst -> export again -> load into dst2 -> still readable.

        Scenario:
            Perform a full roundtrip: export a bundle, load it, export the loaded bundle again, and load it into a second directory.

        Execution Flow:
            1. Export the initial minimal bundle ZIP from the source.
            2. Load the ZIP into the first destination directory (dst1).
            3. Export a new ZIP from the first destination directory using `BathoBundleManager`.
            4. Load the second ZIP into a second destination directory (dst2) using `run_load`.
            5. Assert that the second load operation succeeds.
            6. Instantiate `BathoBundle` on dst2 and verify the run is readable and valid.

        Expectations:
            - Both load and export operations succeed in sequence.
            - The final bundle in dst2 remains fully readable with matching run records.
        """
        src = tmp_path / "src"
        src.mkdir()
        zip1 = _export_bundle(src)

        dst1 = tmp_path / "dst1"
        dst1.mkdir()
        run_load(LoadOptions(root=dst1, artifact_path=zip1))

        artifact_dir1 = resolve_bundle_dir(dst1)
        mgr1 = BathoBundleManager(artifact_dir1)
        zip2 = tmp_path / "export2.batho"
        mgr1.export_artifact(zip2)

        dst2 = tmp_path / "dst2"
        dst2.mkdir()
        result2 = run_load(LoadOptions(root=dst2, artifact_path=zip2))
        assert result2.success

        db2 = BathoBundle(dst2)
        assert len(db2._reader.get_all_runs()) == 1


# ---------------------------------------------------------------------------
# run_load error paths
# ---------------------------------------------------------------------------

class TestRunLoadErrors:
    def test_missing_root_fails(self, tmp_path):
        """Verify that trying to load into a non-existent destination directory fails.

        Scenario:
            The load operation is run pointing to a non-existent destination root.

        Execution Flow:
            1. Run `run_load` with a destination root directory path that does not exist.
            2. Verify that the operation returns a failure.
            3. Assert that the failure message reports that the destination does not exist.

        Expectations:
            - The load operation returns success as False.
            - An appropriate error message is returned pointing to the missing directory.
        """
        result = run_load(LoadOptions(
            root=tmp_path / "nonexistent",
            artifact_path=tmp_path / "any.batho",
        ))
        assert not result.success
        assert "does not exist" in result.message

    def test_missing_artifact_fails(self, tmp_path):
        """Verify that loading a non-existent artifact ZIP package fails.

        Scenario:
            The load operation is run with a path to a non-existent ZIP package.

        Execution Flow:
            1. Create a valid destination directory.
            2. Run `run_load` with a non-existent artifact path.
            3. Verify that the operation fails and the message contains "not found".

        Expectations:
            - The load operation fails.
            - The returned message reports that the artifact ZIP file was not found.
        """
        root = tmp_path / "repo"
        root.mkdir()
        result = run_load(LoadOptions(
            root=root,
            artifact_path=tmp_path / "missing.batho",
        ))
        assert not result.success
        assert "not found" in result.message

    def test_existing_bundle_without_force_fails(self, tmp_path):
        """Verify that loading into an already occupied bundle directory without force fails.

        Scenario:
            A load operation is executed on a destination directory that already has a bundle directory.

        Execution Flow:
            1. Export a minimal bundle ZIP.
            2. Load the ZIP into the destination directory.
            3. Attempt to load the same ZIP into the destination directory again without the force option.
            4. Assert that the second load fails and the message contains "already exists".

        Expectations:
            - The second load operation returns success as False.
            - An error is returned indicating that the bundle already exists at the destination.
        """
        src = tmp_path / "src"
        src.mkdir()
        zip_path = _export_bundle(src)

        dst_root = tmp_path / "dst"
        dst_root.mkdir()
        run_load(LoadOptions(root=dst_root, artifact_path=zip_path))

        result = run_load(LoadOptions(root=dst_root, artifact_path=zip_path))
        assert not result.success
        assert "already exists" in result.message

    def test_force_overwrites_existing_bundle(self, tmp_path):
        """Verify that loading with force=True overwrites an already occupied bundle directory.

        Scenario:
            A load operation is executed with force=True on a destination directory that already contains a bundle.

        Execution Flow:
            1. Export a minimal bundle ZIP.
            2. Load the ZIP into the destination directory.
            3. Run `run_load` targeting the same destination directory with the ZIP and `force=True`.
            4. Assert that the second load succeeds.

        Expectations:
            - The force load succeeds and overwrites the existing bundle.
        """
        src = tmp_path / "src"
        src.mkdir()
        zip_path = _export_bundle(src)

        dst_root = tmp_path / "dst"
        dst_root.mkdir()
        run_load(LoadOptions(root=dst_root, artifact_path=zip_path))

        result = run_load(LoadOptions(root=dst_root, artifact_path=zip_path, force=True))
        assert result.success

    def test_bad_zip_schema_version_fails(self, tmp_path):
        """Verify that loading a ZIP package with an invalid schema version fails.

        Scenario:
            A bundle ZIP package is loaded where the manifest.json contains a schema version mismatch.

        Execution Flow:
            1. Export a minimal bundle ZIP.
            2. Copy the ZIP, unpack manifest.json, modify the schema_version to an invalid value, and pack it back.
            3. Run `run_load` targeting a destination directory using the modified ZIP.
            4. Verify that the load fails.
            5. Assert that the returned error message indicates a schema mismatch.

        Expectations:
            - The load fails due to schema version incompatibility.
        """
        import zipfile, json
        src = tmp_path / "src"
        src.mkdir()
        zip_path = _export_bundle(src)

        bad_zip = tmp_path / "bad.batho"
        shutil.copy(zip_path, bad_zip)
        # Rebuild the ZIP replacing manifest.json to avoid duplicate-name warnings
        tmp_zip = bad_zip.with_suffix(".tmp.batho")
        with zipfile.ZipFile(bad_zip, "r") as src_zf, zipfile.ZipFile(tmp_zip, "w") as dst_zf:
            manifest = json.loads(src_zf.read("manifest.json"))
            manifest["schema_version"] = "batho-bundle.v999"
            for item in src_zf.infolist():
                if item.filename != "manifest.json":
                    dst_zf.writestr(item, src_zf.read(item.filename))
            dst_zf.writestr("manifest.json", json.dumps(manifest))
        shutil.move(str(tmp_zip), str(bad_zip))

        dst_root = tmp_path / "dst"
        dst_root.mkdir()
        result = run_load(LoadOptions(root=dst_root, artifact_path=bad_zip))
        assert not result.success
        assert "schema" in result.message.lower() or "mismatch" in result.message.lower()
