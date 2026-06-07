import os
import json
import pytest
import pyarrow as pa
import pyarrow.ipc as ipc
import zipfile
import threading
from pathlib import Path

from batho.modules.compression.rules import _is_safe_regex
from batho.utils.path_sanitizer import PathSecurityError
from batho.core.config.loader import get_config_with_root
from batho.modules.storage.arrow_bundle.bundle import BathoBundle, resolve_bundle_dir
from batho.modules.storage.arrow_bundle.reader import BathoBundleReader
from batho.modules.storage.arrow_bundle.writer import BathoBundleWriter


def test_is_safe_regex_escaped_redos():
    """Verify that escaped backslashes in ReDoS patterns are not bypassed."""
    # Classic ReDoS pattern with escaped backslash preceding group (which makes group active)
    # in python raw string r'\\(a+)+' has characters: \, \, (, a, +, ), +
    assert _is_safe_regex(r'\\(a+)+') is False
    assert _is_safe_regex(r'\\\\(a+)+') is False
    
    # Standard group without ReDoS
    assert _is_safe_regex(r'\\(abc)') is True
    assert _is_safe_regex(r'\(a+)+') is True  # Escaped group start is safe because it's literal '('


def test_config_path_traversal_rejection(tmp_path):
    """Verify that configuration paths attempting to escape the project root are rejected."""
    # Safe config
    safe_yaml = tmp_path / "batho.yaml"
    safe_yaml.write_text("paths:\n  artifact_dir: .batho/artifact\n  cache_dir: .batho/cache\n  bsg_dir: .batho/bsg\n")
    cfg = get_config_with_root(tmp_path)
    assert Path(cfg["paths"]["artifact_dir"]).resolve() == (tmp_path / ".batho/artifact").resolve()

    # Unsafe config (absolute path traversal)
    unsafe_yaml_abs = tmp_path / "batho.yaml"
    unsafe_yaml_abs.write_text("paths:\n  artifact_dir: /tmp/outside_dir\n")
    with pytest.raises(PathSecurityError) as exc_info:
        get_config_with_root(tmp_path)
    assert "Unsafe config path artifact_dir escaping repository root" in str(exc_info.value)

    # Unsafe config (relative path traversal)
    unsafe_yaml_rel = tmp_path / "batho.yaml"
    unsafe_yaml_rel.write_text("paths:\n  artifact_dir: ../outside_dir\n")
    with pytest.raises(PathSecurityError) as exc_info:
        get_config_with_root(tmp_path)
    assert "Unsafe config path artifact_dir escaping repository root" in str(exc_info.value)


def test_resolve_bundle_dir_traversal_raise(tmp_path):
    """Verify that resolve_bundle_dir raises PathSecurityError when configured to escape project root."""
    # Write unsafe config
    (tmp_path / "batho.yaml").write_text("paths:\n  artifact_dir: /tmp/outside_dir\n")
    
    # Should raise PathSecurityError directly
    with pytest.raises(PathSecurityError):
        resolve_bundle_dir(tmp_path)


def test_bundle_writer_concurrency(tmp_path):
    """Verify that concurrent runs get separate writer instances to prevent cross-run contamination."""
    bundle = BathoBundle(tmp_path)
    
    # Simulate concurrent run creation
    run_id_1 = bundle.create_run("run-1")
    run_id_2 = bundle.create_run("run-2")

    # Assert they have distinct writer instances in the writers map
    assert run_id_1 != run_id_2
    assert bundle._writers[run_id_1] is not bundle._writers[run_id_2]
    assert bundle._writers[run_id_1].run_id == run_id_1
    assert bundle._writers[run_id_2].run_id == run_id_2

    # Clean up
    bundle.close()


