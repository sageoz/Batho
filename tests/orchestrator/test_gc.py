from __future__ import annotations

import argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pytest

from batho.cli.gc import cmd_gc, register_gc_parser
from batho.orchestrator.gc import GCOptions, run_gc
from batho.modules.storage.sqlite_registry.engine import BathoDatabase, artifact_filename, _DB_CACHE, _DB_CACHE_LOCK

def close_all_databases():
    with _DB_CACHE_LOCK:
        for db in list(_DB_CACHE.values()):
            db.close()
        _DB_CACHE.clear()

@pytest.fixture(autouse=True)
def clean_caches():
    close_all_databases()
    from batho.core.config import _active_root, _get_config_cached_for_root
    _active_root.set(None)
    _get_config_cached_for_root.cache_clear()
    yield
    close_all_databases()
    _active_root.set(None)
    _get_config_cached_for_root.cache_clear()

@pytest.fixture
def test_db(tmp_path: Path) -> BathoDatabase:
    # Need to make it look like a valid batho project directory
    (tmp_path / "batho.yaml").write_text("indexer:\n  max_file_size_kb: 500\n")
    db_name = artifact_filename(tmp_path)
    db_path = tmp_path / db_name
    db = BathoDatabase(db_path, repo_root=tmp_path)
    return db

def test_delete_run_cascades(test_db: BathoDatabase):
    run_uuid = "test_run_123"
    internal_id = test_db.create_run(run_uuid, root_path=str(test_db._repo_root))
    
    # insert file artifact
    agent_view = {"entities": []}
    test_db.insert_file_artifact(
        internal_id, "main.py", "hash123", agent_view, {"entities": []}, []
    )
    
    # insert run artifact
    with test_db.connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO run_artifacts (run_id, schema_version) VALUES (?, 'run-artifacts.v1')",
            (internal_id,),
        )
        conn.commit()

    # Verify they exist
    with test_db.connection(read_only=True) as conn:
        assert conn.execute("SELECT COUNT(*) FROM index_runs").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM file_artifacts").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM run_artifacts").fetchone()[0] == 1

    # Delete run
    test_db.delete_run(run_uuid)

    # Verify they are cascaded deleted
    with test_db.connection(read_only=True) as conn:
        assert conn.execute("SELECT COUNT(*) FROM index_runs").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM file_artifacts").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM run_artifacts").fetchone()[0] == 0

def test_gc_status(test_db: BathoDatabase):
    options = GCOptions(root=test_db._repo_root, command="status")
    res = run_gc(options)
    assert res["success"]
    assert "Database size" in res["message"]
    assert "Total runs" in res["message"]

def test_gc_vacuum(test_db: BathoDatabase):
    options = GCOptions(root=test_db._repo_root, command="vacuum")
    res = run_gc(options)
    assert res["success"]
    assert "vacuum completed" in res["message"]

def test_gc_delete_run_command(test_db: BathoDatabase):
    run_uuid = "run_to_delete"
    test_db.create_run(run_uuid, root_path=str(test_db._repo_root))
    
    # Run GC delete run
    options = GCOptions(root=test_db._repo_root, command="run", run_uuid=run_uuid)
    res = run_gc(options)
    assert res["success"]
    assert "Successfully deleted run" in res["message"]
    assert test_db.get_run(run_uuid) is None

def test_gc_delete_runs_older_than(test_db: BathoDatabase):
    # Create an old run and a new run
    old_uuid = "old_run"
    new_uuid = "new_run"
    
    old_id = test_db.create_run(old_uuid, root_path=str(test_db._repo_root))
    new_id = test_db.create_run(new_uuid, root_path=str(test_db._repo_root))
    
    # Update old run's started_at in database
    old_time = datetime.now(timezone.utc) - timedelta(days=10)
    old_time_str = old_time.isoformat()
    
    with test_db.connection() as conn:
        conn.execute(
            "UPDATE index_runs SET started_at = ? WHERE id = ?",
            (old_time_str, old_id),
        )
        conn.commit()
        
    # Run gc older than 5 days
    options = GCOptions(root=test_db._repo_root, command="runs", older_than=5)
    res = run_gc(options)
    assert res["success"]
    assert "Successfully deleted 1 runs" in res["message"]
    
    assert test_db.get_run(old_uuid) is None
    assert test_db.get_run(new_uuid) is not None

def test_cli_gc_cmd(test_db: BathoDatabase, monkeypatch, capsys):
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    register_gc_parser(subparsers)
    
    args = parser.parse_args(["gc", "--root", str(test_db._repo_root), "status"])
    assert args.gc_command == "status"
    
    ret = cmd_gc(args)
    assert ret == 0
    captured = capsys.readouterr()
    assert "Total runs" in captured.out
