"""Tests for bsg/current reconstruction from a packed .batho artifact."""
from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.ipc as ipc
import pytest

from batho.modules.storage.arrow_bundle.bundle import BathoBundle
from batho.modules.storage.arrow_store.compaction import read_ipc
from batho.orchestrator.export import ExportOptions, run_export
from batho.orchestrator.load import LoadOptions, run_load, _reconstruct_bsg_current


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bundle_with_entities(tmp_path: Path) -> tuple[Path, str]:
    """Build a minimal bundle that has agent_views and rels_views populated."""
    db = BathoBundle(tmp_path)
    run_uuid = "bsg_recon_test_001"
    run_id = db.create_run(run_uuid, root_path=str(tmp_path))

    db.insert_file_artifacts_batch(
        run_internal_id=run_id,
        batch_items=[
            {
                "file_path": "src/foo.py",
                "content_hash": "aabbcc",
                "agent_view_data": {
                    "entities": [
                        {
                            "id": "src/foo.py::MyClass",
                            "name": "MyClass",
                            "entity_type": "class",
                            "start_line": 1,
                            "end_line": 20,
                            "fqn": "src.foo.MyClass",
                            "signature": "class MyClass",
                            "is_exported": True,
                        },
                        {
                            "id": "src/foo.py::my_func",
                            "name": "my_func",
                            "entity_type": "function",
                            "start_line": 22,
                            "end_line": 30,
                            "fqn": "src.foo.my_func",
                            "signature": "def my_func()",
                            "is_exported": False,
                        },
                    ]
                },
                "storage_delta_data": {"entities": []},
                "relationships_data": [
                    {
                        "source_id": "src/foo.py::MyClass",
                        "target_id": "src/foo.py::my_func",
                        "relation_type": "contains",
                        "metadata": {},
                    }
                ],
            }
        ],
    )

    db.complete_run(run_uuid, entity_count=2, rel_count=1, file_count=1, duration_ms=10)
    db.close()
    return tmp_path, run_uuid