def test_multi_flush_offset_index_correctness(tmp_path):
    """Verify that multi-batch flushes are correctly sorted and indexed on load, avoiding corruption."""
    artifact_dir = tmp_path / "artifact"
    artifact_dir.mkdir()
    
    # 1. Write multiple batches simulating separate flushes
    writer = BathoBundleWriter(artifact_dir, run_id=1)
    
    # Batch 1: file_id = 3
    writer.write_file_artifact(
        file_id=3,
        agent={"entities": [{"id": "ent3", "name": "func3", "type": "function", "start_line": 1}]},
        storage={"entities": []},
        rels=[],
        content_hash="hash3"
    )
    writer._flush_buffers_locked()

    # Batch 2: file_id = 1
    writer.write_file_artifact(
        file_id=1,
        agent={"entities": [{"id": "ent1", "name": "func1", "type": "function", "start_line": 1}]},
        storage={"entities": []},
        rels=[],
        content_hash="hash1"
    )
    writer._flush_buffers_locked()

    # Batch 3: file_id = 2
    writer.write_file_artifact(
        file_id=2,
        agent={"entities": [{"id": "ent2", "name": "func2", "type": "function", "start_line": 1}]},
        storage={"entities": []},
        rels=[],
        content_hash="hash2"
    )
    writer.finalize()

    # Update meta.json manifest
    meta_path = artifact_dir / "meta.json"
    with open(meta_path, "w") as f:
        json.dump({
            "generation": 1,
            "active_files": {
                "agent_views": "agent_views.tmp.ipc"
            }
        }, f)

    # 2. Read back using BathoBundleReader
    reader = BathoBundleReader(artifact_dir)
    
    # Retrieve artifacts by id - should look up slices correctly
    res1 = reader.get_file_artifacts_by_id(1)
    res2 = reader.get_file_artifacts_by_id(2)
    res3 = reader.get_file_artifacts_by_id(3)

    assert len(res1["agent_view"]) == 1
    assert res1["agent_view"][0]["entity_id"] == "ent1"

    assert len(res2["agent_view"]) == 1
    assert res2["agent_view"][0]["entity_id"] == "ent2"

    assert len(res3["agent_view"]) == 1
    assert res3["agent_view"][0]["entity_id"] == "ent3"


def test_zip_export_oom_prevention(tmp_path):
    """Verify that export_artifact runs successfully using streaming compression."""
    artifact_dir = tmp_path / "artifact"
    artifact_dir.mkdir()

    # Create dummy IPC files
    schema = pa.schema([("file_id", pa.int64())])
    table = pa.Table.from_pydict({"file_id": [1, 2, 3]}, schema=schema)
    ipc_file = artifact_dir / "agent_views.v1.ipc"
    with ipc.new_file(str(ipc_file), schema) as w:
        w.write_table(table)

    # Write manifest
    meta_path = artifact_dir / "meta.json"
    with open(meta_path, "w") as f:
        json.dump({
            "generation": 1,
            "active_files": {
                "agent_views": "agent_views.v1.ipc"
            }
        }, f)

    # Run export
    from batho.modules.storage.arrow_bundle.manager import BathoBundleManager
    manager = BathoBundleManager(artifact_dir)
    zip_path = tmp_path / "export.zip"
    
    manager.export_artifact(zip_path)

    # Verify zip was created and has correct members
    assert zip_path.exists()
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        assert "manifest.json" in names
        assert "agent_views.ipc.zst" in names


def test_config_backup_recovery(tmp_path):
    """Verify that an invalid config file is backed up to .yaml.bak and replaced with default config."""
    cfg_path = tmp_path / "batho.yaml"
    # Write invalid config (e.g. invalid type for logging level)
    cfg_path.write_text("logging:\n  level: 12345\n", encoding="utf-8")
    
    cfg = get_config_with_root(tmp_path)
    
    # Assert that backup file was created
    backup_path = tmp_path / "batho.yaml.bak"
    assert backup_path.exists()
    assert "level: 12345" in backup_path.read_text(encoding="utf-8")
    
    # Assert that config was regenerated with valid default values
    # level will be resolved to standard library integer value (ERROR is 40)
    assert cfg["logging"]["level"] in {10, 20, 30, 40, 50}
    assert cfg_path.exists()
    assert "level: 12345" not in cfg_path.read_text(encoding="utf-8")


def test_interprocess_locking(tmp_path):
    """Verify that InterProcessLock prevents concurrent acquisitions."""
    from batho.utils.file_io import InterProcessLock
    lock_file = tmp_path / "test.lock"
    
    lock1 = InterProcessLock(lock_file)
    lock2 = InterProcessLock(lock_file)
    
    with lock1:
        with pytest.raises(RuntimeError) as exc_info:
            with lock2:
                pass
        assert "Another Batho process is already running" in str(exc_info.value)
    
    # After releasing, it should be acquirable again
    with lock2:
        pass


def test_build_lock_conflict(tmp_path):
    """Verify that run_build returns a failure result when lock cannot be acquired."""
    from batho.orchestrator.build import run_build, BuildOptions
    from batho.utils.file_io import InterProcessLock
    
    # Setup dummy directory
    root = tmp_path / "repo"
    root.mkdir()
    
    lock_file = root / ".batho" / "batho.lock"
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Hold the lock externally
    lock = InterProcessLock(lock_file)
    with lock:
        options = BuildOptions(root=root)
        res = run_build(options)
        assert res.success is False
        assert any("Another Batho process" in w or "failed" in w.lower() for w in res.warnings)


