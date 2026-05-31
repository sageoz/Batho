import os
import sys
import threading
import time
from pathlib import Path
import pytest

from batho.modules.storage.sqlite_registry.engine import BathoDatabase
from batho.modules.storage.cache.unified_cache import BathoCache
from batho.utils.file_io import write_atomically, read_file_text
from batho.utils.encoding import decode_bytes_with_fallback

def test_out_of_order_deletion(tmp_path):
    # Setup database
    db_path = tmp_path / "test_deletion.batho"
    db = BathoDatabase(db_path, repo_root=tmp_path)
    
    run_uuid = "run_1"
    run_internal_id = db.create_run(run_uuid, root_path=str(tmp_path))

    # Define original entities and relationship
    agent_view_1 = {
        "entities": [
            {"id": "e1", "name": "foo", "type": "FUNCTION", "start_line": 1, "end_line": 5},
            {"id": "e2", "name": "bar", "type": "FUNCTION", "start_line": 10, "end_line": 15}
        ]
    }
    storage_delta = {"entities": []}
    relationships_1 = [
        {"id": "r1", "type": "CALLS", "source_id": "e1", "target_id": "e2"}
    ]

    # Insert file artifact
    db.insert_file_artifact(
        run_internal_id, "file1.py", "hash1", agent_view_1, storage_delta, relationships_1
    )

    # Verify initial insert
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    
    entities = conn.execute("SELECT * FROM query_entities WHERE run_id = ?", (run_internal_id,)).fetchall()
    assert len(entities) == 2
    
    relationships = conn.execute("SELECT * FROM query_relationships WHERE run_id = ?", (run_internal_id,)).fetchall()
    assert len(relationships) == 1
    assert db.get_entity_val(relationships[0]["source_key"]) == "e1"

    # Now, insert again for same file, but removing entity e2 and relationship r1
    agent_view_2 = {
        "entities": [
            {"id": "e1", "name": "foo", "type": "FUNCTION", "start_line": 1, "end_line": 5}
        ]
    }
    db.insert_file_artifact(
        run_internal_id, "file1.py", "hash2", agent_view_2, storage_delta, []
    )

    # Verify query_relationships has been updated and the old relationship is removed
    # Previously, since query_entities delete happened first, the relationship delete subquery 
    # matched empty set or did not match e2, leaving the relationship orphaned.
    entities = conn.execute("SELECT * FROM query_entities WHERE run_id = ?", (run_internal_id,)).fetchall()
    assert len(entities) == 1
    assert db.get_entity_val(entities[0]["entity_key"]) == "e1"

    relationships = conn.execute("SELECT * FROM query_relationships WHERE run_id = ?", (run_internal_id,)).fetchall()
    assert len(relationships) == 0

    conn.close()
    db.close()


def test_fork_induced_rlock_deadlock(tmp_path):
    db_path = tmp_path / "test_fork.batho"
    db = BathoDatabase(db_path, repo_root=tmp_path)

    # Lock the lock in the parent process state
    db._lock.acquire()
    assert db._lock._is_owned()

    # Simulate os.getpid() change (fork mismatch)
    db._pid = 999999  # Mismatched PID
    
    # This will trigger the PID check inside database operations, or we can invoke it directly
    db._check_pid()

    # Verify we can acquire the new lock without deadlocking (it should be re-initialized and free)
    acquired = db._lock.acquire(blocking=False)
    assert acquired
    db._lock.release()
    db.close()


def test_cache_eviction_efficiency_and_lazy_eviction(tmp_path):
    cache = BathoCache(str(tmp_path / "cache.batho"))
    cache._max_ast_size = 2

    # 1. Test lazy eviction on get_ast
    # Set an entry with a positive TTL
    cache.set_ast("file1.py", "hash1", ["e1"], ["r1"], 1.0, 100, ttl_days=10)
    # Manually modify expiration to the past
    key1 = cache._ast_key("file1.py", "hash1", "")
    val1 = cache._ast[key1]
    cache._ast[key1] = (val1[0], val1[1], time.time() - 100.0)
    
    # Retrieve it, should return None and delete it from cache
    assert cache.get_ast("file1.py", "hash1") is None
    with cache._lock:
        assert cache._ast_key("file1.py", "hash1") not in cache._ast

    # 2. Test eviction only when cache capacity limit is exceeded
    # Set two active entries
    cache.set_ast("file2.py", "hash2", ["e2"], [], 1.0, 100, ttl_days=10)
    cache.set_ast("file3.py", "hash3", ["e3"], [], 1.0, 100, ttl_days=10)
    
    assert len(cache._ast) == 2
    
    # Set one expired entry
    cache.set_ast("file4.py", "hash4", ["e4"], [], 1.0, 100, ttl_days=10)
    key4 = cache._ast_key("file4.py", "hash4", "")
    val4 = cache._ast[key4]
    cache._ast[key4] = (val4[0], val4[1], time.time() - 100.0)
    
    # Size is now 3 (over capacity of 2). Next set_ast or get_ast will trigger eviction/purge.
    # When we add a new active entry, it should purge the expired file4.py first instead of evicting file2.py (LRU)
    cache.set_ast("file5.py", "hash5", ["e5"], [], 1.0, 100, ttl_days=10)
    
    with cache._lock:
        assert len(cache._ast) <= 2
        # file4.py (expired) should be gone
        assert cache._ast_key("file4.py", "hash4") not in cache._ast
        # file5.py should be present
        assert cache._ast_key("file5.py", "hash5") in cache._ast
        # file3.py should be present
        assert cache._ast_key("file3.py", "hash3") in cache._ast

    cache.close()


def test_write_atomically_permissions_preservation(tmp_path):
    test_file = tmp_path / "perm_test.txt"
    test_file.write_text("initial")
    
    # Set custom permissions (e.g. read and write for owner, read for group, none for others: 0o640)
    original_mode = 0o640
    test_file.chmod(original_mode)
    
    # Check original permissions
    assert (test_file.stat().st_mode & 0o777) == original_mode

    # Perform atomic write
    write_atomically(test_file, "updated content")

    # Verify permissions are preserved
    assert (test_file.stat().st_mode & 0o777) == original_mode


def test_defeated_encoding_fallback(tmp_path):
    test_file = tmp_path / "encoding_test.txt"
    # Write some bytes representing invalid UTF-8 but valid Latin-1 (e.g. 0xff)
    test_file.write_bytes(b"hello \xff world")

    # Try reading as text. Since the preferred encoding utf-8 will fail, 
    # it should trigger fallback and successfully decode using latin-1.
    content = read_file_text(test_file, encoding="utf-8", errors="replace")
    
    # Check that it successfully decoded the latin-1 bytes instead of substituting with \ufffd
    assert content == "hello \u00ff world"
