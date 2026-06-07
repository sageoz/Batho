import os
import re
import shutil
import zipfile
import tempfile
import threading
import time
from pathlib import Path
import pytest
import pyarrow as pa
import zstandard as zstd

from batho.utils.path_sanitizer import PathSecurityError
from batho.modules.storage.arrow_bundle.manager import BathoBundleManager
from batho.modules.storage.arrow_bundle.bundle import BathoBundle
from batho.modules.extraction.ast_cache import AstCache
from batho.modules.compression.rules import _is_safe_regex
from batho.modules.storage.cache.unified_cache import BathoCache
from batho.core.schemas import FileSnapshot, Entity, Relationship, RelationshipType, EntityType


def test_zip_slip_rejection(tmp_path):
    """Verify that Zip Slip path traversal attempts raise PathSecurityError."""
    artifact_dir = tmp_path / "artifact"
    bsg_dir = tmp_path / "bsg"
    manager = BathoBundleManager(artifact_dir)

    # Create a malicious zip file
    zip_file = tmp_path / "malicious.zip"
    with zipfile.ZipFile(zip_file, "w") as zf:
        # manifest.json is required
        manifest_data = {
            "schema_version": "batho-bundle.v1",
            "generation": 1,
            "active_files": {}
        }
        import json
        zf.writestr("manifest.json", json.dumps(manifest_data))
        
        # Add a Zip Slip member escaping active files
        zf.writestr("../escaped_file.ipc.zst", b"some_compressed_data")
        
        # Add a Zip Slip member escaping bsg
        zf.writestr("bsg/../../escaped_bsg.ipc.zst", b"some_compressed_data")

    # Unpacking should raise PathSecurityError
    with pytest.raises(PathSecurityError):
        manager.unpack_artifact(zip_file, bsg_target_dir=bsg_dir)


def test_decompression_bomb_prevention(tmp_path):
    """Verify that decompression sizes exceeding max limit raise RuntimeError."""
    artifact_dir = tmp_path / "artifact"
    manager = BathoBundleManager(artifact_dir)

    zip_file = tmp_path / "bomb.zip"
    cctx = zstd.ZstdCompressor(level=3)
    compressed = cctx.compress(b"a" * 1000)

    with zipfile.ZipFile(zip_file, "w") as zf:
        manifest_data = {
            "schema_version": "batho-bundle.v1",
            "generation": 1,
            "active_files": {}
        }
        import json
        zf.writestr("manifest.json", json.dumps(manifest_data))
        zf.writestr("bomb_table.ipc.zst", compressed)

    # Let's mock MAX_DECOMPRESS_SIZE in manager.py to verify it fails
    import batho.modules.storage.arrow_bundle.manager as manager_mod
    original_limit = manager_mod.MAX_DECOMPRESS_SIZE
    
    # Run with standard limit (should succeed because 1000 < 500MB)
    manifest = manager.unpack_artifact(zip_file)
    assert "bomb_table" in manifest["active_files"]

    # Run with a very low limit (should fail since 1000 > 500)
    manager_mod.MAX_DECOMPRESS_SIZE = 500
    try:
        with pytest.raises(RuntimeError) as exc_info:
            manager.unpack_artifact(zip_file)
        assert "Failed to decompress ZIP member" in str(exc_info.value)
    finally:
        manager_mod.MAX_DECOMPRESS_SIZE = original_limit


def test_changelog_base_uuid_resolution(tmp_path):
    """Verify that record_file_changelog resolves the base run UUID correctly from history."""
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