def _pack_and_load(src: Path, dest: Path) -> None:
    """Pack src → .batho ZIP, then load into dest."""
    zip_path = src / "out.batho"
    run_export(ExportOptions(root=src, output=zip_path))

    dest.mkdir(parents=True, exist_ok=True)
    run_load(LoadOptions(root=dest, artifact_path=zip_path, force=True, rebuild_bsg=True))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBsgCurrentReconstructed:
    def test_bsg_current_dir_exists_after_load(self, tmp_path):
        """Verify that the bsg/current directory is created after loading a bundle.

        Scenario:
            A bundle with entities is exported and then loaded with BSG reconstruction enabled.

        Execution Flow:
            1. Setup a minimal bundle with entity data in the source directory.
            2. Pack the bundle to a ZIP file and load it into a destination directory (with rebuild_bsg=True).
            3. Check if the path `.batho` / `bsg` / `current` exists inside the destination.

        Expectations:
            - The bsg/current directory is successfully created on disk.
        """
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_bundle_with_entities(src)
        _pack_and_load(src, dest)

        current_dir = dest / ".batho" / "bsg" / "current"
        assert current_dir.exists(), "bsg/current/ was not created"

    def test_entity_dict_written(self, tmp_path):
        """Verify that the reconstructed entity dictionary IPC table contains the correct rows.

        Scenario:
            A bundle is loaded with BSG reconstruction enabled, and the resulting entity_dict.ipc is inspected.

        Execution Flow:
            1. Setup a minimal bundle, export it, and load it into the destination.
            2. Locate the `entity_dict.ipc` file in `.batho/bsg/current`.
            3. Assert that the file exists, read its contents into a table, and verify it contains at least 2 rows.

        Expectations:
            - The entity_dict.ipc file exists and is populated with at least two entities.
        """
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_bundle_with_entities(src)
        _pack_and_load(src, dest)

        ed_path = dest / ".batho" / "bsg" / "current" / "entity_dict.ipc"
        assert ed_path.exists()
        tbl = read_ipc(ed_path)
        assert tbl.num_rows >= 2, f"Expected >=2 entity dict entries, got {tbl.num_rows}"

    def test_entities_ipc_written(self, tmp_path):
        """Verify that the entities IPC table is written and contains the expected entities.

        Scenario:
            A bundle is loaded, and the entities.ipc file is read to check entity names.

        Execution Flow:
            1. Setup a minimal bundle, export it, and load it into the destination.
            2. Check that the `entities.ipc` file exists in the reconstructed directory.
            3. Read the table from the file.
            4. Verify that the table has at least 2 rows, containing "MyClass" and "my_func" in the `entity_name` column.

        Expectations:
            - The entities.ipc file is successfully written.
            - Both mock entities "MyClass" and "my_func" are present in the table.
        """
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_bundle_with_entities(src)
        _pack_and_load(src, dest)

        ent_path = dest / ".batho" / "bsg" / "current" / "entities.ipc"
        assert ent_path.exists()
        tbl = read_ipc(ent_path)
        assert tbl.num_rows >= 2

        names = tbl.column("entity_name").to_pylist()
        assert "MyClass" in names
        assert "my_func" in names

    def test_relationships_ipc_written(self, tmp_path):
        """Verify that the relationships IPC table is written and contains the expected relation types.

        Scenario:
            A bundle is loaded, and the relationships.ipc file is read to verify relationships.

        Execution Flow:
            1. Setup a minimal bundle, export it, and load it into the destination.
            2. Check that `relationships.ipc` exists.
            3. Read the IPC file and assert the table has at least 1 row.
            4. Verify the `relation_type` column contains "contains".

        Expectations:
            - The relationships.ipc file is successfully written.
            - The "contains" relationship between MyClass and my_func is preserved.
        """
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_bundle_with_entities(src)
        _pack_and_load(src, dest)

        rel_path = dest / ".batho" / "bsg" / "current" / "relationships.ipc"
        assert rel_path.exists()
        tbl = read_ipc(rel_path)
        assert tbl.num_rows >= 1

        rel_types = tbl.column("relation_type").to_pylist()
        assert "contains" in rel_types

    def test_dangling_ipc_written_empty(self, tmp_path):
        """Verify that the dangling IPC table is written but is empty after load.

        Scenario:
            A bundle is loaded, and the dangling.ipc file is inspected.

        Execution Flow:
            1. Setup a minimal bundle, export it, and load it into the destination.
            2. Check that `dangling.ipc` exists.
            3. Read the IPC file and assert that the number of rows is 0.

        Expectations:
            - The dangling.ipc file is created.
            - The table in dangling.ipc contains 0 rows since there are no dangling relationships.
        """
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_bundle_with_entities(src)
        _pack_and_load(src, dest)

        dan_path = dest / ".batho" / "bsg" / "current" / "dangling.ipc"
        assert dan_path.exists()
        tbl = read_ipc(dan_path)
        assert tbl.num_rows == 0, "Dangling table should be empty after load"

    def test_meta_json_written(self, tmp_path):
        """Verify that the bsg/current metadata file is written and contains valid attributes.

        Scenario:
            A bundle is loaded, and the bsg/current/meta.json is inspected.

        Execution Flow:
            1. Setup a minimal bundle, export it, and load it.
            2. Check that `meta.json` exists in `bsg/current/`.
            3. Parse the JSON content of the file.
            4. Assert that `schema_version` is present and `entity_count` is at least 2.

        Expectations:
            - The metadata JSON file is correctly written and contains the proper schema version and entity count.
        """
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_bundle_with_entities(src)
        _pack_and_load(src, dest)

        meta_path = dest / ".batho" / "bsg" / "current" / "meta.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["schema_version"] is not None
        assert meta["entity_count"] >= 2

    def test_rebuild_bsg_false_skips_reconstruction(self, tmp_path):
        """Verify that setting rebuild_bsg=False skips the bsg/current reconstruction.

        Scenario:
            A load operation is run with `rebuild_bsg` explicitly set to False.

        Execution Flow:
            1. Setup a minimal bundle and export it to ZIP.
            2. Run `run_load` targeting the destination with `rebuild_bsg=False`.
            3. Assert that the `.batho/bsg/current` directory does not exist.

        Expectations:
            - The load operation succeeds but does not populate the bsg/current directory.
        """
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_bundle_with_entities(src)

        zip_path = src / "out.batho"
        run_export(ExportOptions(root=src, output=zip_path))
        dest.mkdir(parents=True, exist_ok=True)
        run_load(LoadOptions(root=dest, artifact_path=zip_path, force=True, rebuild_bsg=False))

        current_dir = dest / ".batho" / "bsg" / "current"
        assert not current_dir.exists(), "bsg/current should NOT exist when rebuild_bsg=False"

    def test_bsg_current_entity_file_paths_populated(self, tmp_path):
        """Verify that entity file paths are properly populated in the reconstructed entities.ipc table.

        Scenario:
            A bundle is loaded, and the reconstructed `entities.ipc` is checked for correct `file_path` values.

        Execution Flow:
            1. Setup a minimal bundle, export it, and load it.
            2. Read `entities.ipc` from the bsg/current directory.
            3. Assert that the `file_path` column contains "src/foo.py".

        Expectations:
            - The file paths mapping in the entities table matches the source file path "src/foo.py".
        """
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_bundle_with_entities(src)
        _pack_and_load(src, dest)

        ent_path = dest / ".batho" / "bsg" / "current" / "entities.ipc"
        tbl = read_ipc(ent_path)
        file_paths = set(tbl.column("file_path").to_pylist())
        assert "src/foo.py" in file_paths

    def test_patch_can_open_reconstructed_store(self, tmp_path):
        """BsgScratchStore.open_for_patch should load the reconstructed current/.

        Scenario:
            Open the reconstructed store for a patch operation and verify it has the correct entity/relationship counts.

        Execution Flow:
            1. Setup a minimal bundle, export it, and load it.
            2. Import `BsgScratchStore` and invoke `open_for_patch` on the destination's `.batho` directory.
            3. Assert that the returned current_store has an entity count of at least 2.
            4. Assert that the current_store has a relationship count of at least 1.

        Expectations:
            - The BsgScratchStore successfully opens the reconstructed directory.
            - The entity and relationship counts in the store match the loaded bundle counts.
        """
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_bundle_with_entities(src)
        _pack_and_load(src, dest)

        from batho.modules.storage.arrow_store.store import BsgScratchStore
        batho_dir = dest / ".batho"
        current_store, delta_store = BsgScratchStore.open_for_patch(
            batho_dir=batho_dir,
            new_run_uuid="patch_after_load_001",
            new_run_internal_id=99,
            changed_paths=set(),
            db=None,
        )
        assert current_store.entity_count >= 2
        assert current_store.rel_count >= 1