def test_build_failed_cleanup(tmp_path):
    """Verify that on build failure, db.fail_run is called and store.cleanup_streams is called."""
    from batho.orchestrator.build import run_build, BuildOptions
    from unittest.mock import patch
    
    root = tmp_path / "repo"
    root.mkdir()
    
    # Write a simple config
    (root / "batho.yaml").write_text("paths:\n  artifact_dir: .batho/artifact\n", encoding="utf-8")
    
    # Force a failure during the build graph stage by mocking CodeGraphIndexer
    with patch("batho.modules.graph.builder.codegraph.CodeGraphIndexer") as mock_indexer_cls:
        mock_indexer = mock_indexer_cls.return_value.__enter__.return_value
        mock_indexer.build_graph.side_effect = ValueError("Mocked build failure")
        mock_indexer.build_stats = {"files_parsed": 1, "files_cached": 0}
        mock_indexer.get_unindexed_files.return_value = []
        
        options = BuildOptions(root=root, force_full=True)
        res = run_build(options)
        assert res.success is False
        assert any("Mocked build failure" in w for w in res.warnings)
            
    # Verify that run was marked as failed in SQLite db
    from batho.modules.storage.arrow_bundle.bundle import BathoBundle
    db = BathoBundle(root)
    runs = db._reader.get_all_runs()
    assert len(runs) == 1
    assert runs[0]["status"] == "failed"
    assert runs[0]["error_message"] == "Mocked build failure"


def test_is_safe_regex_new_cases():
    """Verify that _is_safe_regex handles character classes, ?, and alternation with shared prefixes."""
    # Safe regexes
    assert _is_safe_regex("([a-z+])+") is True
    assert _is_safe_regex("(api|auth)+") is True

    # Unsafe regexes (nested quantifiers, ReDoS, or prefix sharing)
    assert _is_safe_regex("([a-z]+)+") is False
    assert _is_safe_regex("(a?)+") is False
    assert _is_safe_regex("(a|ab)+") is False
    assert _is_safe_regex("(a|a)+") is False


def test_ast_cache_clear_older_than_days(tmp_path):
    """Verify that AstCache.clear(older_than_days) selectively deletes old entries and updates manifest."""
    from batho.modules.extraction.ast_cache import AstCache
    from batho.core.schemas import Entity, Relationship
    import time

    cache = AstCache(tmp_path)
    
    # Write a cache entry
    cache.set_ast(
        file_path="foo.py",
        content_hash="hash1",
        variant="v1",
        entities=[],
        relationships=[],
        mtime=1.0,
        size=10
    )
    
    key1 = cache._compute_key("foo.py", "hash1", "v1")
    file1 = cache.ast_dir / f"{key1}.msgpack"
    assert file1.exists()

    # Backdate file1 st_mtime to 10 days ago
    ten_days_ago = time.time() - (10 * 86400)
    os.utime(file1, (ten_days_ago, ten_days_ago))

    # Write a fresh cache entry
    cache.set_ast(
        file_path="bar.py",
        content_hash="hash2",
        variant="v1",
        entities=[],
        relationships=[],
        mtime=2.0,
        size=20
    )
    
    key2 = cache._compute_key("bar.py", "hash2", "v1")
    file2 = cache.ast_dir / f"{key2}.msgpack"
    assert file2.exists()

    # Clear entries older than 5 days
    deleted_count = cache.clear(older_than_days=5)
    assert deleted_count == 1
    
    assert not file1.exists()
    assert file2.exists()
    
    manifest = cache._load_manifest_for_gc()
    assert "foo.py" not in manifest
    assert "bar.py" in manifest


def test_manifest_nanosecond_invalidation(tmp_path):
    """Verify that load_manifest detects nanosecond mtime and size changes for invalidation."""
    from batho.modules.storage.arrow_bundle.manager import BathoBundleManager
    import json
    
    meta_path = tmp_path / "meta.json"
    manager = BathoBundleManager(tmp_path)
    
    # Initial manifest
    manifest_data = {"schema_version": "batho-bundle.v1", "generation": 1, "active_files": {}}
    meta_path.write_text(json.dumps(manifest_data))
    
    m1 = manager.load_manifest()
    assert m1["generation"] == 1
    
    # Update generation but keep same file size and modify st_mtime_ns explicitly
    manifest_data["generation"] = 2
    meta_path.write_text(json.dumps(manifest_data))
    
    # Artificially set stat times
    stat_res = meta_path.stat()
    os.utime(meta_path, ns=(stat_res.st_atime_ns, stat_res.st_mtime_ns + 1000))
    
    m2 = manager.load_manifest()
    assert m2["generation"] == 2


def test_file_id_max_calculation(tmp_path):
    """Verify that _compute_next_file_id correctly identifies the max file ID on unsorted tables."""
    from batho.modules.storage.arrow_bundle.bundle import BathoBundle
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


def test_run_artifacts_specific_run(tmp_path):
    """Verify that get_run_artifacts resolves and returns artifacts for the specific requested run."""
    from batho.modules.storage.arrow_bundle.bundle import BathoBundle
    
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
