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
    run_export(ExportOptions(root=src, pack=True, output=zip_path))

    dest.mkdir(parents=True, exist_ok=True)
    run_load(LoadOptions(root=dest, artifact_path=zip_path, force=True, rebuild_bsg=True))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBsgCurrentReconstructed:
    def test_bsg_current_dir_exists_after_load(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_bundle_with_entities(src)
        _pack_and_load(src, dest)

        current_dir = dest / ".batho" / "bsg" / "current"
        assert current_dir.exists(), "bsg/current/ was not created"

    def test_entity_dict_written(self, tmp_path):
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
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        _make_bundle_with_entities(src)

        zip_path = src / "out.batho"
        run_export(ExportOptions(root=src, pack=True, output=zip_path))
        dest.mkdir(parents=True, exist_ok=True)
        run_load(LoadOptions(root=dest, artifact_path=zip_path, force=True, rebuild_bsg=False))

        current_dir = dest / ".batho" / "bsg" / "current"
        assert not current_dir.exists(), "bsg/current should NOT exist when rebuild_bsg=False"

    def test_bsg_current_entity_file_paths_populated(self, tmp_path):
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
        """BsgScratchStore.open_for_patch should load the reconstructed current/."""
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
