"""Tests for BsgScratchStore — Arrow IPC + zstd scratch store."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_batho_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


def test_store_init_creates_current_dir(tmp_batho_dir):
    from batho.modules.storage.arrow_store import BsgScratchStore

    store = BsgScratchStore(run_uuid="test-run-001", batho_dir=tmp_batho_dir, run_internal_id=1)
    assert store.run_dir.exists()
    assert store.run_dir.name == "current"
    assert (store.run_dir / "meta.json").exists()
    assert not store.is_delta


def test_store_delta_init_creates_uuid_dir(tmp_batho_dir):
    from batho.modules.storage.arrow_store import BsgScratchStore

    store = BsgScratchStore(
        run_uuid="patch-xyz", batho_dir=tmp_batho_dir, run_internal_id=2, is_delta=True
    )
    assert store.run_dir.exists()
    assert store.run_dir.name == "patch-xyz"
    assert store.is_delta


def test_entity_dict_roundtrip(tmp_batho_dir):
    from batho.modules.storage.arrow_store import BsgScratchStore

    store = BsgScratchStore(run_uuid="test-run-002", batho_dir=tmp_batho_dir, run_internal_id=1)
    assert store.run_dir.name == "current"
    ids = ["entity:a:foo", "entity:b:bar", "entity:c:baz"]
    keys = store.bulk_get_or_create_entity_keys(ids)
    assert len(keys) == 3
    assert all(isinstance(v, int) for v in keys.values())

    for eid, key in keys.items():
        assert store.get_entity_val(key) == eid

    keys2 = store.bulk_get_or_create_entity_keys(ids)
    assert keys2 == keys


def test_append_and_compact_entities(tmp_batho_dir):
    from batho.modules.storage.arrow_store import BsgScratchStore
    from batho.modules.storage.arrow_store.compaction import read_ipc

    store = BsgScratchStore(run_uuid="test-run-003", batho_dir=tmp_batho_dir, run_internal_id=1)
    assert store.run_dir.name == "current"
    keys = store.bulk_get_or_create_entity_keys(["eid:1", "eid:2"])

    rows = [
        (keys["eid:1"], 1, "MyFunc", "FUNCTION", "pkg.MyFunc", "src/a.py", 10, "def MyFunc()", True),
        (keys["eid:2"], 1, "MyClass", "CLASS", "pkg.MyClass", "src/b.py", 5, None, False),
    ]
    store.append_entities(rows)
    assert store.entity_count == 2

    store.compact()

    tbl = read_ipc(store.entities_path)
    assert len(tbl) == 2
    names = set(tbl.column("entity_name").to_pylist())
    assert "MyFunc" in names and "MyClass" in names


def test_append_and_compact_relationships(tmp_batho_dir):
    from batho.modules.storage.arrow_store import BsgScratchStore
    from batho.modules.storage.arrow_store.compaction import read_ipc

    store = BsgScratchStore(run_uuid="test-run-004", batho_dir=tmp_batho_dir, run_internal_id=1)
    keys = store.bulk_get_or_create_entity_keys(["eid:src", "eid:tgt"])

    rel_rows = [(keys["eid:src"], keys["eid:tgt"], "IMPORTS", 1, "{}")]
    store.append_relationships(rel_rows)
    store.compact()

    tbl = read_ipc(store.relationships_path)
    assert len(tbl) == 1
    assert tbl.column("relation_type").to_pylist()[0] == "IMPORTS"


def test_compact_removes_stream_dir(tmp_batho_dir):
    from batho.modules.storage.arrow_store import BsgScratchStore

    store = BsgScratchStore(run_uuid="test-run-005", batho_dir=tmp_batho_dir, run_internal_id=1)
    store.append_entities([
        (1, 1, "X", "CLASS", None, "src/x.py", 1, None, False)
    ])
    store.bulk_get_or_create_entity_keys(["eid:1"])

    store.compact()
    assert not store._stream_dir.exists()


def test_cleanup_streams_leaves_compacted_files(tmp_batho_dir):
    from batho.modules.storage.arrow_store import BsgScratchStore

    store = BsgScratchStore(run_uuid="test-run-006", batho_dir=tmp_batho_dir, run_internal_id=1)
    store.compact()
    store.cleanup_streams()

    assert store.entities_path.exists()
    assert store.relationships_path.exists()
    assert store.entity_dict_path.exists()
    assert not store._stream_dir.exists()


def test_entity_dict_compacted_correctly(tmp_batho_dir):
    from batho.modules.storage.arrow_store import BsgScratchStore
    from batho.modules.storage.arrow_store.compaction import read_ipc

    store = BsgScratchStore(run_uuid="test-run-007", batho_dir=tmp_batho_dir, run_internal_id=1)
    store.bulk_get_or_create_entity_keys(["eid:a", "eid:b", "eid:c"])
    store.compact()

    tbl = read_ipc(store.entity_dict_path)
    assert len(tbl) == 3
    vals = set(tbl.column("val").to_pylist())
    assert vals == {"eid:a", "eid:b", "eid:c"}


def test_open_for_patch_filters_changed_files(tmp_batho_dir):
    from batho.modules.storage.arrow_store import BsgScratchStore
    from batho.modules.storage.arrow_store.compaction import read_ipc

    # Build a "base" store into current/
    base_store = BsgScratchStore(run_uuid="base-run", batho_dir=tmp_batho_dir, run_internal_id=1)
    keys = base_store.bulk_get_or_create_entity_keys(["eid:1", "eid:2", "eid:3"])
    base_store.append_entities([
        (keys["eid:1"], 1, "FuncA", "FUNCTION", None, "src/unchanged.py", 1, None, False),
        (keys["eid:2"], 1, "ClassB", "CLASS", None, "src/changed.py", 5, None, False),
        (keys["eid:3"], 1, "FuncC", "FUNCTION", None, "src/unchanged.py", 20, None, False),
    ])
    base_store.compact()

    # Open for patch, excluding "src/changed.py"
    current_store, delta_store = BsgScratchStore.open_for_patch(
        batho_dir=tmp_batho_dir,
        new_run_uuid="patch-001",
        new_run_internal_id=2,
        changed_paths={"src/changed.py"},
        db=None,
    )

    # Compact to flush pre-loaded unchanged rows to disk
    current_store.compact()

    # current/ should have unchanged rows only
    tbl = read_ipc(current_store.entities_path)
    fps = set(tbl.column("file_path").to_pylist())
    assert "src/changed.py" not in fps
    assert "src/unchanged.py" in fps
    assert len(tbl) == 2

    # delta sidecar is at bsg/patch-001/
    assert delta_store.is_delta
    assert delta_store.run_dir.name == "patch-001"

    # entity dict shared between stores
    assert current_store._entity_dict is delta_store._entity_dict


def test_resolve_dangling_no_entities(tmp_batho_dir):
    from batho.modules.storage.arrow_store import BsgScratchStore

    store = BsgScratchStore(run_uuid="test-run-008", batho_dir=tmp_batho_dir, run_internal_id=1)
    store.compact()
    resolved = store.resolve_dangling(db=None)
    assert resolved == 0


def test_resolve_dangling_simple(tmp_batho_dir):
    from batho.modules.storage.arrow_store import BsgScratchStore
    from batho.modules.storage.arrow_store.compaction import read_ipc

    store = BsgScratchStore(run_uuid="test-run-009", batho_dir=tmp_batho_dir, run_internal_id=1)
    keys = store.bulk_get_or_create_entity_keys(["eid:src", "eid:tgt"])

    store.append_entities([
        (keys["eid:src"], 1, "SrcFunc", "FUNCTION", None, "src/a.py", 1, None, False),
        (keys["eid:tgt"], 1, "TgtClass", "CLASS", None, "src/b.py", 5, None, False),
    ])
    store.append_dangling([
        (keys["eid:src"], "TgtClass", "IMPORTS", 1),
    ])
    store.compact()

    resolved = store.resolve_dangling(db=None)
    assert resolved >= 1

    dan_tbl = read_ipc(store.dangling_path)
    assert len(dan_tbl) == 0


def test_from_run_dir(tmp_batho_dir):
    from batho.modules.storage.arrow_store import BsgScratchStore
    from batho.modules.storage.arrow_store.store import BsgScratchStore as _StoreClass

    store = BsgScratchStore(run_uuid="test-run-010", batho_dir=tmp_batho_dir, run_internal_id=5)
    store.bulk_get_or_create_entity_keys(["eid:x"])
    store.compact()

    reloaded = _StoreClass.from_run_dir(store.run_dir, run_internal_id=5)
    assert reloaded.run_uuid == "test-run-010"
    assert reloaded.get_entity_val(1) is not None
    assert not reloaded.is_delta


def test_meta_json_written(tmp_batho_dir):
    import json
    from batho.modules.storage.arrow_store import BsgScratchStore

    store = BsgScratchStore(run_uuid="test-run-011", batho_dir=tmp_batho_dir, run_internal_id=3)
    store.compact()

    meta = json.loads((store.run_dir / "meta.json").read_text())
    assert meta["run_uuid"] == "test-run-011"
    assert meta["run_internal_id"] == 3
    assert meta["compacted"] is True
    assert meta["is_delta"] is False


def test_delta_meta_json_has_extra_fields(tmp_batho_dir):
    import json
    from batho.modules.storage.arrow_store import BsgScratchStore

    store = BsgScratchStore(
        run_uuid="patch-meta",
        batho_dir=tmp_batho_dir,
        run_internal_id=7,
        is_delta=True,
        _base_run_uuid="current",
        _changed_files={"src/a.py"},
    )
    store.compact()

    meta = json.loads((store.run_dir / "meta.json").read_text())
    assert meta["is_delta"] is True
    assert meta["base_run_uuid"] == "current"
    assert "src/a.py" in meta["changed_files"]


def test_deduplication_on_compact(tmp_batho_dir):
    from batho.modules.storage.arrow_store import BsgScratchStore
    from batho.modules.storage.arrow_store.compaction import read_ipc

    store = BsgScratchStore(run_uuid="test-run-012", batho_dir=tmp_batho_dir, run_internal_id=1)
    keys = store.bulk_get_or_create_entity_keys(["eid:dup"])
    row = (keys["eid:dup"], 1, "DupFunc", "FUNCTION", None, "src/dup.py", 1, None, False)
    store.append_entities([row, row, row])
    store.compact()

    tbl = read_ipc(store.entities_path)
    assert len(tbl) == 1


def test_build_writes_to_current(tmp_batho_dir):
    """build stores write to bsg/current/ — no per-build-uuid dir."""
    from batho.modules.storage.arrow_store import BsgScratchStore
    from batho.modules.storage.arrow_store.compaction import read_ipc

    store = BsgScratchStore(run_uuid="build-abc", batho_dir=tmp_batho_dir, run_internal_id=1)
    assert store.run_dir == tmp_batho_dir.resolve() / "bsg" / "current"
    assert not (tmp_batho_dir / "bsg" / "build-abc").exists()

    keys = store.bulk_get_or_create_entity_keys(["eid:z"])
    store.append_entities([(keys["eid:z"], 1, "Z", "FUNCTION", None, "src/z.py", 1, None, False)])
    store.compact()

    assert (tmp_batho_dir / "bsg" / "current" / "entities.ipc").exists()
    assert not (tmp_batho_dir / "bsg" / "build-abc").exists()


def test_patch_delta_sidecar(tmp_batho_dir):
    """open_for_patch produces correct current/ and <patch_uuid>/ delta with only changed rows."""
    from batho.modules.storage.arrow_store import BsgScratchStore
    from batho.modules.storage.arrow_store.compaction import read_ipc

    # Simulate a prior build populating current/
    build_store = BsgScratchStore(run_uuid="build-1", batho_dir=tmp_batho_dir, run_internal_id=1)
    keys = build_store.bulk_get_or_create_entity_keys(["eid:a", "eid:b"])
    build_store.append_entities([
        (keys["eid:a"], 1, "Alpha", "FUNCTION", None, "src/stable.py", 1, None, False),
        (keys["eid:b"], 1, "Beta", "CLASS", None, "src/changing.py", 5, None, False),
    ])
    build_store.compact()

    # Open for patch: src/changing.py is being modified
    current_store, delta_store = BsgScratchStore.open_for_patch(
        batho_dir=tmp_batho_dir,
        new_run_uuid="patch-p1",
        new_run_internal_id=2,
        changed_paths={"src/changing.py"},
        db=None,
    )

    # Append new rows for the changed file into both stores
    new_keys = current_store.bulk_get_or_create_entity_keys(["eid:b2"])
    new_row = (new_keys["eid:b2"], 2, "BetaV2", "CLASS", None, "src/changing.py", 5, None, False)
    current_store.append_entities([new_row])
    delta_store.append_entities([new_row])

    current_store.compact()
    delta_store.compact()

    # current/ has stable + new changed row
    current_tbl = read_ipc(current_store.entities_path)
    current_names = set(current_tbl.column("entity_name").to_pylist())
    assert "Alpha" in current_names
    assert "BetaV2" in current_names

    # delta sidecar has only the new changed row
    delta_tbl = read_ipc(delta_store.entities_path)
    delta_names = set(delta_tbl.column("entity_name").to_pylist())
    assert delta_names == {"BetaV2"}
    assert "Alpha" not in delta_names

    # delta dir is bsg/patch-p1/
    assert delta_store.run_dir == tmp_batho_dir.resolve() / "bsg" / "patch-p1"