def test_ast_cache_stale_purging(tmp_path):
    """Verify that older content_hash entries are deleted from disk/manifest when a file changes."""
    ast_cache = AstCache(tmp_path)

    file_path = "src/main.py"
    entities = [Entity(type=EntityType.FUNCTION, name="func1", file=file_path, start_line=1, end_line=5)]
    rels = [Relationship(source_id="e1", target_id="e2", type=RelationshipType.CALLS)]

    # Write variant 1 under content_hash_1
    ast_cache.set_ast(
        file_path=file_path,
        content_hash="content_hash_1",
        variant="v1",
        entities=entities,
        relationships=rels,
        mtime=1234.56,
        size=100
    )

    # Verify files exist on disk
    key1 = ast_cache._compute_key(file_path, "content_hash_1", "v1")
    file1 = ast_cache.ast_dir / f"{key1}.msgpack"
    assert file1.exists()

    manifest = ast_cache._load_manifest_for_gc()
    assert file_path in manifest
    assert key1 in manifest[file_path]

    # Write a new variant under content_hash_2 (content has changed)
    ast_cache.set_ast(
        file_path=file_path,
        content_hash="content_hash_2",
        variant="v1",
        entities=entities,
        relationships=rels,
        mtime=1234.57,
        size=105
    )

    # Verify that file1 is deleted and file2 exists
    key2 = ast_cache._compute_key(file_path, "content_hash_2", "v1")
    file2 = ast_cache.ast_dir / f"{key2}.msgpack"
    
    assert not file1.exists()
    assert file2.exists()

    manifest = ast_cache._load_manifest_for_gc()
    assert key1 not in manifest[file_path]
    assert key2 in manifest[file_path]


def test_ast_cache_manifest_locking(tmp_path):
    """Test that the manifest locking context manager serializes concurrent access."""
    ast_cache = AstCache(tmp_path)
    
    results = []
    
    def worker(worker_id):
        with ast_cache._lock_manifest():
            results.append(f"{worker_id}-start")
            time.sleep(0.05)
            results.append(f"{worker_id}-end")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # The start and end tags must not be interleaved because of the lock
    # i.e. we should see worker_id-start immediately followed by worker_id-end
    for i in range(0, len(results), 2):
        start = results[i]
        end = results[i+1]
        assert start.split("-")[0] == end.split("-")[0]
        assert "start" in start
        assert "end" in end


def test_unified_cache_lru_eviction():
    """Verify that unified cache snapshots are capped at 1000 items and follow LRU eviction."""
    cache = BathoCache()

    # Insert 1005 snapshots
    for i in range(1005):
        snap = FileSnapshot(file_path=f"file_{i}.py", file_hash=f"hash_{i}")
        cache.set_file_snapshot(snap)

    # Check stats - snapshot count should be strictly 1000
    stats = cache.get_stats()
    assert stats["snapshot_count"] == 1000

    # The first 5 files should be evicted (file_0 to file_4)
    for i in range(5):
        assert cache.get_file_snapshot(f"file_{i}.py") is None

    # file_5 should be present
    assert cache.get_file_snapshot("file_5.py") is not None


def test_reader_cache_invalidation(tmp_path):
    """Verify that reader caches are invalidated automatically when the active path changes on disk."""
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
    from batho.modules.storage.arrow_bundle.reader import BathoBundleReader
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
    # The manager's manifest cache checks modification time, so updating meta.json updates mtime.
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


def test_redos_pattern_detection():
    """Verify that _is_safe_regex correctly classifies safe and unsafe regexes."""
    # Safe regexes
    assert _is_safe_regex("^prefix.*") is True
    assert _is_safe_regex("[a-z]+_suffix") is True
    assert _is_safe_regex("(api|auth)_.*") is True
    assert _is_safe_regex("normal_pattern") is True

    # Unsafe regexes (nested quantifiers or too many wildcards)
    assert _is_safe_regex("(a+)+") is False
    assert _is_safe_regex("(a*)*") is False
    assert _is_safe_regex("([a-zA-Z]+)*") is False
    assert _is_safe_regex("(a|b+)+") is False
    assert _is_safe_regex("a*b*c*d*e*f*g*h*i*j*") is False  # too many quantifiers (> 8)
    assert _is_safe_regex("x" * 251) is False  # too long
